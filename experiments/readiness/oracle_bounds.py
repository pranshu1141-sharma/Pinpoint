"""WP3 follow-up: how much would correct candidate bounds be worth? (diagnostic only, never scored)

    python -m experiments.readiness.oracle_bounds   -> artifacts/readiness/oracle_bounds.json

For every G5 *test* file that is FSK2 or ASK2, has an expected rate and fits in memory, take the strongest
packet (active samples above a quarter of the peak power, gaps under 3 ms bridged, longest packet) and give
the verify estimator an ORACLE candidate: that packet, not flagged pulsed, with a band derived from the file's
own signal and its expected rate:
  FSK2  centre = midpoint of the 15th/85th percentile of the instantaneous frequency inside the packet,
        half-width = tone split / 2 + expected rate (Carson-like).
  ASK2  centre = peak of the smoothed packet spectrum, half-width = 2 x expected rate.
The expected rate comes from the manifest (truth), so this is an upper bound on what better Detect bounds plus
lifting the pulsed refusal could deliver. It is not a product path and must not be used to fit thresholds.
Compared with the same packet handed over with the band Detect actually produced for it.
"""
import argparse
import collections
import json
from pathlib import Path

import numpy as np

from backend.cli import analyze_file
from backend.pipeline import verify_estimator as ve
from backend.pipeline.ingest import load_capture
from . import g5
from .metrics import label_matches

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "artifacts" / "readiness" / "oracle_bounds.json"
GAP_S = 3e-3


def strongest_packet(x, fs):
    w = max(8, int(fs * 2e-4))
    p = np.convolve(np.abs(x) ** 2, np.ones(w) / w, "same")
    active = p > 0.25 * p.max()
    idx = np.flatnonzero(active)
    if idx.size == 0:
        return None
    breaks = np.flatnonzero(np.diff(idx) > GAP_S * fs)
    starts = np.r_[idx[0], idx[breaks + 1]]
    ends = np.r_[idx[breaks], idx[-1]] + 1
    k = int(np.argmax(ends - starts))
    return int(starts[k]), int(ends[k]), active


def oracle_band(x, fs, a, b, active, label, rate):
    seg, act = x[a:b], active[a:b]
    if label == "FSK2":
        fi = np.angle(seg[1:] * np.conj(seg[:-1])) * fs / (2 * np.pi)
        fi = np.convolve(fi, np.ones(3) / 3, "same")[3:-3]
        keep = act[4:len(seg) - 3]            # fi[j] belongs to sample j + 1; 3 dropped at each end
        fi = fi[keep] if keep.any() else fi
        lo, hi = np.percentile(fi, [15, 85])
        return (lo + hi) / 2, (hi - lo) / 2 + rate
    n = len(seg)
    spec = np.abs(np.fft.fftshift(np.fft.fft(seg * np.hanning(n)))) ** 2
    spec = np.convolve(spec, np.ones(max(3, n // 256)) / max(3, n // 256), "same")
    f = np.fft.fftshift(np.fft.fftfreq(n, 1 / fs))
    return float(f[int(np.argmax(spec))]), 2 * rate


def run():
    args = argparse.Namespace(sample_rate=None, datatype=None, wav_mode="auto", margin_db=8.0, estimator="verify")
    rows = []
    for stem, path, meta, entry in g5.folder_files():
        if not entry or entry["allowed_labels"] not in (["FSK2"], ["ASK2"]) or not entry.get("expected_rate_hz"):
            continue
        label, rate = entry["allowed_labels"][0], entry["expected_rate_hz"]
        try:
            cap = load_capture(path.name, path.read_bytes(), None, None,
                               path.with_name(path.name[:-len(".sigmf-data")] + ".sigmf-meta").read_bytes())
        except ValueError:
            rows.append(dict(file=stem, truth=label, outcome="skipped_too_long"))
            continue
        pk = strongest_packet(cap.iq, cap.sample_rate)
        if pk is None:
            continue
        a, b, active = pk
        centre, half = oracle_band(cap.iq, cap.sample_rate, a, b, active, label, rate)
        half = min(half, 0.45 * cap.sample_rate)
        cand = dict(freq_lower_hz=centre - half, freq_upper_hz=centre + half, start_sample=a, end_sample=b,
                    is_pulsed=False, pulse_windows=[])
        out = ve.verify_candidate(cap, cand, return_raw=True)
        row = dict(file=stem, truth=label, rate=rate, packet_samples=b - a, band_khz=[cand["freq_lower_hz"] / 1e3, cand["freq_upper_hz"] / 1e3],
                   label=out["modulation_label"], rate_out=out["symbol_rate_hz"], status=out["verify_status"])
        if "_raw" in out:
            from .diagnose import evidence, first_failure
            ev = evidence(*out["_raw"], out)
            row.update(cause=None if out["modulation_label"] else first_failure(ev), best=ev["best"], m_fam=ev["m_fam"],
                       unexplained=ev["unexplained"])
        else:
            row["cause"] = "short_segment" if "insufficient" in out["verify_status"] else "other"
        row["correct"] = bool(row["label"]) and label_matches(row["label"], label)
        row["wrong"] = bool(row["label"]) and not row["correct"]
        rows.append(row)
        print(stem, row["label"], row.get("cause"), flush=True)
    OUT.write_text(json.dumps(rows, indent=1, default=float) + "\n")
    for truth in ("FSK2", "ASK2"):
        r = [x for x in rows if x["truth"] == truth and x.get("outcome") != "skipped_too_long"]
        print(truth, "n", len(r), "correct", sum(x.get("correct", False) for x in r), "wrong", sum(x.get("wrong", False) for x in r),
              collections.Counter(x.get("cause") for x in r if not x.get("label")).most_common())


if __name__ == "__main__":
    run()
