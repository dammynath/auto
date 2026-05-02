#!/usr/bin/env python3
"""Start the Smart Lab Streamlit dashboard as a background process."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

from smart_lab.config import DEFAULT_OUTPUT_DIR
from smart_lab.state import setup_logging


def is_process_running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--port", default="8501")
    parser.add_argument("--address", default="127.0.0.1")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    logs_dir = args.output_dir / "outputs" / "logs"
    logger = setup_logging(logs_dir, logger_name="smart_lab.deploy")
    pid_path = args.output_dir / "outputs" / "state" / "streamlit.pid"
    pid_path.parent.mkdir(parents=True, exist_ok=True)

    if pid_path.exists():
        try:
            pid = int(pid_path.read_text(encoding="utf-8").strip())
            if is_process_running(pid):
                logger.info("Streamlit already appears to be running with PID %s.", pid)
                print(f"Streamlit already running: http://{args.address}:{args.port}")
                return 0
        except ValueError:
            pass

    command = [
        sys.executable,
        "-m",
        "streamlit",
        "run",
        str(Path(__file__).with_name("dashboard.py")),
        "--server.address",
        args.address,
        "--server.port",
        str(args.port),
        "--server.headless",
        "true",
    ]
    stdout_path = logs_dir / "streamlit_stdout.log"
    stderr_path = logs_dir / "streamlit_stderr.log"
    stdout = stdout_path.open("a", encoding="utf-8")
    stderr = stderr_path.open("a", encoding="utf-8")
    process = subprocess.Popen(
        command,
        cwd=str(Path(__file__).parent),
        stdout=stdout,
        stderr=stderr,
        text=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    pid_path.write_text(str(process.pid), encoding="utf-8")
    logger.info("Started Streamlit dashboard with PID %s at http://%s:%s", process.pid, args.address, args.port)
    print(f"Streamlit dashboard started: http://{args.address}:{args.port}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
