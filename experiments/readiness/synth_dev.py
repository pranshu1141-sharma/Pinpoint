"""Development check of the estimator criteria on G1/G2 *calibration* seeds (never the test seeds).

    python -m experiments.readiness.synth_dev [--workers 8] [--gens G1,G2]

The scoreboard refuses calibration seeds, so an estimator change is checked here first: the same
row computation and criteria (L1, L2, R1, R2, C1, C2) on G1 seed 4 and G2 seeds 200000+, the seeds the
verify thresholds were fit on. S1 (speed) is not judged here: rows are computed in parallel, and the
scoreboard times speed sequentially. Prints one line per criterion and the FM-labelled diagnostic.
"""
import argparse

from . import generators, scoreboard as sb

CAL_SEEDS = dict(g1=4, g2=generators.G2_CALIBRATION_SEEDS.start)
ESTIMATOR_IDS = ("L1", "L2", "R1", "R2", "C1", "C2")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--gens", default="G1,G2")
    ap.add_argument("--g1-n", type=int, default=sb.config.G1_TEST_N)
    a = ap.parse_args(argv)
    sb.SEEDS.update(CAL_SEEDS)
    rows = {g: sb.refresh_library_flags(sb.compute_rows("verify", g, a.workers, a.g1_n)) for g in a.gens.split(",")}
    stub = sb._crit("-", "not judged here", {})
    extra = dict(real=stub, cli=stub, docs=stub, g5=[], bounds_g5=stub)
    phases, _, stats = sb.evaluate({"verify": rows}, "verify", extra)
    for _, crits in phases:
        for c in crits:
            if c["id"] in ESTIMATOR_IDS:
                cells = "  ".join(f"{g}={'-' if v['value'] is None else format(v['value'], '.1%')} (n={v['n']})"
                                  for g, v in c["gens"].items() if g in rows)
                print(f"{c['id']} {'PASS' if c['passed'] else 'FAIL'}  {cells}  [{c['desc']}]")
    for g in rows:
        conf = stats["verify"][g]["confidence"]
        print(g, "FM labelled", conf.get("fm_labelled"))


if __name__ == "__main__":
    main()
