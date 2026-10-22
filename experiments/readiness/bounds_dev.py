"""Readiness step 1 tuning harness: Detect bounds on CALIBRATION data only (never scored).

    python -m experiments.readiness.bounds_dev [--stride 2] [--workers 8]

G4 calibration seeds (ablation conditions `none` and `all`): bounds ok (B1), fragmented (B2), correct/wrong labels.
G5 calibration FSK2 files: B3-style bounds (tone split + 2 x expected rate), as fsk_split_probe measures them.
"""
import argparse
from concurrent.futures import ProcessPoolExecutor

from . import ablation, fsk_split_probe, generators, impaired


def g4(stride, workers):
    specs = [s for s in generators.g4_specs(generators.G4_CALIBRATION_SEED_BASE)[::stride] if s["kind"] != "noise"]
    with ProcessPoolExecutor(workers) as ex:
        for name, imp in (("none", ()), ("all", impaired.IMPAIRMENTS)):
            s = ablation.summarize(list(ex.map(ablation._one, [(sp, imp) for sp in specs], chunksize=4)))
            print(f"G4 calibration {name:5s} n={s['n']} bounds ok {s['ok_bounds']:.1%} (B1 >= 85%) fragmented {s['fragmented']:.1%} "
                  f"(B2 <= 5%) too wide {s['too_wide']:.1%} too narrow {s['too_narrow']:.1%} | correct {s['correct']:.1%} "
                  f"wrong {s['wrong']:.1%} abstain {s['abstain']:.1%}", flush=True)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--stride", type=int, default=2)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--skip-g4", action="store_true")
    ap.add_argument("--skip-g5", action="store_true")
    args = ap.parse_args(argv)
    if not args.skip_g5:
        fsk_split_probe.run("calibration", fsk_split_probe.OUT.with_name("fsk_split_probe_calibration.json"), quiet=True)
    if not args.skip_g4:
        g4(args.stride, args.workers)


if __name__ == "__main__":
    main()
