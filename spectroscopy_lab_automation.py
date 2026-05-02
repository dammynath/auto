#!/usr/bin/env python3
"""Scan, organize, plot, and summarize spectroscopy lab data.

Default behavior is conservative: source files are copied into an organized
output folder, not moved. Use --move only when you intentionally want to
relocate originals.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import math
import re
import shutil
from dataclasses import asdict, dataclass
from pathlib import Path
from statistics import mean
from typing import Iterable

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt


DEFAULT_SOURCE = Path(r"C:\Users\NATHANAEL\Desktop\Exptal_Research")
DEFAULT_OUTPUT = Path.cwd() / "lab_analysis_output"

DATA_EXTENSIONS = {".csv", ".txt"}
ALL_RELEVANT_EXTENSIONS = DATA_EXTENSIONS | {
    ".asc",
    ".sp",
    ".fs",
    ".fl",
    ".fs2f",
    ".jws",
    ".xlsx",
    ".png",
    ".pdf",
    ".docx",
}

TYPE_PATTERNS = {
    "UV-Vis": [
        r"\buv\b",
        r"uv[-_ ]?vis",
        r"ultraviolet",
        r"absorb",
        r"jasco",
        r"ojo_uv",
    ],
    "Photoluminescence": [
        r"\bpl\b",
        r"\bem\b",
        r"emission",
        r"excitation",
        r"fluores",
        r"lumines",
        r"rf-6000",
        r"ojo_pl",
    ],
    "FTIR": [
        r"\bftir\b",
        r"infrared",
        r"transmittance",
        r"wavenumber",
    ],
    "Lifetime": [
        r"lifetime",
        r"decay",
        r"\btau\b",
        r"tcspc",
    ],
}


@dataclass
class FileRecord:
    source: str
    relative_path: str
    extension: str
    size_bytes: int
    modified: str
    experiment_date: str
    experiment_type: str
    organized_path: str = ""


@dataclass
class SpectrumResult:
    source: str
    experiment_date: str
    experiment_type: str
    n_points: int
    x_min: float
    x_max: float
    y_min: float
    y_max: float
    peak_x: float
    peak_y: float
    plot_path: str = ""


def safe_name(text: str, max_len: int = 140) -> str:
    text = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", text)
    text = re.sub(r"\s+", " ", text).strip(" .")
    return (text[:max_len].strip(" .") or "untitled")


def file_text_hint(path: Path, limit: int = 4096) -> str:
    if path.suffix.lower() not in DATA_EXTENSIONS:
        return ""
    try:
        return path.read_text(encoding="utf-8", errors="ignore")[:limit]
    except OSError:
        return ""


def detect_type(path: Path, hint: str = "") -> str:
    text = f"{path} {hint[:1000]}".lower()
    scores: dict[str, int] = {}
    for experiment_type, patterns in TYPE_PATTERNS.items():
        scores[experiment_type] = sum(1 for pattern in patterns if re.search(pattern, text, re.I))
    if scores and max(scores.values()) > 0:
        return max(scores, key=scores.get)
    return "Other"


def valid_lab_date(value: dt.date) -> bool:
    current_year = dt.date.today().year
    return 2024 <= value.year <= current_year + 1


def parse_date_from_text(text: str) -> dt.date | None:
    patterns = [
        (r"(?<!\d)(20\d{2})[-_/ ]?([01]\d)[-_/ ]?([0-3]\d)(?!\d)", "ymd"),
        (r"(?<!\d)([0-3]\d)[-_/ ]?([01]\d)[-_/ ]?(20\d{2})(?!\d)", "dmy"),
        (r"(?<!\d)([0-3]\d)([01]\d)(\d{2})(?!\d)", "dmy2"),
        (r"(?<!\d)(\d{2})([01]\d)(20\d{2})(?!\d)", "dmy"),
        (r"\b(\d{1,2})\s+(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+(20\d{2})\b", "dmony"),
    ]
    months = {
        "jan": 1,
        "feb": 2,
        "mar": 3,
        "apr": 4,
        "may": 5,
        "jun": 6,
        "jul": 7,
        "aug": 8,
        "sep": 9,
        "oct": 10,
        "nov": 11,
        "dec": 12,
    }
    for pattern, style in patterns:
        match = re.search(pattern, text, re.I)
        if not match:
            continue
        try:
            if style == "ymd":
                year, month, day = map(int, match.groups())
            elif style == "dmy":
                day, month, year = map(int, match.groups())
            elif style == "dmy2":
                day, month, yy = map(int, match.groups())
                year = 2000 + yy
            else:
                day = int(match.group(1))
                month = months[match.group(2).lower()[:3]]
                year = int(match.group(3))
            value = dt.date(year, month, day)
            if valid_lab_date(value):
                return value
        except ValueError:
            continue
    return None


def metadata_date_hint(text: str) -> str:
    lines = []
    for line in text.splitlines()[:80]:
        if re.search(r"\b(date|date/time|time)\b", line, re.I):
            lines.append(line)
    return " ".join(lines)


def extract_date(path: Path, hint: str = "") -> dt.date:
    path_text = " ".join(path.parts)
    parsed = parse_date_from_text(path_text)
    if parsed:
        return parsed
    parsed = parse_date_from_text(metadata_date_hint(hint))
    if parsed:
        return parsed
    return dt.date.fromtimestamp(path.stat().st_mtime)


def parse_number(token: str) -> float | None:
    token = token.strip().strip('"')
    if not token:
        return None
    # LabSolutions exports often use decimal commas with semicolon separators.
    if "," in token and "." not in token:
        token = token.replace(",", ".")
    token = token.replace(" ", "")
    try:
        value = float(token)
    except ValueError:
        return None
    if math.isfinite(value):
        return value
    return None


def numeric_pairs_from_line(line: str) -> tuple[float, float] | None:
    stripped = line.strip()
    if not stripped:
        return None
    if ";" in stripped:
        parts = stripped.split(";")
    elif "\t" in stripped:
        parts = stripped.split("\t")
    else:
        parts = stripped.split(",")
    values = [parse_number(part) for part in parts[:4]]
    values = [value for value in values if value is not None]
    if len(values) >= 2:
        return values[0], values[1]
    return None


def read_spectrum(path: Path) -> list[tuple[float, float]]:
    points: list[tuple[float, float]] = []
    in_xy_block = False
    try:
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return points
    for line in lines:
        if line.strip().upper().startswith("XYDATA"):
            in_xy_block = True
            continue
        pair = numeric_pairs_from_line(line)
        if pair is None:
            continue
        x, y = pair
        if in_xy_block or plausible_spectrum_point(x, y):
            points.append((x, y))
    points = remove_duplicate_header_rows(points)
    if len(points) < 10:
        return []
    return points


def filter_points_for_type(points: list[tuple[float, float]], experiment_type: str) -> list[tuple[float, float]]:
    if experiment_type in {"UV-Vis", "Photoluminescence"}:
        filtered = [(x, y) for x, y in points if 150 <= x <= 1200]
    elif experiment_type == "FTIR":
        filtered = [(x, y) for x, y in points if 350 <= x <= 4500]
    else:
        filtered = points
    if len(filtered) >= 10:
        return filtered
    return []


def plausible_spectrum_point(x: float, y: float) -> bool:
    return -10000 <= x <= 10000 and -1e8 <= y <= 1e8


def remove_duplicate_header_rows(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
    cleaned: list[tuple[float, float]] = []
    for x, y in points:
        if cleaned and x == cleaned[-1][0] and y == cleaned[-1][1]:
            continue
        cleaned.append((x, y))
    return cleaned


def scan_files(source: Path) -> list[FileRecord]:
    records: list[FileRecord] = []
    for path in source.rglob("*"):
        if not path.is_file():
            continue
        ext = path.suffix.lower()
        if ext not in ALL_RELEVANT_EXTENSIONS:
            continue
        hint = file_text_hint(path)
        experiment_date = extract_date(path, hint)
        experiment_type = detect_type(path, hint)
        records.append(
            FileRecord(
                source=str(path),
                relative_path=str(path.relative_to(source)),
                extension=ext,
                size_bytes=path.stat().st_size,
                modified=dt.datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds"),
                experiment_date=experiment_date.isoformat(),
                experiment_type=experiment_type,
            )
        )
    return records


def organize_files(records: list[FileRecord], source: Path, output: Path, move: bool = False) -> None:
    organized_root = output / "organized_files"
    for record in records:
        src = Path(record.source)
        rel_parent = Path(record.relative_path).parent
        target_dir = organized_root / record.experiment_date / safe_name(record.experiment_type) / rel_parent
        target_dir.mkdir(parents=True, exist_ok=True)
        target = unique_path(target_dir / src.name)
        if move:
            shutil.move(str(src), str(target))
            record.source = str(target)
        else:
            shutil.copy2(src, target)
        record.organized_path = str(target)


def unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    stem, suffix = path.stem, path.suffix
    for i in range(1, 10000):
        candidate = path.with_name(f"{stem}_{i}{suffix}")
        if not candidate.exists():
            return candidate
    raise RuntimeError(f"Could not create unique path for {path}")


def plot_spectrum(points: list[tuple[float, float]], result: SpectrumResult, output_dir: Path) -> str:
    output_dir.mkdir(parents=True, exist_ok=True)
    source = Path(result.source)
    plot_path = unique_path(output_dir / f"{safe_name(source.stem)}.png")
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]

    fig, ax = plt.subplots(figsize=(8, 5), dpi=160)
    ax.plot(xs, ys, linewidth=1.5)
    ax.scatter([result.peak_x], [result.peak_y], s=22, zorder=3)
    ax.set_title(f"{result.experiment_type}: {source.stem}")
    x_label = "Wavelength (nm)"
    y_label = "Absorbance" if result.experiment_type == "UV-Vis" else "Intensity (a.u.)"
    if result.experiment_type == "FTIR":
        x_label = "Wavenumber (cm^-1)"
        y_label = "Transmittance / Absorbance"
    ax.set_xlabel(x_label)
    ax.set_ylabel(y_label)
    ax.grid(True, alpha=0.25)
    fig.tight_layout()
    fig.savefig(plot_path)
    plt.close(fig)
    return str(plot_path)


def analyze_spectra(records: list[FileRecord], output: Path) -> list[SpectrumResult]:
    results: list[SpectrumResult] = []
    for record in records:
        if record.extension not in DATA_EXTENSIONS:
            continue
        if record.experiment_type not in {"UV-Vis", "Photoluminescence", "FTIR", "Lifetime"}:
            continue
        path = Path(record.source)
        points = filter_points_for_type(read_spectrum(path), record.experiment_type)
        if not points:
            continue
        xs = [p[0] for p in points]
        ys = [p[1] for p in points]
        if max(ys) <= 0:
            continue
        peak_index = max(range(len(points)), key=lambda idx: ys[idx])
        result = SpectrumResult(
            source=str(path),
            experiment_date=record.experiment_date,
            experiment_type=record.experiment_type,
            n_points=len(points),
            x_min=min(xs),
            x_max=max(xs),
            y_min=min(ys),
            y_max=max(ys),
            peak_x=points[peak_index][0],
            peak_y=points[peak_index][1],
        )
        if record.experiment_type == "UV-Vis":
            result.plot_path = plot_spectrum(points, result, output / "plots" / "uv_vis")
        elif record.experiment_type == "Photoluminescence":
            result.plot_path = plot_spectrum(points, result, output / "plots" / "pl")
        results.append(result)
    return results


def write_csv(path: Path, rows: Iterable[dict]) -> None:
    rows = list(rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def summarize_records(records: list[FileRecord]) -> dict:
    by_type: dict[str, int] = {}
    by_date: dict[str, int] = {}
    by_extension: dict[str, int] = {}
    for record in records:
        by_type[record.experiment_type] = by_type.get(record.experiment_type, 0) + 1
        by_date[record.experiment_date] = by_date.get(record.experiment_date, 0) + 1
        by_extension[record.extension] = by_extension.get(record.extension, 0) + 1
    return {
        "total_files": len(records),
        "by_type": dict(sorted(by_type.items())),
        "by_date": dict(sorted(by_date.items())),
        "by_extension": dict(sorted(by_extension.items())),
    }


def trend_lines(results: list[SpectrumResult]) -> list[str]:
    lines: list[str] = []
    for experiment_type in sorted({r.experiment_type for r in results}):
        subset = sorted(
            [r for r in results if r.experiment_type == experiment_type],
            key=lambda r: (r.experiment_date, Path(r.source).name),
        )
        if not subset:
            continue
        peaks = [r.peak_x for r in subset]
        intensities = [r.peak_y for r in subset]
        lines.append(
            f"{experiment_type}: {len(subset)} parsed spectra; peak positions span "
            f"{min(peaks):.2f}-{max(peaks):.2f}; peak signals span "
            f"{min(intensities):.3g}-{max(intensities):.3g}."
        )
        if len(subset) >= 2:
            first, last = subset[0], subset[-1]
            direction = "increased" if last.peak_y > first.peak_y else "decreased"
            lines.append(
                f"{experiment_type}: from {first.experiment_date} to {last.experiment_date}, "
                f"peak signal {direction} from {first.peak_y:.3g} to {last.peak_y:.3g} "
                f"based on parsed file order."
            )
    return lines


def generate_reports(records: list[FileRecord], results: list[SpectrumResult], output: Path) -> None:
    reports = output / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    records_by_date: dict[str, list[FileRecord]] = {}
    results_by_date: dict[str, list[SpectrumResult]] = {}
    for record in records:
        records_by_date.setdefault(record.experiment_date, []).append(record)
    for result in results:
        results_by_date.setdefault(result.experiment_date, []).append(result)

    daily_lines = ["Daily Lab Activity Report", "=" * 25, ""]
    for day in sorted(records_by_date):
        day_records = records_by_date[day]
        daily_lines.append(day)
        daily_lines.append("-" * len(day))
        daily_lines.append(f"Files captured/modified: {len(day_records)}")
        type_counts: dict[str, int] = {}
        for record in day_records:
            type_counts[record.experiment_type] = type_counts.get(record.experiment_type, 0) + 1
        daily_lines.append(
            "Experiment types: "
            + ", ".join(f"{key} ({value})" for key, value in sorted(type_counts.items()))
        )
        day_results = results_by_date.get(day, [])
        if day_results:
            daily_lines.append("Parsed spectra:")
            for result in sorted(day_results, key=lambda r: (r.experiment_type, Path(r.source).name)):
                daily_lines.append(
                    f"- {result.experiment_type}: {Path(result.source).name}; "
                    f"peak at {result.peak_x:.2f} with signal {result.peak_y:.3g}; "
                    f"{result.n_points} points"
                )
        else:
            daily_lines.append("Parsed spectra: none from CSV/TXT numeric-pair data")
        daily_lines.append("")

    today = dt.date.today()
    week_start = today - dt.timedelta(days=today.weekday() + 1 if today.weekday() < 6 else 6)
    week_end = week_start + dt.timedelta(days=6)
    week_records = [
        record
        for record in records
        if week_start <= dt.date.fromisoformat(record.experiment_date) <= week_end
    ]
    week_results = [
        result
        for result in results
        if week_start <= dt.date.fromisoformat(result.experiment_date) <= week_end
    ]
    trend_summary = trend_lines(week_results)
    weekly_lines = [
        "Weekly Experiment Summary",
        "=" * 25,
        f"Generated: {dt.datetime.now().isoformat(timespec='seconds')}",
        f"Reporting week: {week_start.isoformat()} to {week_end.isoformat()}",
        "",
        "Overview",
        "- Relevant files this week: " + str(len(week_records)),
        "- Parsed spectra this week: " + str(len(week_results)),
        "- Total archive files scanned: " + str(len(records)),
        "",
        "Trends",
    ]
    weekly_lines.extend(f"- {line}" for line in trend_summary or ["No spectral trends could be calculated."])
    weekly_lines.extend(["", "Activity by day"])
    for day in sorted(records_by_date):
        day_value = dt.date.fromisoformat(day)
        if not (week_start <= day_value <= week_end):
            continue
        types = sorted({record.experiment_type for record in records_by_date[day]})
        weekly_lines.append(f"- {day}: {len(records_by_date[day])} files; {', '.join(types)}")

    (reports / "daily_lab_report.txt").write_text("\n".join(daily_lines), encoding="utf-8")
    (reports / "weekly_experiment_summary.txt").write_text("\n".join(weekly_lines), encoding="utf-8")
    (reports / "trends_summary.txt").write_text("\n".join(trend_summary), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE, help="Folder containing spectroscopy data")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="Folder for organized files, plots, and reports")
    parser.add_argument("--organize", action="store_true", help="Copy files into output/organized_files/date/type")
    parser.add_argument("--move", action="store_true", help="Move files instead of copying when organizing")
    args = parser.parse_args()

    source = args.source.resolve()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)

    records = scan_files(source)
    if args.organize or args.move:
        organize_files(records, source, output, move=args.move)
    results = analyze_spectra(records, output)
    generate_reports(records, results, output)

    write_csv(output / "manifest.csv", [asdict(record) for record in records])
    write_csv(output / "spectral_analysis.csv", [asdict(result) for result in results])
    summary = summarize_records(records)
    summary["parsed_spectra"] = len(results)
    summary["uv_plots"] = len([r for r in results if r.experiment_type == "UV-Vis" and r.plot_path])
    summary["pl_plots"] = len([r for r in results if r.experiment_type == "Photoluminescence" and r.plot_path])
    (output / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print(json.dumps(summary, indent=2))
    print(f"Output written to: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
