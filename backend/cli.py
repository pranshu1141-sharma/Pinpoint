"""Offline batch analysis: python -m backend.cli analyze <file-or-folder> --out <dir>.

For every capture (a .sigmf-data with its .sigmf-meta, a .wav, or a raw .iq with
--sample-rate and --datatype) it writes <stem>.json (detections with parameters,
label, rate, tier and review flags) and <stem>.sigmf-meta (annotations), plus one
summary.csv for the batch, with rows needing review first. It uses the same
pipeline as the API (captures above 1 MiB take the disk-backed large-capture
path). Offline and deterministic: wall-clock timings are left out of the files.
Exit status: 0 when every input was analysed, 2 when any input was malformed or
could not be interpreted (it is still listed in summary.csv), 1 on usage errors.
"""
import argparse
import csv
import json
import sys
from pathlib import Path

import numpy as np

from backend.pipeline.classify import ESTIMATORS, analyze_candidate
from backend.pipeline.detect import analyze_capture
from backend.pipeline.ingest import load_capture
from backend.pipeline.large_capture import analyze_disk_capture, open_disk_capture
from backend.pipeline.sigmf_io import export_metadata

LARGE_FILE_BYTES = 1024 * 1024
SUFFIXES = (".sigmf-data", ".wav", ".iq")
TIMING_KEYS = ("elapsed_ms", "verify_elapsed_ms")
SUMMARY_FIELDS = ("needs_review", "file", "detection_id", "label", "tier", "symbol_rate_hz",
                  "center_frequency_hz", "bandwidth_3db_hz", "snr_db", "freq_lower_hz", "freq_upper_hz",
                  "start_sample", "end_sample", "status", "error")


def find_inputs(target: Path) -> list[Path]:
    if target.is_file():
        return [target]
    if not target.is_dir():
        raise FileNotFoundError(f"{target} does not exist")
    return sorted(p for p in target.iterdir() if p.is_file() and p.name.lower().endswith(SUFFIXES))


def analyze_file(path: Path, args) -> dict:
    meta_path = path.with_name(path.name[:-len(".sigmf-data")] + ".sigmf-meta") \
        if path.name.lower().endswith(".sigmf-data") else None
    if meta_path is not None and not meta_path.exists():
        raise ValueError(f"missing {meta_path.name} next to {path.name}")
    meta = meta_path.read_bytes() if meta_path else None
    if path.stat().st_size > LARGE_FILE_BYTES:
        capture = open_disk_capture(path, path.name, args.sample_rate, args.datatype, meta, args.wav_mode)
        result = analyze_disk_capture(capture, args.margin_db, estimator=args.estimator)
    else:
        capture = load_capture(path.name, path.read_bytes(), args.sample_rate, args.datatype, meta, args.wav_mode)
        result = analyze_capture(capture, args.margin_db)
        result.response["detections"] = [analyze_candidate(capture, d, noise_floor=result.noise_floor,
                                                           estimator=args.estimator)
                                         for d in result.response["detections"]]
    response = result.response
    detections = [_clean(d) for d in response["detections"]]
    return {"file": path.name, "estimator": args.estimator, "metadata": _clean(response["metadata"]),
            "noise_floor_db": response["noise_floor_db"], "threshold_db": response["threshold_db"],
            "detections": detections, "sigmf": export_metadata(response["metadata"], response["detections"])}


def _clean(obj):
    """JSON-safe, timing-free copy (NumPy scalars to Python, NaN/inf to null)."""
    if isinstance(obj, dict):
        return {k: _clean(v) for k, v in obj.items() if k not in TIMING_KEYS}
    if isinstance(obj, (list, tuple)):
        return [_clean(v) for v in obj]
    if isinstance(obj, (np.floating, float)):
        return float(obj) if np.isfinite(obj) else None
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, np.bool_):
        return bool(obj)
    return obj


def summary_rows(blob: dict) -> list[dict]:
    rows = []
    for d in blob["detections"]:
        review = bool(d.get("needs_review")) or bool(d.get("label_needs_review", True))
        label = d.get("modulation_label")
        rows.append({"needs_review": "true" if review else "false", "file": blob["file"], "detection_id": d["id"],
                     "label": label or "", "tier": d.get("estimate_tier") or "",
                     "symbol_rate_hz": _fmt(d.get("symbol_rate_hz")), "center_frequency_hz": _fmt(
                         d.get("center_frequency_refined_hz") or d.get("center_frequency_hz")),
                     "bandwidth_3db_hz": _fmt(d.get("bandwidth_3db_hz")), "snr_db": _fmt(d.get("snr_db")),
                     "freq_lower_hz": _fmt(d["freq_lower_hz"]), "freq_upper_hz": _fmt(d["freq_upper_hz"]),
                     "start_sample": d["start_sample"], "end_sample": d["end_sample"],
                     "status": d.get("verify_status") or d.get("fine_modulation_status") or "", "error": ""})
    return rows


def _fmt(v):
    return "" if v is None else f"{v:.6g}"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m backend.cli")
    sub = ap.add_subparsers(dest="command", required=True)
    an = sub.add_parser("analyze", help="analyse a capture file or every capture in a folder")
    an.add_argument("target", type=Path)
    an.add_argument("--out", type=Path, required=True)
    an.add_argument("--estimator", choices=ESTIMATORS, default="verify")
    an.add_argument("--sample-rate", type=float, default=None, help="required for raw .iq")
    an.add_argument("--datatype", default=None, help="required for raw .iq (e.g. cf32_le, ci16_le)")
    an.add_argument("--wav-mode", default="auto", choices=("auto", "iq", "audio_left", "audio_right"))
    an.add_argument("--margin-db", type=float, default=8.0)
    args = ap.parse_args(argv)
    try:
        inputs = find_inputs(args.target)
    except FileNotFoundError as exc:
        print(exc, file=sys.stderr)
        return 1
    args.out.mkdir(parents=True, exist_ok=True)
    rows, failed = [], 0
    for path in inputs:
        try:
            blob = analyze_file(path, args)
        except Exception as exc:          # malformed or ambiguous input: reported, never silently skipped
            failed += 1
            rows.append({k: "" for k in SUMMARY_FIELDS} | {"needs_review": "true", "file": path.name,
                                                          "error": f"{type(exc).__name__}: {exc}"})
            print(f"{path.name}: {exc}", file=sys.stderr)
            continue
        stem = path.name[:-len(".sigmf-data")] if path.name.lower().endswith(".sigmf-data") else path.stem
        sigmf = blob.pop("sigmf")
        (args.out / f"{stem}.json").write_text(json.dumps(blob, indent=1, sort_keys=True) + "\n")
        (args.out / f"{stem}.sigmf-meta").write_text(json.dumps(sigmf, indent=1, sort_keys=True) + "\n")
        rows += summary_rows(blob)
    rows.sort(key=lambda r: (r["needs_review"] != "true", r["file"], str(r["detection_id"])))
    with (args.out / "summary.csv").open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=SUMMARY_FIELDS)
        w.writeheader()
        w.writerows(rows)
    print(f"analysed {len(inputs) - failed}/{len(inputs)} captures -> {args.out}")
    return 2 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
