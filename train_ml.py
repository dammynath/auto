#!/usr/bin/env python3
"""Train Smart Lab ML models from historical spectroscopy data."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from ml_pipeline import train_models
from smart_lab.config import DEFAULT_INPUT_DIR, DEFAULT_OUTPUT_DIR
from smart_lab.ingestion import parse_spectra, scan_input_folder


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
    print(f"Model directory: {args.output_dir / 'outputs' / 'models'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
