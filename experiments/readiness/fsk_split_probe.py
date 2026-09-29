"""WP3 follow-up: does Detect's band cover an FSK2 signal's tones? (diagnostic only, never scored)

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

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "artifacts" / "readiness" / "fsk_split_probe.json"


def run():
    args = argparse.Namespace(sample_rate=None, datatype=None, wav_mode="auto", margin_db=8.0, estimator="verify")
    out = []
    for stem, path, meta, entry in g5.folder_files():
        if not entry or entry["allowed_labels"] != ["FSK2"]:
            continue
        blob = analyze_file(path, args)
        try:
            cap = load_capture(path.name, path.read_bytes(), None, None,
                               path.with_name(path.name[:-len(".sigmf-data")] + ".sigmf-meta").read_bytes())
        except ValueError:
            print("skip (too long for an in-memory load):", stem)
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
        dets = [d for d in blob["detections"] if d.get("snr_db") is not None]
        if len(seg) < 50 or not dets:
            continue
        fi = np.angle(seg[1:] * np.conj(seg[:-1])) * fs / (2 * np.pi)
        fi = np.convolve(fi, np.ones(3) / 3, "same")[3:-3]
        lo, hi = np.percentile(fi, [15, 85])
        top = max(dets, key=lambda d: d["snr_db"])
        bw = top["freq_upper_hz"] - top["freq_lower_hz"]
        near = [e for e in dets if abs(e["snr_db"] - top["snr_db"]) < 3]
        out.append(dict(file=stem, split_khz=(hi - lo) / 1e3, bw_khz=bw / 1e3, ratio=bw / (hi - lo) if hi > lo else None,
                        n_near=len(near), pulsed=top.get("is_pulsed"), label=top.get("modulation_label"),
                        exp_rate=entry["expected_rate_hz"], fs=fs))
        print(stem, flush=True)
    OUT.write_text(json.dumps(out, indent=1, default=float) + "\n")
    r = [o for o in out if o["ratio"] is not None]
    print(len(r), "files; candidate narrower than half the tone split:", sum(o["ratio"] < 0.5 for o in r),
          "; more than twice the tone split:", sum(o["ratio"] > 2 for o in r))


if __name__ == "__main__":
    run()
