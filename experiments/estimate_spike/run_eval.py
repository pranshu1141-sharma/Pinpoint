"""Run the Estimate spike over a seeded synthetic corpus and save one row per capture.

    python -m experiments.estimate_spike.run_eval --n 500 --seed 4 --out artifacts/estimate_spike/rows_seed4.json
    (add --prototype to disable post-prototype deviations for a faithful reproduction)
"""
import argparse
import dataclasses
import json
import time
from pathlib import Path

from backend.experimental.estimate_spike import DEFAULT, analyze_segment
from .legacy_proposers import legacy_fsk, legacy_psk
from .signals import REF_FS, corpus


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=500)
    ap.add_argument("--seed", type=int, default=4)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--prototype", action="store_true", help="disable post-prototype deviations (exact v5)")
    ap.add_argument("--no-fsk-needle", action="store_true", help="keep the FSK timing re-refine, skip the FSK needle")
    args = ap.parse_args()
    cfg = DEFAULT
    if args.prototype:
        cfg = dataclasses.replace(cfg, fsk_rescore_refine=False, fsk_needle=False)
    elif args.no_fsk_needle:
        cfg = dataclasses.replace(cfg, fsk_needle=False)
    rows, t_start = [], time.time()
    for i, (x, truth) in enumerate(corpus(args.n, args.seed)):
        t0 = time.perf_counter()
        r = analyze_segment(x, REF_FS, cfg)
        total = time.perf_counter() - t0
        row = r.to_dict()
        row["hyps"] = [[h.expert, h.rate, h.score, h.label, h.residual] for h in r.hypotheses]
        del row["hypotheses"]
        row.update(truth, total_s=total, legacy_psk=legacy_psk(x, REF_FS), legacy_fsk=legacy_fsk(x, REF_FS))
        rows.append(row)
        if (i + 1) % 50 == 0:
            print(i + 1, round(time.time() - t_start, 1), flush=True)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    meta = dict(n=args.n, seed=args.seed, prototype=args.prototype, no_fsk_needle=args.no_fsk_needle, config=dataclasses.asdict(cfg))
    args.out.write_text(json.dumps(dict(meta=meta, rows=rows), default=float))
    print("done", len(rows), round(time.time() - t_start, 1))


if __name__ == "__main__":
    main()
