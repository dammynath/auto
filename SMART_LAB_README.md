# Smart Lab System

Smart spectroscopy data pipeline for organization, plotting, peak fitting,
scientific trend summaries, report generation, and dashboard review.

## Project Structure

```text
.
├── run_daily.py
├── dashboard.py
├── auto_runner.py
├── deploy_streamlit.py
├── report_generator_docx.py
├── ml_pipeline.py
├── train_ml.py
├── requirements.txt
├── smart_lab/
│   ├── __init__.py
│   ├── analysis.py
│   ├── config.py
│   ├── ingestion.py
│   ├── plotting.py
│   ├── reporting.py
│   └── state.py
└── outputs/                  # Created under the configured output directory
    ├── organized/
    ├── plots/
    ├── manifests/
    ├── reports/
    ├── logs/
    ├── models/
    └── state/
```

## What It Does

- Scans `C:/Users/NATHANAEL/Desktop/Exptal_Research`
- Detects experiment type from filename, folder path, and file structure
- Supports `.csv` and `.txt` spectral parsing
- Copies files into:

```text
outputs/organized/YYYY-MM-DD/experiment_type/
```

- Generates publication-style PNG plots in:

```text
outputs/plots/UV/
outputs/plots/PL/
outputs/plots/FTIR/
outputs/plots/lifetime/
```

- Performs peak analysis:
  - sampled peak position and signal
  - FWHM estimate
  - Gaussian center, amplitude, sigma, and fitted FWHM
- Performs first-pass lifetime fitting:
  - single exponential decay tau
- Performs first-pass drug sensing calibration when concentration can be read from filenames:
  - slope
  - intercept
  - LOD
- Generates reports:

```text
outputs/reports/daily_report.txt
outputs/reports/weekly_report.txt
outputs/reports/trends_summary.txt
outputs/reports/daily_report_YYYY-MM-DD.docx
outputs/reports/daily_report_YYYY-MM-DD.pdf
outputs/reports/weekly_report_YYYY-WW.docx
outputs/reports/weekly_report_YYYY-WW.pdf
```

- Writes reproducibility manifests:

```text
outputs/manifests/file_manifest.csv
outputs/manifests/plot_manifest.csv
outputs/manifests/analysis_results.csv
outputs/manifests/ml_predictions.csv
outputs/manifests/run_summary.json
```

- Supports continuous automation:
  - real-time folder watching
  - daily scheduled mode
  - SHA256 state tracking to avoid unnecessary reprocessing
  - log files under `outputs/logs`
- Supports ML:
  - Random Forest peak-position regression
  - Random Forest sample classification where labels can be inferred
  - Isolation Forest anomaly detection
  - saved models via `joblib`

## Run Locally

Install dependencies:

```bash
pip install -r requirements.txt
```

Run the daily pipeline:

```bash
python run_daily.py
```

Run with custom folders:

```bash
python run_daily.py --input-dir "C:/path/to/data" --output-dir "C:/path/to/report/folder"
```

Skip copied organization and only generate plots/manifests:

```bash
python run_daily.py --no-organize
```

Launch the dashboard:

```bash
streamlit run dashboard.py
```

Run the continuous watcher:

```bash
python auto_runner.py --mode watch
```

Run the daily scheduler loop at 20:00:

```bash
python auto_runner.py --mode schedule --time 20:00
```

Train ML models:

```bash
python train_ml.py
```

Start the dashboard as a background deployment:

```bash
python deploy_streamlit.py
```

See [AUTOMATION_AND_DEPLOYMENT.md](AUTOMATION_AND_DEPLOYMENT.md) for Windows Task Scheduler and cron setup.

## Future Improvements

- Add multi-peak fitting and baseline correction for complex PL/FTIR spectra
- Add replicate grouping and blank subtraction for drug sensing datasets
- Add `.docx` report export with embedded figures
- Add persistent run history so trend detection compares only new files
- Add curated experiment metadata entry in the dashboard
