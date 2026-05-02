"""Streamlit dashboard for the Smart Lab System."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pandas as pd
import streamlit as st

from smart_lab.analysis import analyze_spectra
from smart_lab.config import DEFAULT_OUTPUT_DIR
from smart_lab.ingestion import (
    FileRecord,
    classify_experiment,
    extract_experiment_date,
    parse_spectra,
    read_text_sample,
)
from smart_lab.plotting import plot_all_spectra


st.set_page_config(page_title="Smart Lab Dashboard", layout="wide")


def load_csv(path: Path) -> pd.DataFrame:
    if not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except Exception:
        return pd.DataFrame()


def show_plot_gallery(plot_manifest: pd.DataFrame) -> None:
    st.subheader("Generated Plots")
    if plot_manifest.empty:
        st.info("No plots found yet. Run `python run_daily.py` first.")
        return
    experiment_types = ["All"] + sorted(plot_manifest["experiment_type"].dropna().unique().tolist())
    selected_type = st.selectbox("Experiment type", experiment_types)
    filtered = plot_manifest if selected_type == "All" else plot_manifest[plot_manifest["experiment_type"] == selected_type]
    for _, row in filtered.head(80).iterrows():
        plot_path = Path(str(row["plot_path"]))
        if plot_path.exists():
            st.image(str(plot_path), caption=plot_path.name, use_container_width=True)


def show_results_table(results: pd.DataFrame) -> None:
    st.subheader("Extracted Results")
    if results.empty:
        st.info("No analysis results found yet.")
        return
    columns = [
        column
        for column in [
            "experiment_date",
            "experiment_type",
            "peak_x",
            "peak_y",
            "gaussian_center",
            "gaussian_fwhm",
            "lifetime_tau",
            "concentration",
            "lod",
            "status",
            "insight",
            "source_path",
        ]
        if column in results.columns
    ]
    st.dataframe(results[columns], use_container_width=True, hide_index=True)


def make_upload_record(uploaded_file, temp_path: Path) -> FileRecord:
    sample = read_text_sample(temp_path)
    experiment_type = classify_experiment(temp_path, sample)
    experiment_date = extract_experiment_date(temp_path, sample)
    stat = temp_path.stat()
    return FileRecord(
        source_path=str(temp_path),
        relative_path=uploaded_file.name,
        file_name=uploaded_file.name,
        extension=temp_path.suffix.lower(),
        size_bytes=stat.st_size,
        modified_time="uploaded",
        experiment_date=experiment_date.isoformat(),
        experiment_type=experiment_type,
    )


def upload_panel() -> None:
    st.subheader("Upload and Analyze")
    uploaded_files = st.file_uploader(
        "Upload CSV or TXT spectroscopy files",
        type=["csv", "txt"],
        accept_multiple_files=True,
    )
    if not uploaded_files:
        return

    with tempfile.TemporaryDirectory() as temp_dir_text:
        temp_dir = Path(temp_dir_text)
        records = []
        for uploaded_file in uploaded_files:
            temp_path = temp_dir / uploaded_file.name
            temp_path.write_bytes(uploaded_file.getbuffer())
            records.append(make_upload_record(uploaded_file, temp_path))

        spectra = parse_spectra(records)
        analysis_results = analyze_spectra(spectra)
        plots = plot_all_spectra(spectra, temp_dir / "plots")

        st.write(f"Parsed spectra: {len(spectra)}")
        if analysis_results:
            st.dataframe(pd.DataFrame([result.__dict__ for result in analysis_results]), use_container_width=True)
        for plot in plots:
            st.image(plot.plot_path, caption=Path(plot.plot_path).name, use_container_width=True)


def main() -> None:
    st.title("Smart Lab Dashboard")
    output_dir = Path(
        st.sidebar.text_input("Output directory", value=str(DEFAULT_OUTPUT_DIR))
    )
    manifests_dir = output_dir / "outputs" / "manifests"
    reports_dir = output_dir / "outputs" / "reports"

    file_manifest = load_csv(manifests_dir / "file_manifest.csv")
    plot_manifest = load_csv(manifests_dir / "plot_manifest.csv")
    analysis_results = load_csv(manifests_dir / "analysis_results.csv")
    ml_predictions = load_csv(manifests_dir / "ml_predictions.csv")

    st.sidebar.metric("Files", len(file_manifest))
    st.sidebar.metric("Plots", len(plot_manifest))
    st.sidebar.metric("Analyzed", len(analysis_results))
    st.sidebar.metric("ML predictions", len(ml_predictions))

    tabs = st.tabs(["Overview", "Plots", "Results", "ML", "Reports", "Upload"])
    with tabs[0]:
        st.subheader("Run Overview")
        if file_manifest.empty:
            st.info("No run data found. Run `python run_daily.py` to generate manifests.")
        else:
            st.dataframe(file_manifest, use_container_width=True, hide_index=True)
    with tabs[1]:
        show_plot_gallery(plot_manifest)
    with tabs[2]:
        show_results_table(analysis_results)
    with tabs[3]:
        st.subheader("Machine Learning Predictions")
        if ml_predictions.empty:
            st.info("No ML predictions found. Train models with `python train_ml.py`, then run `python run_daily.py`.")
        else:
            st.dataframe(ml_predictions, use_container_width=True, hide_index=True)
            if "plot_path" in ml_predictions.columns:
                for _, row in ml_predictions.head(30).iterrows():
                    plot_path = Path(str(row.get("plot_path", "")))
                    if plot_path.exists():
                        st.image(str(plot_path), caption=plot_path.name, use_container_width=True)
    with tabs[4]:
        st.subheader("Reports")
        for report_name in ["daily_report.txt", "weekly_report.txt", "trends_summary.txt"]:
            report_path = reports_dir / report_name
            if report_path.exists():
                st.markdown(f"**{report_name}**")
                st.text_area(report_name, report_path.read_text(encoding="utf-8"), height=260)
    with tabs[5]:
        upload_panel()


if __name__ == "__main__":
    main()
