"""Fit the verify estimator's publication thresholds on a cross-generator CALIBRATION split.

    python -m experiments.readiness.calibrate            # writes docs/verify-thresholds.json

Calibration data never overlaps the scoreboard's test data:
  G1: spike corpus seed 4 (test uses seed 7);  G2: seeds from G2_CALIBRATION_SEEDS, one per cell
  (test uses G2_TEST_SEED_BASE...). Held-out families (8-FSK, 8-QAM) are excluded.
Each capture goes through the product path (Detect -> matched candidate -> verify window).

Rule (the spike's): a rate is only published for a digital winner whose family margin passes;
the smallest margin reaching >= 95% precision on >= 8 captures, found on
EACH generator separately; the larger (stricter) of the two is kept. The margin unit is chosen
on calibration data too: per-sample nats (the spike's), per-symbol nats (x samples/symbol) or
total nats (x samples) -- whichever publishes the most correct answers at that precision.
"""
import argparse
import json
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

from backend.experimental.estimate_spike import Thresholds, decide
from backend.experimental.estimate_spike.hypothesis import DIGITAL_EXPERTS, UNKNOWN_CE
from backend.pipeline.verify_estimator import THRESHOLDS_FILE, verify_candidate
from . import generators, systems, synth_wide
from .metrics import label_matches, rate_matches

ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / "artifacts" / "readiness" / "calibration_rows.json"
UNITS = ("sample", "symbol", "total")
PRECISION, MIN_COUNT = 0.95, 8
RAW = Thresholds(m_fam=-np.inf, m_rate=-np.inf, unexplained_max=np.inf, min_usage=0.0)


def calibration_captures(g1_n=500):
    yield from generators.g1_captures(g1_n, seed=4)
    seeds = iter(generators.G2_CALIBRATION_SEEDS)
    for kind in generators.G2_KINDS_DIGITAL:
        for fc in generators.G2_CARRIERS:
            for sps in generators.G2_SPS:
                for snr in generators.G2_SNRS:
                    yield generators.g2_capture(kind, snr, fc, sps, next(seeds))
    for kind in ("fm", "noise"):
        for fc in generators.G2_CARRIERS:
            for snr in generators.G2_SNRS:
                yield generators.g2_capture(kind, snr, fc, 96, next(seeds))


def _row(cap):
    pc, res, dets, primary, info = systems.detect(cap)
    cands = [primary] if primary is not None else (dets if cap.truth["label"] == "noise" else [])
    out = []
    for d in cands:
        est = systems.classify.estimate_candidate(pc, d, noise_floor=res.noise_floor)
        v = verify_candidate(pc, est, return_raw=True)
        if "_raw" not in v:
            continue
        r, dd = v["_raw"]
        n = v["verify_segment"]["samples"]
        fs = v["verify_segment"]["sample_rate_hz"]
        out.append(dict(hyps=[[h.expert, h.label, h.rate, h.score, h.residual, h.usage] for h in r.hypotheses],
                        noise_var=r.noise_var, total_power=r.total_power, n=n, fs=fs))
    truth = {k: (list(v) if isinstance(v, tuple) else v) for k, v in cap.truth.items()}
    return dict(gen=cap.gen, id=cap.id, truth=truth, cands=out)


def _hyps(c):
    from backend.experimental.estimate_spike import Hypothesis
    return [Hypothesis(e, lab, rate, s, res, u) for e, lab, rate, s, res, u in c["hyps"]]


def margins(row):
    """Per candidate: raw decision and margins in each unit."""
    out = []
    for c in row["cands"]:
        d = decide(_hyps(c), c["noise_var"], c["total_power"], RAW)
        sps = c["fs"] / d.rate if d.rate else np.nan
        scale = dict(sample=1.0, symbol=sps, total=float(c["n"]))
        best = min(_hyps(c), key=lambda h: h.score)
        out.append(dict(d=d, usage=best.usage, scale=scale))
    return out


def fit(rows, unit, min_usage):
    """Thresholds for one margin unit; coverage = published-correct labels + rates on calibration."""
    per_gen = {}
    M = {gen: [(r, m) for r in rows if r["gen"] == gen for m in margins(r)] for gen in ("G1", "G2")}
    for gen, pairs in M.items():
        L = [(m["d"].m_fam * m["scale"][unit], label_matches(m["d"].label, r["truth"]["label"]), m["d"].unexplained)
             for r, m in pairs if m["d"].family not in ("none", UNKNOWN_CE) and m["usage"] >= min_usage]
        per_gen[gen] = [_pick(L), None, L, None]
    t_fam = max(per_gen[g][0] for g in per_gen)
    # a rate is published only for a digital winner whose family margin also passes
    for gen, pairs in M.items():
        T = [(m["d"].m_rate * m["scale"][unit], rate_matches(m["d"].rate, r["truth"]["rate"]))
             for r, m in pairs if m["d"].expert in DIGITAL_EXPERTS and m["d"].m_fam * m["scale"][unit] >= t_fam]
        per_gen[gen][1], per_gen[gen][3] = _pick(T), T
    t_rate = max(per_gen[g][1] for g in per_gen)
    good = [u for g in per_gen for m, ok, u in per_gen[g][2] if ok and m >= t_fam and np.isfinite(u)]
    t_unexp = float(np.percentile(good, 95)) if good else 1.0
    cover = sum(ok for g in per_gen for m, ok, u in per_gen[g][2] if m >= t_fam and u <= t_unexp) + \
        sum(ok for g in per_gen for m, ok in per_gen[g][3] if m >= t_rate)
    return dict(unit=unit, m_fam=t_fam, m_rate=t_rate, unexplained_max=t_unexp, coverage=int(cover))


def _pick(pairs):
    vals = sorted({round(p[0], 6) for p in pairs if np.isfinite(p[0])})
    for th in vals:
        sel = [p[1] for p in pairs if p[0] >= th]
        if len(sel) >= MIN_COUNT and np.mean(sel) >= PRECISION:
            return float(th)
    return float("inf")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--reuse", action="store_true")
    ap.add_argument("--workers", type=int, default=10)
    args = ap.parse_args(argv)
    if args.reuse and CACHE.exists():
        rows = json.loads(CACHE.read_text())
    else:
        t0 = time.time()
        with ProcessPoolExecutor(args.workers) as ex:
            rows = list(ex.map(_row, calibration_captures(), chunksize=4))
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        CACHE.write_text(json.dumps(rows, default=float))
        print(f"{len(rows)} calibration captures in {time.time() - t0:.0f} s")
    min_usage = Thresholds().min_usage
    fits = [fit(rows, u, min_usage) for u in UNITS]
    for f in fits:
        print(f)
    best = max(fits, key=lambda f: f["coverage"])
    blob = dict(thresholds=dict(m_fam=best["m_fam"], m_rate=best["m_rate"],
                                unexplained_max=best["unexplained_max"], min_usage=min_usage),
                margin_unit=best["unit"],
                provenance=(f"margin thresholds fit on a cross-generator calibration split (G1 seed 4, "
                            f"G2 calibration seeds; {len(rows)} captures): >= 95% precision on each generator; "
                            f"margins are nats per {best['unit']}, not probabilities"),
                candidates=fits, n_captures=len(rows))
    THRESHOLDS_FILE.write_text(json.dumps(blob, indent=1, default=float) + "\n")
    print("wrote", THRESHOLDS_FILE.relative_to(ROOT), best)


if __name__ == "__main__":
    main()
