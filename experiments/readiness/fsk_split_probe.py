"""Does Detect's band cover an FSK2 signal's tones? (diagnostic only, never scored)

WP3 first version picked the highest-`snr_db` candidate as "the" candidate for the file. That selects weak narrow
spectral lines (narrow bands read a high SNR), not the signal, and overstated the bounds problem. Corrected in WP3b: the
candidate for a file is the one that overlaps the strongest burst in time and contains the burst's centre frequency,
highest `threshold_excess_db` first; a file where none does counts as a miss.

    python -m experiments.readiness.fsk_split_probe   -> artifacts/readiness/fsk_split_probe.json

For every G5 *test* file whose truth is FSK2 (and that fits in memory), measure the tone split of its strongest
burst (85th minus 15th percentile of the instantaneous frequency inside the burst, a rough measure that is only
meaningful at the 15-30 dB SNRs these bursts have) and compare it with the bandwidth of the file's highest-SNR
Detect candidate. ratio = candidate bandwidth / tone split: well under 1 means the candidate is one tone's
lobe or line; far above 1 means it is much wider than the signal.
"""
import argparse
import json
from pathlib import Path

import numpy as np

from backend.cli import analyze_file
from backend.pipeline.ingest import load_capture
from . import g5
from .config import THRESHOLDS as TH

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "artifacts" / "readiness" / "fsk_split_probe.json"


def files(split):
    """[(stem, data, meta, entry)] of the G5 FSK2 files in `split` ("test" is the scored throughput folder)."""
    if split == "test":
        return [f for f in g5.folder_files() if f[3] and f[3]["allowed_labels"] == ["FSK2"]]
    return [(e["id"], g5.DATA / f"{e['id']}.sigmf-data", g5.DATA / f"{e['id']}.sigmf-meta", e) for e in g5.manifest()
            if e["split"] == split and e["allowed_labels"] == ["FSK2"]]


def run(split="test", out_path=OUT, quiet=False):
    args = argparse.Namespace(sample_rate=None, datatype=None, wav_mode="auto", margin_db=8.0, estimator="verify")
    out = []
    for stem, path, meta, entry in files(split):
        blob = analyze_file(path, args)
        try:
            cap = load_capture(path.name, path.read_bytes(), None, None,
                               path.with_name(path.name[:-len(".sigmf-data")] + ".sigmf-meta").read_bytes())
        except ValueError:
            quiet or print("skip (too long for an in-memory load):", stem)
            continue
        x, fs = cap.iq, cap.sample_rate
        w = max(8, int(fs * 2e-4))
        p = np.convolve(np.abs(x) ** 2, np.ones(w) / w, "same")
        i = int(np.argmax(p))
        a = i
        while a > 0 and p[a] > 0.25 * p[i]:
            a -= 1
        b = i
        while b < len(p) - 1 and p[b] > 0.25 * p[i]:
            b += 1
        seg = x[a:b]
        dets = blob["detections"]
        if len(seg) < 50 or not dets:
            continue
        fi = np.angle(seg[1:] * np.conj(seg[:-1])) * fs / (2 * np.pi)
        fi = np.convolve(fi, np.ones(3) / 3, "same")[3:-3]
        lo, hi = np.percentile(fi, [15, 85])
        centre = (lo + hi) / 2
        hit = [d for d in dets if d["freq_lower_hz"] <= centre <= d["freq_upper_hz"]
               and d["start_sample"] < b and d["end_sample"] > a]
        top = max(hit, key=lambda d: d.get("threshold_excess_db", -99)) if hit else None
        bw = top["freq_upper_hz"] - top["freq_lower_hz"] if top else None
        out.append(dict(file=stem, split_khz=(hi - lo) / 1e3, bw_khz=bw / 1e3 if bw else None,
                        ratio=bw / (hi - lo) if bw and hi > lo else None, found=top is not None,
                        # B3 truth (config.bounds_ok_min_g5): tone split + 2 x expected rate
                        b3_ratio=bw / ((hi - lo) + 2 * entry["expected_rate_hz"]) if bw and entry["expected_rate_hz"] else None,
                        n_cands=len(dets), n_lines=sum(d["freq_upper_hz"] - d["freq_lower_hz"] < 3e3 for d in dets),
                        pulsed=top.get("is_pulsed") if top else None, label=top.get("modulation_label") if top else None,
                        exp_rate=entry["expected_rate_hz"], fs=fs))
        quiet or print(stem, flush=True)
    out_path.write_text(json.dumps(out, indent=1, default=float) + "\n")
    summarize(out)
    return out


def summarize(out):
    r = [o for o in out if o["ratio"] is not None]
    print(len(out), "files; no candidate contains the burst centre:", sum(not o["found"] for o in out),
          "; ratio < 0.5:", sum(o["ratio"] < 0.5 for o in r), "; 0.5-2:", sum(0.5 <= o["ratio"] <= 2 for o in r),
          "; > 2:", sum(o["ratio"] > 2 for o in r), "; median candidates per file:", sorted(o["n_cands"] for o in out)[len(out) // 2])
    ok, n = b3_count(out)
    rated = [o for o in out if o["exp_rate"]]
    print(f"B3 bounds ok: {ok} of {n} rated files"
          f" (> 2x: {sum(o['b3_ratio'] is not None and o['b3_ratio'] > 2 for o in rated)},"
          f" < 0.5x: {sum(o['b3_ratio'] is not None and o['b3_ratio'] < 0.5 for o in rated)},"
          f" no candidate: {sum(o['b3_ratio'] is None for o in rated)})")
    return ok, n


def b3_count(out):
    """(files with B3-usable bounds, rated files): band within the registered ratio window of tone split + 2 x rate."""
    rated = [o for o in out if o["exp_rate"]]
    return sum(o.get("b3_ratio") is not None and TH.bounds_ratio_lo <= o["b3_ratio"] <= TH.bounds_ratio_hi for o in rated), len(rated)


if __name__ == "__main__":
    run()
