"""G3: real recordings (WP7). Each manifest entry records, by hand, what is known about a file;
`check(entry, result)` compares the pipeline output with it. Results land in
artifacts/readiness/real_results.json; the criterion reads that file."""
import json
from pathlib import Path

from .config import THRESHOLDS as TH

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = Path(__file__).with_name("real_manifest.json")
RESULTS = ROOT / "artifacts" / "readiness" / "real_results.json"


def criterion():
    results = json.loads(RESULTS.read_text()) if RESULTS.exists() else []
    ran = [r for r in results if r.get("crashed") is False]
    sane = [r for r in ran if r.get("sanity_ok")]
    n = len(results)
    ok = n >= TH.real_min_recordings and len(sane) == n
    return dict(id="RD1", desc=f">= {TH.real_min_recordings} public recordings end to end, no crash, sanity check on each",
                passed=bool(ok), gens={"G3": dict(value=f"{len(sane)}/{n} sane" if n else None,
                                                  passed=bool(ok) if n else None, n=n)},
                files=[dict(file=r["file"], crashed=r.get("crashed"), sanity_ok=r.get("sanity_ok"),
                            note=r.get("note")) for r in results])


DATA = ROOT / "artifacts" / "readiness" / "real"


def sanity(entry: dict, detections: list[dict]) -> tuple[bool, list[str]]:
    """Apply one manifest entry's pre-registered checks to the pipeline's detections."""
    notes = []
    if len(detections) < entry.get("min_detections", 1):
        notes.append(f"{len(detections)} detections < {entry.get('min_detections', 1)}")
    allowed = set(entry.get("allowed_labels", []))
    rate = entry.get("expected_rate_hz")
    for d in detections:
        lab = d.get("modulation_label")
        if lab is not None and lab not in allowed:
            notes.append(f"detection {d.get('id')}: published label {lab} not in {sorted(allowed)}")
        r = d.get("symbol_rate_hz")
        if lab in allowed and rate and r is not None and abs(r - rate) / rate > 0.05:
            notes.append(f"detection {d.get('id')}: published rate {r:.0f} Hz vs expected {rate} Hz")
    band = entry.get("overlap_band_hz")
    near = [d for d in detections if band is None or (d["freq_upper_hz"] > band[0] and d["freq_lower_hz"] < band[1])]
    if band is not None and not near:
        notes.append(f"no detection overlaps {band} Hz")
    if entry.get("require_pulsed") and not any(d.get("is_pulsed") for d in near):
        notes.append("no pulsed detection where bursts are expected")
    rng = entry.get("bandwidth_99pct_range_hz")
    if rng and not any(d.get("bandwidth_99pct_hz") is not None and rng[0] <= d["bandwidth_99pct_hz"] <= rng[1]
                       for d in near):
        notes.append(f"no detection with 99% bandwidth in {rng} Hz")
    wide = entry.get("min_wide_detections")
    if wide:
        n = sum(1 for d in detections if (d.get("bandwidth_99pct_hz") or 0) >= wide["bandwidth_99pct_hz"])
        if n < wide["count"]:
            notes.append(f"{n} detections with 99% bandwidth >= {wide['bandwidth_99pct_hz']} Hz < {wide['count']}")
    return not notes, notes


def trimmed_meta(name: str) -> Path:
    """SigMF meta matching the (possibly truncated) data file: drops the full-file hash, fixes the
    'core::datetime' key typo, keeps only annotations inside the downloaded samples."""
    meta = json.loads((DATA / f"{name}.sigmf-meta.orig").read_text())
    g = meta["global"]
    g.pop("core:sha512", None)
    bps = {"cf32_le": 8, "ci16_le": 4, "ci8": 2}[g["core:datatype"]]
    n = (DATA / f"{name}.sigmf-data").stat().st_size // bps
    for c in meta.get("captures", []):
        if "core::datetime" in c:
            c["core:datetime"] = c.pop("core::datetime")
    meta["annotations"] = [a for a in meta.get("annotations", [])
                           if a["core:sample_start"] + a.get("core:sample_count", 0) <= n]
    out = DATA / f"{name}.sigmf-meta"
    out.write_text(json.dumps(meta, indent=1))
    return out


def run():
    """Analyse every manifest recording through the batch-CLI path and record the checks."""
    import argparse
    from backend.cli import analyze_file
    manifest = json.loads(MANIFEST.read_text())
    args = argparse.Namespace(sample_rate=None, datatype=None, wav_mode="auto", margin_db=8.0, estimator="verify")
    results = []
    for entry in manifest["recordings"]:
        name = entry["file"]
        rec = dict(file=name, known=entry["known"])
        try:
            trimmed_meta(name)
            blob = analyze_file(DATA / f"{name}.sigmf-data", args)
            dets = blob["detections"]
            ok, notes = sanity(entry, dets)
            rec.update(crashed=False, sanity_ok=ok, note="; ".join(notes) or "all checks passed",
                       detections=[{k: d.get(k) for k in ("id", "freq_lower_hz", "freq_upper_hz", "is_pulsed",
                                                         "bandwidth_3db_hz", "bandwidth_99pct_hz", "snr_db",
                                                         "modulation_label", "estimate_tier", "symbol_rate_hz",
                                                         "verify_status")} for d in dets])
        except Exception as exc:
            rec.update(crashed=True, sanity_ok=False, note=f"{type(exc).__name__}: {exc}")
        results.append(rec)
        print(name, "crashed" if rec["crashed"] else ("ok" if rec["sanity_ok"] else "FAILED"), "-", rec["note"][:200])
    RESULTS.parent.mkdir(parents=True, exist_ok=True)
    RESULTS.write_text(json.dumps(results, indent=1, default=float) + "\n")
    return results


if __name__ == "__main__":
    run()
