# Smart Lab Automation, Reporting, and ML Deployment

## New Files

```text
auto_runner.py
deploy_streamlit.py
report_generator_docx.py
ml_pipeline.py
train_ml.py
smart_lab/state.py
```

## Dependencies

Install or update dependencies:

```bash
pip install -r requirements.txt
```

Additional packages used by this upgrade:

```text
watchdog
python-docx
reportlab
scikit-learn
joblib
```

## Continuous Automation

### One-shot incremental run

Processes only when new or changed supported files are detected:

```bash
python auto_runner.py --mode once
```

Force processing regardless of state:

```bash
python auto_runner.py --mode once --force
```

### Real-time file watcher

Watches the data directory indefinitely and triggers the pipeline when new files are created or modified:

```bash
python auto_runner.py --mode watch
```

### Long-running scheduled mode

Runs daily at 20:00 local time:

```bash
python auto_runner.py --mode schedule --time 20:00
```

## State Tracking

Processed file hashes and run history are stored in:

```text
C:/Users/NATHANAEL/Desktop/All/RSC Conference 2025/Weekly Report Ojo/outputs/state/automation_state.json
```

The runner avoids unnecessary reprocessing by comparing SHA256 hashes.

## Logs

Logs are written to:

```text
C:/Users/NATHANAEL/Desktop/All/RSC Conference 2025/Weekly Report Ojo/outputs/logs/automation.log
```

Example log output:

```text
2026-05-02 20:00:00 | INFO | smart_lab | Smart Lab automation started in once mode.
2026-05-02 20:00:01 | INFO | smart_lab | New or changed files detected: 14
2026-05-02 20:00:01 | INFO | smart_lab | Starting pipeline: python run_daily.py --input-dir ... --output-dir ...
2026-05-02 20:02:18 | INFO | smart_lab | Pipeline completed in 137.42 seconds; files processed: 14
2026-05-02 20:02:18 | INFO | smart_lab | Console alert: Smart Lab report generated | Pipeline completed in 137.42 seconds.
```

## Windows Task Scheduler Setup

Use PowerShell:

```powershell
$Action = New-ScheduledTaskAction `
  -Execute "python" `
  -Argument "`"C:\Users\NATHANAEL\Documents\Lab morning reports to Prof Oluwafemi\auto_runner.py`" --mode once --force"

$Trigger = New-ScheduledTaskTrigger -Daily -At 8:00pm

$Settings = New-ScheduledTaskSettingsSet `
  -AllowStartIfOnBatteries `
  -DontStopIfGoingOnBatteries `
  -StartWhenAvailable

Register-ScheduledTask `
  -TaskName "Smart Lab Daily Spectroscopy Pipeline" `
  -Action $Action `
  -Trigger $Trigger `
  -Settings $Settings `
  -Description "Runs Smart Lab spectroscopy pipeline daily at 8 PM."
```

Dashboard deployment task:

```powershell
$Action = New-ScheduledTaskAction `
  -Execute "python" `
  -Argument "`"C:\Users\NATHANAEL\Documents\Lab morning reports to Prof Oluwafemi\deploy_streamlit.py`""

$Trigger = New-ScheduledTaskTrigger -Daily -At 8:00pm

Register-ScheduledTask `
  -TaskName "Smart Lab Streamlit Dashboard" `
  -Action $Action `
  -Trigger $Trigger `
  -Description "Starts Smart Lab Streamlit dashboard daily at 8 PM."
```

## Cron Setup

Linux/macOS optional:

```bash
crontab -e
```

Add:

```cron
0 20 * * * cd "/path/to/Lab morning reports to Prof Oluwafemi" && python auto_runner.py --mode once --force
0 20 * * * cd "/path/to/Lab morning reports to Prof Oluwafemi" && python deploy_streamlit.py
```

## Notifications

Console logging is the fallback. Email alerts are enabled if these environment variables are set:

```text
SMART_LAB_SMTP_HOST
SMART_LAB_SMTP_PORT
SMART_LAB_EMAIL_FROM
SMART_LAB_EMAIL_TO
SMART_LAB_SMTP_PASSWORD
```

## RSC-style Word and PDF Reports

Generated automatically by `run_daily.py`.

Manual generation:

```bash
python report_generator_docx.py
```

Output files:

```text
outputs/reports/daily_report_YYYY-MM-DD.docx
outputs/reports/daily_report_YYYY-MM-DD.pdf
outputs/reports/weekly_report_YYYY-WW.docx
outputs/reports/weekly_report_YYYY-WW.pdf
```

Report structure:

```text
Title
Abstract
Introduction
Experimental Section
Results and Discussion
Figure captions
Conclusion
References placeholder
```

## Machine Learning

Train models from historical parsed spectra:

```bash
python train_ml.py
```

Models and metrics:

```text
outputs/models/smart_lab_models.joblib
outputs/models/ml_metrics.json
```

The daily pipeline automatically loads the saved model, predicts peak position/sample label where available, flags anomalies, and writes:

```text
outputs/manifests/ml_predictions.csv
outputs/plots/ml_predictions/
```

The ML module handles small datasets by skipping classification when there is only one class or too few samples.
