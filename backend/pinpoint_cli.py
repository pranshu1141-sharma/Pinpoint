"""Terminal packaging around the offline batch CLI (backend.cli): adds --json, --jobs,
watch, summary and validate around the same find_inputs/analyze_file/summary_rows
functions backend.cli already uses. No analysis logic lives here."""
import argparse
import csv
import json
import sys
from pathlib import Path

from backend._version import __version__
from backend.cli import ESTIMATORS, SUMMARY_FIELDS, analyze_file, find_inputs, summary_rows


def _add_shared_analyze_args(parser):
    parser.add_argument("--estimator", choices=ESTIMATORS, default="verify")
    parser.add_argument("--sample-rate", type=float, default=None, help="required for raw .iq")
    parser.add_argument("--datatype", default=None, help="required for raw .iq (e.g. cf32_le, ci16_le)")
    parser.add_argument("--wav-mode", default="auto", choices=("auto", "iq", "audio_left", "audio_right"))
    parser.add_argument("--margin-db", type=float, default=8.0)


def _analyze_one(path, args):
    """Runs in a worker process when --jobs > 1: (file name, blob-or-None, error-or-None)."""
    try:
        return path.name, analyze_file(path, args), None
    except Exception as exc:                     # malformed/ambiguous input: reported, never raised
        return path.name, None, f"{type(exc).__name__}: {exc}"


def _run_batch(inputs, args, jobs):
    """Analyzes every input, returning one (name, blob, error) triple per input, in input order.
    jobs=1 is a plain sequential loop; jobs>1 uses a process pool. ProcessPoolExecutor.map
    preserves call order in its results regardless of completion order, so output is the
    same either way."""
    if jobs == 1:
        return [_analyze_one(path, args) for path in inputs]
    from concurrent.futures import ProcessPoolExecutor
    with ProcessPoolExecutor(max_workers=jobs) as pool:
        return list(pool.map(_analyze_one, inputs, [args] * len(inputs)))


def _write_outputs(name, blob, out_dir):
    stem = name[:-len(".sigmf-data")] if name.lower().endswith(".sigmf-data") else Path(name).stem
    sigmf = blob["sigmf"]
    (out_dir / f"{stem}.json").write_text(
        json.dumps({k: v for k, v in blob.items() if k != "sigmf"}, indent=1, sort_keys=True) + "\n")
    (out_dir / f"{stem}.sigmf-meta").write_text(json.dumps(sigmf, indent=1, sort_keys=True) + "\n")


def cmd_summary(args):
    csv_path = args.out_dir / "summary.csv"
    if not csv_path.exists():
        print(f"{csv_path} does not exist", file=sys.stderr)
        return 1
    rows = list(csv.DictReader(csv_path.open()))
    rows.sort(key=lambda r: (r["needs_review"] != "true", r["file"], r["detection_id"]))
    cols = ["needs_review", "file", "detection_id", "label", "tier", "snr_db", "status", "error"]
    widths = {c: max([len(c)] + [len(r[c]) for r in rows]) for c in cols}
    print("  ".join(c.ljust(widths[c]) for c in cols))
    print("  ".join("-" * widths[c] for c in cols))
    for r in rows:
        print("  ".join(r[c].ljust(widths[c]) for c in cols))
    files = {r["file"] for r in rows}
    labelled = sum(1 for r in rows if r["label"])
    errors = sum(1 for r in rows if r["error"])
    abstained = sum(1 for r in rows if not r["label"] and not r["error"])
    print(f"files={len(files)} detections={len(rows)} labelled={labelled} abstained={abstained} errors={errors}")
    return 0


def cmd_analyze(args):
    try:
        inputs = find_inputs(args.target)
    except FileNotFoundError as exc:
        print(exc, file=sys.stderr)
        return 1
    if args.out is None and not args.json:
        print("--out is required unless --json is given", file=sys.stderr)
        return 1
    if args.out is not None:
        args.out.mkdir(parents=True, exist_ok=True)

    results = _run_batch(inputs, args, args.jobs)

    rows, failed, json_lines = [], 0, []
    for name, blob, err in results:
        if err is not None:
            failed += 1
            rows.append({k: "" for k in SUMMARY_FIELDS} | {"needs_review": "true", "file": name, "error": err})
            print(f"{name}: {err}", file=sys.stderr)
            continue
        if args.out is not None:
            _write_outputs(name, blob, args.out)
        rows += summary_rows(blob)
        if args.json:
            for d in sorted(blob["detections"], key=lambda d: str(d["id"])):
                json_lines.append({"file": name, **d})

    if args.json:
        for obj in json_lines:
            print(json.dumps(obj, sort_keys=True))

    if args.out is not None:
        rows.sort(key=lambda r: (r["needs_review"] != "true", r["file"], str(r["detection_id"])))
        with (args.out / "summary.csv").open("w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=SUMMARY_FIELDS)
            w.writeheader()
            w.writerows(rows)

    dest = f" -> {args.out}" if args.out is not None else ""
    print(f"analysed {len(inputs) - failed}/{len(inputs)} captures{dest}",
          file=sys.stderr if args.json else sys.stdout)
    return 2 if failed else 0


def build_parser():
    ap = argparse.ArgumentParser(prog="pinpoint")
    ap.add_argument("--version", action="version", version=f"pinpoint {__version__}")
    sub = ap.add_subparsers(dest="command", required=True)

    an = sub.add_parser("analyze", help="analyse a capture file or every capture in a folder")
    an.add_argument("target", type=Path)
    an.add_argument("--out", type=Path, default=None)
    an.add_argument("--json", action="store_true", help="write per-detection JSON Lines to stdout")
    an.add_argument("--jobs", type=int, default=1)
    _add_shared_analyze_args(an)
    an.set_defaults(func=cmd_analyze)

    su = sub.add_parser("summary", help="print a terminal table from an --out folder's summary.csv")
    su.add_argument("out_dir", type=Path)
    su.set_defaults(func=cmd_summary)
    return ap


def run(argv=None):
    args = build_parser().parse_args(argv)
    if hasattr(args, 'jobs') and args.jobs < 1:
        print("--jobs must be >= 1", file=sys.stderr)
        return 1
    return args.func(args)


if __name__ == "__main__":
    sys.exit(run())
