#!/usr/bin/env python3
"""Machine learning pipeline for spectral prediction and anomaly detection."""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path

import joblib
import matplotlib
import numpy as np
from sklearn.ensemble import IsolationForest, RandomForestClassifier, RandomForestRegressor
from sklearn.metrics import accuracy_score, mean_squared_error
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import LabelEncoder

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from smart_lab.config import DEFAULT_INPUT_DIR, DEFAULT_OUTPUT_DIR
from smart_lab.ingestion import SpectrumData, parse_spectra, scan_input_folder, safe_name, unique_path


GRID_MIN = 150.0
GRID_MAX = 1200.0
GRID_POINTS = 300


@dataclass
class MLPrediction:
    source_path: str
    experiment_date: str
    experiment_type: str
    predicted_peak_x: float | None
    predicted_label: str | None
    anomaly_score: float | None
    is_anomaly: bool
    plot_path: str = ""


def normalize_signal(y_values: np.ndarray) -> np.ndarray:
    y_values = np.asarray(y_values, dtype=float)
    y_values = np.nan_to_num(y_values, nan=0.0, posinf=0.0, neginf=0.0)
    y_min = float(np.min(y_values))
    y_max = float(np.max(y_values))
    if y_max <= y_min:
        return np.zeros_like(y_values)
    return (y_values - y_min) / (y_max - y_min)


def spectrum_to_vector(spectrum: SpectrumData, grid: np.ndarray | None = None) -> np.ndarray:
    grid = grid if grid is not None else np.linspace(GRID_MIN, GRID_MAX, GRID_POINTS)
    x_values = np.asarray(spectrum.x_values, dtype=float)
    y_values = normalize_signal(np.asarray(spectrum.y_values, dtype=float))
    mask = np.isfinite(x_values) & np.isfinite(y_values)
    x_values = x_values[mask]
    y_values = y_values[mask]
    if x_values.size < 2:
        return np.zeros(grid.shape)
    order = np.argsort(x_values)
    x_values = x_values[order]
    y_values = y_values[order]
    return np.interp(grid, x_values, y_values, left=0.0, right=0.0)


def infer_sample_label(source_path: str) -> str:
    name = Path(source_path).stem.lower()
    tokens = re.split(r"[^a-zA-Z0-9]+", name)
    tokens = [token for token in tokens if token and not token.isdigit()]
    if "cetirizine" in tokens or "cz" in tokens:
        return "analyte_present"
    if "ais" in tokens and "zns" in tokens:
        return "AIS_ZnS"
    if "ais" in tokens:
        return "AIS"
    if "cis" in tokens and "zns" in tokens:
        return "CIS_ZnS"
    return tokens[0] if tokens else "unknown"


def actual_peak_x(spectrum: SpectrumData) -> float:
    vector = normalize_signal(np.asarray(spectrum.y_values, dtype=float))
    x_values = np.asarray(spectrum.x_values, dtype=float)
    if vector.size == 0:
        return 0.0
    return float(x_values[int(np.argmax(vector))])


def prepare_dataset(spectra: list[SpectrumData]) -> tuple[np.ndarray, np.ndarray, np.ndarray, list[SpectrumData], LabelEncoder]:
    usable = [spectrum for spectrum in spectra if spectrum.experiment_type in {"UV", "PL", "FTIR"}]
    grid = np.linspace(GRID_MIN, GRID_MAX, GRID_POINTS)
    features = np.asarray([spectrum_to_vector(spectrum, grid) for spectrum in usable], dtype=float)
    peak_targets = np.asarray([actual_peak_x(spectrum) for spectrum in usable], dtype=float)
    labels = [infer_sample_label(spectrum.source_path) for spectrum in usable]
    encoder = LabelEncoder()
    encoded_labels = encoder.fit_transform(labels) if labels else np.asarray([])
    return features, peak_targets, encoded_labels, usable, encoder


def train_models(spectra: list[SpectrumData], model_dir: Path) -> dict:
    model_dir.mkdir(parents=True, exist_ok=True)
    features, peak_targets, labels, usable, encoder = prepare_dataset(spectra)
    metrics: dict = {"samples": int(features.shape[0]), "models": {}}
    if features.shape[0] < 5:
        metrics["status"] = "insufficient_data"
        return metrics

    model_bundle = {
        "grid_min": GRID_MIN,
        "grid_max": GRID_MAX,
        "grid_points": GRID_POINTS,
        "label_encoder": encoder,
        "regressor": None,
        "classifier": None,
        "anomaly_detector": None,
    }

    test_size = 0.25 if features.shape[0] >= 12 else 0.4
    x_train, x_test, y_train, y_test = train_test_split(features, peak_targets, test_size=test_size, random_state=42)
    regressor = RandomForestRegressor(n_estimators=120, random_state=42, min_samples_leaf=2)
    regressor.fit(x_train, y_train)
    predicted = regressor.predict(x_test)
    rmse = float(mean_squared_error(y_test, predicted, squared=False))
    model_bundle["regressor"] = regressor
    metrics["models"]["peak_regression"] = {"rmse": rmse, "test_samples": int(len(y_test))}

    if len(set(labels.tolist())) >= 2 and features.shape[0] >= 6:
        stratify = labels if min(np.bincount(labels)) >= 2 else None
        x_train_c, x_test_c, y_train_c, y_test_c = train_test_split(
            features, labels, test_size=test_size, random_state=42, stratify=stratify
        )
        classifier = RandomForestClassifier(n_estimators=120, random_state=42, min_samples_leaf=1)
        classifier.fit(x_train_c, y_train_c)
        class_pred = classifier.predict(x_test_c)
        accuracy = float(accuracy_score(y_test_c, class_pred))
        model_bundle["classifier"] = classifier
        metrics["models"]["classification"] = {"accuracy": accuracy, "test_samples": int(len(y_test_c))}
    else:
        metrics["models"]["classification"] = {"status": "skipped_single_class_or_small_dataset"}

    contamination = min(0.1, max(0.02, 1.0 / features.shape[0]))
    anomaly_detector = IsolationForest(contamination=contamination, random_state=42)
    anomaly_detector.fit(features)
    model_bundle["anomaly_detector"] = anomaly_detector
    anomaly_flags = anomaly_detector.predict(features)
    metrics["models"]["anomaly_detection"] = {"flagged_training_anomalies": int(np.sum(anomaly_flags == -1))}

    joblib.dump(model_bundle, model_dir / "smart_lab_models.joblib")
    (model_dir / "ml_metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    return metrics


def load_models(model_dir: Path) -> dict | None:
    model_path = model_dir / "smart_lab_models.joblib"
    if not model_path.exists():
        return None
    return joblib.load(model_path)


def plot_prediction(spectrum: SpectrumData, prediction: MLPrediction, output_dir: Path) -> str:
    output_dir.mkdir(parents=True, exist_ok=True)
    target = unique_path(output_dir / f"{safe_name(Path(spectrum.source_path).stem)}_ml_prediction.png")
    x_values = np.asarray(spectrum.x_values, dtype=float)
    y_values = normalize_signal(np.asarray(spectrum.y_values, dtype=float))
    fig, ax = plt.subplots(figsize=(8, 5), dpi=160)
    ax.plot(x_values, y_values, color="#1f77b4", linewidth=1.2, label="Actual normalized spectrum")
    if prediction.predicted_peak_x is not None:
        ax.axvline(prediction.predicted_peak_x, color="#d62728", linestyle="--", label="Predicted peak")
    ax.set_xlabel("Spectral coordinate")
    ax.set_ylabel("Normalized signal")
    ax.set_title(Path(spectrum.source_path).stem)
    ax.legend()
    ax.grid(True, alpha=0.25)
    fig.tight_layout()
    fig.savefig(target)
    plt.close(fig)
    return str(target)


def predict_spectra(spectra: list[SpectrumData], model_dir: Path, output_dir: Path) -> list[MLPrediction]:
    bundle = load_models(model_dir)
    if bundle is None:
        return []
    grid = np.linspace(bundle["grid_min"], bundle["grid_max"], bundle["grid_points"])
    encoder = bundle.get("label_encoder")
    predictions: list[MLPrediction] = []
    for spectrum in spectra:
        vector = spectrum_to_vector(spectrum, grid).reshape(1, -1)
        predicted_peak = None
        predicted_label = None
        anomaly_score = None
        is_anomaly = False
        if bundle.get("regressor") is not None:
            predicted_peak = float(bundle["regressor"].predict(vector)[0])
        if bundle.get("classifier") is not None and encoder is not None:
            label_id = int(bundle["classifier"].predict(vector)[0])
            predicted_label = str(encoder.inverse_transform([label_id])[0])
        if bundle.get("anomaly_detector") is not None:
            anomaly_score = float(bundle["anomaly_detector"].decision_function(vector)[0])
            is_anomaly = bool(bundle["anomaly_detector"].predict(vector)[0] == -1)
        prediction = MLPrediction(
            source_path=spectrum.source_path,
            experiment_date=spectrum.experiment_date,
            experiment_type=spectrum.experiment_type,
            predicted_peak_x=predicted_peak,
            predicted_label=predicted_label,
            anomaly_score=anomaly_score,
            is_anomaly=is_anomaly,
        )
        prediction.plot_path = plot_prediction(spectrum, prediction, output_dir)
        predictions.append(prediction)
    return predictions


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, default=DEFAULT_INPUT_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    records = scan_input_folder(args.input_dir)
    spectra = parse_spectra(records)
    metrics = train_models(spectra, args.output_dir / "outputs" / "models")
    print(json.dumps(metrics, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
