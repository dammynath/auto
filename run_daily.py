#!/usr/bin/env python3
"""Run the first Smart Lab pipeline slice: organize files and generate plots."""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
from dataclasses import asdict
from pathlib import Path

from smart_lab.analysis import analyze_spectra
from smart_lab.config import DEFAULT_INPUT_DIR, DEFAULT_OUTPUT_DIR, LabConfig
from smart_lab.ingestion import organize_files, parse_spectra, scan_input_folder, write_manifest
from smart_lab.plotting import plot_all_spectra
from smart_lab.reporting import analysis_rows, write_reports

try:
    from report_generator_docx import generate_all_reports
except Exception:
    generate_all_reports = None

try:
    from ml_pipeline import predict_spectra
except Exception:
    predict_spectra = None


def write_plot_manifest(plot_records, target: Path) -> None:
    """Write generated plot metadata for reproducibility."""

    rows = [asdict(record) for record in plot_records]
    target.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        target.write_text("", encoding="utf-8")
        return
    with target.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def write_rows(rows: list[dict], target: Path) -> None:
    """Write arbitrary rows to CSV."""

    target.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        target.write_text("", encoding="utf-8")
        return
    with target.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def build_summary(records, spectra, plot_records, analysis_results, report_paths, document_reports=None, ml_predictions=None) -> dict:
    """Build a compact JSON summary for the run."""

    by_type: dict[str, int] = {}
    by_date: dict[str, int] = {}
    for record in records:
        by_type[record.experiment_type] = by_type.get(record.experiment_type, 0) + 1
        by_date[record.experiment_date] = by_date.get(record.experiment_date, 0) + 1
    return {
        "files_scanned": len(records),
        "spectra_parsed": len(spectra),
        "plots_generated": len(plot_records),
        "analysis_results": len(analysis_results),
        "reports": report_paths,
        "document_reports": document_reports or {},
        "ml_predictions": len(ml_predictions or []),
        "files_by_type": dict(sorted(by_type.items())),
        "files_by_date": dict(sorted(by_date.items())),
    }


def run_pipeline(config: LabConfig, organize: bool = True) -> dict:
    """Run organization and plotting."""

    config.output_dir.mkdir(parents=True, exist_ok=True)
    config.manifests_dir.mkdir(parents=True, exist_ok=True)
    config.plots_dir.mkdir(parents=True, exist_ok=True)
    config.reports_dir.mkdir(parents=True, exist_ok=True)

    records = scan_input_folder(config.input_dir)
    if organize:
        organize_files(records, config.organized_dir, copy_files=True)

    spectra = parse_spectra(records)
    plot_records = plot_all_spectra(spectra, config.plots_dir)
    analysis_results = analyze_spectra(spectra)
    report_paths = write_reports(records, analysis_results, plot_records, config.reports_dir)

    write_manifest(records, config.manifests_dir / "file_manifest.csv")
    write_plot_manifest(plot_records, config.manifests_dir / "plot_manifest.csv")
    write_rows(analysis_rows(analysis_results), config.manifests_dir / "analysis_results.csv")

    ml_predictions = []
    if predict_spectra is not None:
        try:
            ml_predictions = predict_spectra(
                spectra,
                config.output_dir / "outputs" / "models",
                config.output_dir / "outputs" / "plots" / "ml_predictions",
            )
            write_rows([asdict(prediction) for prediction in ml_predictions], config.manifests_dir / "ml_predictions.csv")
        except Exception as exc:
            write_rows([{"error": str(exc)}], config.manifests_dir / "ml_predictions.csv")

    document_reports = {}
    if generate_all_reports is not None:
        try:
            document_reports = generate_all_reports(config.output_dir, dt.date.today())
        except Exception as exc:
            document_reports = {"error": str(exc)}

    summary = build_summary(records, spectra, plot_records, analysis_results, report_paths, document_reports, ml_predictions)
    summary_path = config.manifests_dir / "run_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, default=DEFAULT_INPUT_DIR, help="Raw spectroscopy input folder")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR, help="Smart Lab output folder")
    parser.add_argument(
        "--no-organize",
        action="store_true",
        help="Skip copied organization and only parse/plot from raw files",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = LabConfig(input_dir=args.input_dir, output_dir=args.output_dir)
    summary = run_pipeline(config, organize=not args.no_organize)
    print(json.dumps(summary, indent=2))
    print(f"Outputs written under: {config.output_dir / 'outputs'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
