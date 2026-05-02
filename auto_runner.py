#!/usr/bin/env python3
"""Continuous automation runner for the Smart Lab spectroscopy pipeline.

Modes:
- once: run one incremental check and process if new files exist
- watch: real-time watchdog monitoring
- schedule: long-running daily scheduler loop
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import smtplib
import subprocess
import sys
import time
from email.message import EmailMessage
from pathlib import Path
from threading import Lock, Timer
from typing import Iterable

from smart_lab.config import DEFAULT_INPUT_DIR, DEFAULT_OUTPUT_DIR, LabConfig
from smart_lab.ingestion import RELATED_EXTENSIONS
from smart_lab.state import StateStore, setup_logging

try:
    from watchdog.events import FileSystemEventHandler
    from watchdog.observers import Observer
except Exception:  # watchdog is optional until watch mode is used
    FileSystemEventHandler = object
    Observer = None


DEBOUNCE_SECONDS = 10


def discover_candidate_files(input_dir: Path) -> list[Path]:
    """Return supported files under the data folder."""

    if not input_dir.exists():
        return []
    return [
        path
        for path in input_dir.rglob("*")
        if path.is_file() and path.suffix.lower() in RELATED_EXTENSIONS
    ]


def find_new_files(input_dir: Path, state: StateStore) -> list[Path]:
    """Find files not yet processed at their current hash."""

    new_files = []
    for path in discover_candidate_files(input_dir):
        try:
            if not state.is_processed(path):
                new_files.append(path)
        except OSError:
            continue
    return new_files


def send_notification(subject: str, body: str, logger) -> None:
    """Send optional SMTP email notification, otherwise log console fallback."""

    host = os.getenv("SMART_LAB_SMTP_HOST")
    sender = os.getenv("SMART_LAB_EMAIL_FROM")
    recipient = os.getenv("SMART_LAB_EMAIL_TO")
    password = os.getenv("SMART_LAB_SMTP_PASSWORD")
    port = int(os.getenv("SMART_LAB_SMTP_PORT", "587"))
    if not all([host, sender, recipient, password]):
        logger.info("Console alert: %s | %s", subject, body.replace("\n", " "))
        return

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = sender
    message["To"] = recipient
    message.set_content(body)
    try:
        with smtplib.SMTP(host, port, timeout=30) as server:
            server.starttls()
            server.login(sender, password)
            server.send_message(message)
        logger.info("Email notification sent to %s", recipient)
    except Exception as exc:
        logger.exception("Email notification failed: %s", exc)


def run_daily_pipeline(config: LabConfig, logger) -> dict:
    """Call run_daily.py as a subprocess and return its parsed summary when possible."""

    command = [
        sys.executable,
        str(Path(__file__).with_name("run_daily.py")),
        "--input-dir",
        str(config.input_dir),
        "--output-dir",
        str(config.output_dir),
    ]
    logger.info("Starting pipeline: %s", " ".join(command))
    completed = subprocess.run(
        command,
        cwd=str(Path(__file__).parent),
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.stdout:
        logger.info("Pipeline stdout: %s", completed.stdout.strip())
    if completed.stderr:
        logger.warning("Pipeline stderr: %s", completed.stderr.strip())
    if completed.returncode != 0:
        raise RuntimeError(f"run_daily.py failed with exit code {completed.returncode}")

    summary_path = config.manifests_dir / "run_summary.json"
    if summary_path.exists():
        try:
            return json.loads(summary_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
    return {}


def process_if_needed(config: LabConfig, state: StateStore, logger, force: bool = False) -> dict:
    """Run pipeline when new files are present, then update state."""

    started = time.perf_counter()
    new_files = discover_candidate_files(config.input_dir) if force else find_new_files(config.input_dir, state)
    if not new_files and not force:
        logger.info("No new files detected; skipping pipeline.")
        return {"status": "skipped", "new_files": 0}

    logger.info("New or changed files detected: %d", len(new_files))
    try:
        summary = run_daily_pipeline(config, logger)
        for path in new_files:
            try:
                state.mark_processed(path, summary)
            except OSError as exc:
                logger.warning("Could not mark processed file %s: %s", path, exc)
        duration = time.perf_counter() - started
        state.add_run("success", duration, [str(path) for path in new_files], summary)
        logger.info("Pipeline completed in %.2f seconds; files processed: %d", duration, len(new_files))
        send_notification(
            "Smart Lab report generated",
            f"Pipeline completed in {duration:.2f} seconds.\nFiles processed: {len(new_files)}\nSummary: {summary}",
            logger,
        )
        return {"status": "success", "new_files": len(new_files), "summary": summary}
    except Exception as exc:
        duration = time.perf_counter() - started
        logger.exception("Pipeline failed after %.2f seconds: %s", duration, exc)
        state.add_run("failed", duration, [str(path) for path in new_files], {"error": str(exc)})
        send_notification("Smart Lab pipeline failed", str(exc), logger)
        return {"status": "failed", "new_files": len(new_files), "error": str(exc)}


class DebouncedHandler(FileSystemEventHandler):
    """Watchdog event handler that debounces bursts of file writes."""

    def __init__(self, config: LabConfig, state: StateStore, logger):
        self.config = config
        self.state = state
        self.logger = logger
        self.lock = Lock()
        self.timer: Timer | None = None

    def on_created(self, event):  # noqa: N802 - watchdog API
        self._schedule(event)

    def on_modified(self, event):  # noqa: N802 - watchdog API
        self._schedule(event)

    def _schedule(self, event) -> None:
        if getattr(event, "is_directory", False):
            return
        path = Path(getattr(event, "src_path", ""))
        if path.suffix.lower() not in RELATED_EXTENSIONS:
            return
        with self.lock:
            if self.timer:
                self.timer.cancel()
            self.logger.info("File event detected: %s", path)
            self.timer = Timer(DEBOUNCE_SECONDS, process_if_needed, args=[self.config, self.state, self.logger])
            self.timer.daemon = True
            self.timer.start()


def run_watch_mode(config: LabConfig, state: StateStore, logger) -> None:
    """Continuously watch the input folder using watchdog."""

    if Observer is None:
        raise RuntimeError("watchdog is not installed. Run `pip install watchdog`.")
    event_handler = DebouncedHandler(config, state, logger)
    observer = Observer()
    observer.schedule(event_handler, str(config.input_dir), recursive=True)
    observer.start()
    logger.info("Watching %s indefinitely.", config.input_dir)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Stopping watcher.")
    finally:
        observer.stop()
        observer.join()


def seconds_until_time(time_text: str) -> float:
    """Return seconds until next HH:MM local time."""

    hour, minute = [int(part) for part in time_text.split(":", 1)]
    now = dt.datetime.now()
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= now:
        target += dt.timedelta(days=1)
    return (target - now).total_seconds()


def run_schedule_mode(config: LabConfig, state: StateStore, logger, daily_time: str) -> None:
    """Run pipeline once per day at HH:MM."""

    logger.info("Scheduled mode active; daily run time: %s", daily_time)
    while True:
        wait_seconds = seconds_until_time(daily_time)
        logger.info("Next scheduled run in %.1f minutes.", wait_seconds / 60)
        time.sleep(wait_seconds)
        process_if_needed(config, state, logger, force=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["once", "watch", "schedule"], default="once")
    parser.add_argument("--input-dir", type=Path, default=DEFAULT_INPUT_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--time", default="20:00", help="Daily scheduled time in HH:MM local time")
    parser.add_argument("--force", action="store_true", help="Run even when no new file hashes are detected")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = LabConfig(input_dir=args.input_dir, output_dir=args.output_dir)
    logs_dir = config.output_dir / "outputs" / "logs"
    state = StateStore(config.output_dir / "outputs" / "state" / "automation_state.json")
    logger = setup_logging(logs_dir)

    logger.info("Smart Lab automation started in %s mode.", args.mode)
    if args.mode == "once":
        result = process_if_needed(config, state, logger, force=args.force)
        print(json.dumps(result, indent=2))
        return 0 if result["status"] != "failed" else 1
    if args.mode == "watch":
        run_watch_mode(config, state, logger)
        return 0
    run_schedule_mode(config, state, logger, args.time)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
