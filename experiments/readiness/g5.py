"""G5 real benchmark and batch throughput (WP2).

    python -m experiments.readiness.g5 fetch        # download + convert to SigMF pairs, write g5_data_lock.json
    python -m experiments.readiness.g5 run          # one timed batch-CLI run over the fixed folder, then score

Data lands in artifacts/readiness/g5/ (git-ignored). rtl_433 captures are wrapped unchanged as
`cu8` SigMF pairs (rate and centre from their rtl_433 names); IQEngine recordings are truncated
to their first 16,000,000 bytes, as the G3 files were. The lock file pins each data file's sha256.

The throughput folder is fixed: the six G3 recordings plus every G5 *test* recording. One run of
`python -m backend.cli analyze <folder>` (the analyst's batch path, default options) is timed
wall-clock, sequentially with nothing else running in this program; T1 = that time / the total
recorded duration of the folder. The same run's JSON outputs are scored for RC1-RC3 (test files only;
calibration files are never scored here).
"""
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from .config import G5_MANIFEST, THRESHOLDS as TH
from .metrics import label_matches, rate_matches

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = Path(__file__).with_name(G5_MANIFEST)
LOCK = Path(__file__).with_name("g5_data_lock.json")
DATA = ROOT / "artifacts" / "readiness" / "g5"
REAL = ROOT / "artifacts" / "readiness" / "real"
FOLDER = ROOT / "artifacts" / "readiness" / "batch_folder"
OUT = ROOT / "artifacts" / "readiness" / "batch_out"
RESULTS = ROOT / "artifacts" / "readiness" / "g5_results.json"
BYTES_PER_SAMPLE = {"cf32_le": 8, "ci16_le": 4, "ci8": 2, "cu8": 2}


def manifest():
    return json.loads(MANIFEST.read_text())["recordings"]


def _open(url, tries=4):
    for i in range(tries):
        try:
            return urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "PinPoint-readiness-g5"}),
                                          timeout=120)
        except OSError:
            if i == tries - 1:
                raise
            time.sleep(2 ** i)


def _read(url, limit=None):
    with _open(url) as r:
        if limit is None:
            return r.read()
        buf = bytearray()
        while len(buf) < limit:
            chunk = r.read(min(1 << 20, limit - len(buf)))
            if not chunk:
                break
            buf += chunk
        return bytes(buf)


def _sanitize(meta, n_samples):
    """SigMF meta that matches (possibly truncated) data: no full-file hash, the 'core::datetime'
    typo fixed, numbers stored as strings made numbers, only annotations inside the downloaded samples."""
    g = meta["global"]
    g.pop("core:sha512", None)
    for key in [k for k in g if k.startswith("traceability:")]:
        g.pop(key)
    for key in ("core:sample_rate",):          # some IQEngine metas store numbers as strings (invalid SigMF)
        if isinstance(g.get(key), str):
            g[key] = float(g[key])
    for c in meta.get("captures", []):
        if isinstance(c.get("core:frequency"), str):
            c["core:frequency"] = float(c["core:frequency"])
        if "core::datetime" in c:
            c["core:datetime"] = c.pop("core::datetime")
    meta["annotations"] = [a for a in meta.get("annotations", [])
                           if a["core:sample_start"] + a.get("core:sample_count", 0) <= n_samples]
    return meta


def fetch(entries=None):
    DATA.mkdir(parents=True, exist_ok=True)
    lock = json.loads(LOCK.read_text()) if LOCK.exists() else {}
    for e in entries or manifest():
        data, meta_path = DATA / f"{e['id']}.sigmf-data", DATA / f"{e['id']}.sigmf-meta"
        if not data.exists():
            if e["source"] == "rtl_433_tests":
                raw = _read(e["url"])
                meta = {"global": {"core:datatype": "cu8", "core:sample_rate": e["sample_rate"], "core:version": "1.2.0",
                                   "core:description": f"rtl_433_tests {e['path']} (sample rate and centre from the "
                                   "rtl_433 file name); ground truth in experiments/readiness/g5_manifest.json"},
                        "captures": [{"core:sample_start": 0, "core:frequency": e["center_frequency"]}],
                        "annotations": []}
            else:
                meta = json.loads(_read(e["url"] + ".sigmf-meta"))
                bps = BYTES_PER_SAMPLE[meta["global"]["core:datatype"]]
                raw = _read(e["url"] + ".sigmf-data", e["truncate_bytes"])
                raw = raw[:len(raw) - len(raw) % bps]
                (DATA / f"{e['id']}.sigmf-meta.orig").write_text(json.dumps(meta, indent=1))
                meta = _sanitize(meta, len(raw) // bps)
            data.write_bytes(raw)
            meta_path.write_text(json.dumps(meta, indent=1))
        digest = hashlib.sha256(data.read_bytes()).hexdigest()
        if e["id"] in lock and lock[e["id"]] != digest:
            raise SystemExit(f"{e['id']}: data changed since it was locked")
        lock[e["id"]] = digest
        print(e["id"], digest[:12], flush=True)
    LOCK.write_text(json.dumps(dict(sorted(lock.items())), indent=1) + "\n")


def duration_s(meta_path: Path, data_path: Path) -> float:
    g = json.loads(meta_path.read_text())["global"]
    return data_path.stat().st_size / BYTES_PER_SAMPLE[g["core:datatype"]] / float(g["core:sample_rate"])


def folder_files():
    """[(stem, data, meta, entry or None)] of the fixed throughput folder: G3 + G5 test."""
    out = []
    g3 = json.loads((Path(__file__).with_name("real_manifest.json")).read_text())["recordings"]
    for r in g3:
        out.append((r["file"], REAL / f"{r['file']}.sigmf-data", REAL / f"{r['file']}.sigmf-meta", None))
    for e in manifest():
        if e["split"] == "test":
            out.append((e["id"], DATA / f"{e['id']}.sigmf-data", DATA / f"{e['id']}.sigmf-meta", e))
    return out


def score_file(entry, detections):
    """Per-file outcome for RC1-RC3 (pre-registered rules):
    correct: some detection publishes an allowed label (order-less family labels count, as in metrics);
    wrong: some detection publishes a label that is not allowed (anywhere in the file; OFDM
    negatives allow none); rate_wrong: on a rate-scored file, a detection with an allowed label
    publishes a rate more than 5% from the expected one."""
    allowed = entry["allowed_labels"]
    ok = lambda lab: any(label_matches(lab, a) for a in allowed)
    labels = [d.get("modulation_label") for d in detections if d.get("modulation_label")]
    rate = entry.get("expected_rate_hz")
    bad_rates = [d.get("symbol_rate_hz") for d in detections if rate and d.get("modulation_label")
                 and ok(d["modulation_label"]) and d.get("symbol_rate_hz") is not None
                 and not rate_matches(d["symbol_rate_hz"], rate)]
    good_rates = [d.get("symbol_rate_hz") for d in detections if rate and d.get("modulation_label")
                  and ok(d["modulation_label"]) and rate_matches(d.get("symbol_rate_hz"), rate)]
    return dict(correct=any(ok(l) for l in labels), wrong=any(not ok(l) for l in labels),
                published=sorted(set(labels)), rate_scored=bool(rate), rate_wrong=bool(bad_rates),
                rate_correct=bool(good_rates), n_detections=len(detections))


def run(estimator_args=()):
    """One timed batch-CLI run over the fixed folder; returns and saves the per-file results."""
    from . import real
    for r in json.loads((Path(__file__).with_name("real_manifest.json")).read_text())["recordings"]:
        real.trimmed_meta(r["file"])
    shutil.rmtree(FOLDER, ignore_errors=True)
    shutil.rmtree(OUT, ignore_errors=True)
    FOLDER.mkdir(parents=True)
    files = folder_files()
    for stem, data, meta, _ in files:
        if not data.exists():
            raise SystemExit(f"missing {data}: run `python -m experiments.readiness.g5 fetch` first")
        os.symlink(data, FOLDER / f"{stem}.sigmf-data")
        os.symlink(meta, FOLDER / f"{stem}.sigmf-meta")
    total = sum(duration_s(m, d) for _, d, m, _ in files)
    t0 = time.perf_counter()
    proc = subprocess.run([sys.executable, "-m", "backend.cli", "analyze", str(FOLDER), "--out", str(OUT),
                           *estimator_args], cwd=ROOT, capture_output=True, text=True)
    wall = time.perf_counter() - t0
    per_file = []
    for stem, data, meta, e in files:
        out = OUT / f"{stem}.json"
        dets = json.loads(out.read_text())["detections"] if out.exists() else None
        rec = dict(file=stem, duration_s=duration_s(meta, data), crashed=dets is None, g5=e is not None)
        if e is not None and dets is not None:
            rec.update(score_file(e, dets), stratum=e["stratum"], protocol=e["protocol"],
                       allowed=e["allowed_labels"], expected_rate_hz=e.get("expected_rate_hz"),
                       detections=[{k: d.get(k) for k in ("id", "freq_lower_hz", "freq_upper_hz", "is_pulsed",
                                                         "bandwidth_99pct_hz", "snr_db", "modulation_label",
                                                         "estimate_tier", "symbol_rate_hz", "verify_status")}
                                   for d in dets])
        per_file.append(rec)
    blob = dict(wall_s=wall, duration_s=total, rtf=wall / total, cli_exit=proc.returncode,
                cli_stderr=proc.stderr[-2000:], files=per_file)
    RESULTS.write_text(json.dumps(blob, indent=1, default=float) + "\n")
    return blob


def stats(blob):
    g5 = [f for f in blob["files"] if f["g5"]]
    have = [f for f in g5 if f.get("allowed")]
    scored = [f for f in g5 if f.get("rate_scored")]
    frac = lambda a, b: None if not b else a / b
    return dict(n_test=len(g5), n_with_label=len(have), n_rate_scored=len(scored),
                correct=frac(sum(bool(f.get("correct")) for f in have), len(have)),
                wrong=frac(sum(bool(f.get("wrong")) for f in g5), len(g5)),
                rate_wrong=frac(sum(bool(f.get("rate_wrong")) for f in scored), len(scored)),
                rate_correct=frac(sum(bool(f.get("rate_correct")) for f in scored), len(scored)),
                crashed=sum(bool(f["crashed"]) for f in blob["files"]),
                rtf=blob["rtf"], wall_s=blob["wall_s"], duration_s=blob["duration_s"])


def criteria(blob=None):
    """RC1-RC3 and T1 as scoreboard criteria dicts (on the G5 column)."""
    if blob is None:
        blob = json.loads(RESULTS.read_text()) if RESULTS.exists() else None
    if blob is None:
        none = dict(value=None, passed=None, n=None)
        return [dict(id=i, desc=d, passed=False, gens={"G5": none}) for i, d in
                (("RC1", ""), ("RC2", ""), ("RC3", ""), ("T1", ""))], None
    s = stats(blob)
    le = lambda v, lim: None if v is None else v <= lim
    ge = lambda v, lim: None if v is None else v >= lim

    def crit(cid, desc, v, ok, n):
        return dict(id=cid, desc=desc, passed=bool(ok), gens={"G5": dict(value=v, passed=ok, n=n)})
    return [
        crit("RC1", f"correct label published on >= {TH.real_correct_min:.0%} of G5 test files that have one",
             s["correct"], ge(s["correct"], TH.real_correct_min), s["n_with_label"]),
        crit("RC2", f"wrong label published on <= {TH.real_wrong_max:.0%} of G5 test files",
             s["wrong"], le(s["wrong"], TH.real_wrong_max), s["n_test"]),
        crit("RC3", f"wrong rate published on <= {TH.real_rate_wrong_max:.0%} of rate-scored G5 test files",
             s["rate_wrong"], le(s["rate_wrong"], TH.real_rate_wrong_max), s["n_rate_scored"]),
        crit("T1", f"batch CLI time / recorded duration <= {TH.throughput_rtf_max:g} (G3 + G5 test folder)",
             round(s["rtf"], 3), le(s["rtf"], TH.throughput_rtf_max), len(blob["files"])),
    ], s


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=("fetch", "run"))
    args = ap.parse_args(argv)
    if args.command == "fetch":
        fetch()
    else:
        blob = run()
        print(json.dumps(stats(blob), indent=1, default=float))


if __name__ == "__main__":
    main()
