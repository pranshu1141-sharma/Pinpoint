"""Run every system on every generator and write docs/READINESS.md + docs/readiness.json.

    python -m experiments.readiness.scoreboard            # full run (G1, G2, G3 when present)
    python -m experiments.readiness.scoreboard --reuse    # re-score cached rows only

A bar is the fraction of that phase's pass/fail criteria that pass. Thresholds live
in config.py and are fixed. Rows are cached in artifacts/readiness/ (git-ignored).
"""
import argparse
import json
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from . import config, generators, metrics, systems
from .config import THRESHOLDS as TH
from .render import render_bar

ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / "artifacts" / "readiness"
GENS = ("G1", "G2", "G3")


# ------------------------------------------------------------------ running

def _g1_job(args):
    system, cap = args
    return systems.run(system, cap)


def _g2_job(args):
    system, spec = args
    return systems.run(system, generators.g2_capture(**spec))


def compute_rows(system, gen, workers, g1_n, cached=()):
    """Rows for every capture of `gen`; captures whose id is in `cached` rows are reused."""
    have = {r["id"]: r for r in cached}
    if gen == "G1":
        caps = list(generators.g1_captures(g1_n))
        ids = [c.id for c in caps]
        jobs, fn = [(system, c) for c in caps if c.id not in have], _g1_job
    elif gen == "G2":
        specs = generators.g2_specs()
        ids = [generators.g2_capture_id(**s) for s in specs]
        jobs, fn = [(system, s) for s, i in zip(specs, ids) if i not in have], _g2_job
    else:
        return []
    if jobs:
        with ProcessPoolExecutor(workers) as ex:
            for r in ex.map(fn, jobs, chunksize=4):
                have[r["id"]] = r
    return [have[i] for i in ids]


def refresh_library_flags(rows):
    """Library membership can change (WP3); cached truth rows carry the flags of their run."""
    for r in rows:
        r["truth"]["in_library"] = r["truth"]["label"] in config.IN_LIBRARY
        r["truth"]["out_of_library"] = r["truth"]["label"] in config.OUT_OF_LIBRARY
    return rows


# ------------------------------------------------------------------ criteria

def _crit(cid, desc, per_gen):
    """per_gen: {gen: (value, pass_bool_or_None, n)}; None pass = not applicable on that gen."""
    applicable = [p for _, p, _ in per_gen.values() if p is not None]
    ok = bool(applicable) and all(applicable)
    return dict(id=cid, desc=desc, passed=ok,
                gens={g: dict(value=v, passed=p, n=n) for g, (v, p, n) in per_gen.items()})


def _le(v, lim):
    return None if v is None else v <= lim


def _ge(v, lim):
    return None if v is None else v >= lim


def evaluate(rows_by, product, extra):
    """rows_by[system][gen] -> list of rows. Returns phases (list of dicts) and raw stats."""
    stats = {}
    for sysname, by_gen in rows_by.items():
        for gen, rows in by_gen.items():
            if not rows:
                continue
            s = dict(label=metrics.label_stats(rows), rate=metrics.rate_stats(rows),
                     confidence=metrics.confidence_stats(rows), speed=metrics.speed_stats(rows))
            if rows[0]["detect"] is not None:
                s["detect"] = metrics.detect_stats(rows)
                s["params"] = metrics.param_stats(rows)
            stats.setdefault(sysname, {})[gen] = s

    def per(sysname, key, field, test, gens=("G1", "G2")):
        out = {}
        for g in gens:
            s = stats.get(sysname, {}).get(g, {}).get(key)
            v = None if s is None else s.get(field)
            nkey = {"recall": "n_strong", "noise_false": "n_noise", "fragmentation": "n_found",
                    "cf_ok": "n_linear", "bw3_ok": "n_linear", "snr_ok": "n_signal",
                    "published_correct_in_library": "n_in_library", "published_correct_digital": "n_digital",
                    "noise_labelled": "n_noise", "ool_wrong": "n_ool"}.get(field, "n")
            out[g] = (v, test(v), None if s is None else s.get(nkey))
        return out

    def estimator_phases(sysname):
        pf = TH.param_pass_fraction
        return [
            ("Modulation label", [
                _crit("L1", f"published-wrong labels <= {TH.label_wrong_max:.0%} of captures",
                      per(sysname, "label", "published_wrong", lambda v: _le(v, TH.label_wrong_max))),
                _crit("L2", f"published-correct >= {TH.label_correct_min:.0%} of in-library digital at >= 5 dB",
                      per(sysname, "label", "published_correct_in_library", lambda v: _ge(v, TH.label_correct_min)))]),
            ("Symbol rate", [
                _crit("R1", f"published-wrong rates <= {TH.rate_wrong_max:.0%} of captures",
                      per(sysname, "rate", "published_wrong", lambda v: _le(v, TH.rate_wrong_max))),
                _crit("R2", f"published-correct >= {TH.rate_correct_min:.0%} of digital at >= 5 dB",
                      per(sysname, "rate", "published_correct_digital", lambda v: _ge(v, TH.rate_correct_min)))]),
            ("Confidence/abstention", [
                _crit("C1", "noise -> 0% labels published",
                      per(sysname, "confidence", "noise_labelled", lambda v: _le(v, 0.0))),
                _crit("C2", f"out-of-library families -> <= {TH.ool_wrong_max:.0%} wrong labels",
                      per(sysname, "confidence", "ool_wrong", lambda v: _le(v, TH.ool_wrong_max))),
                _crit("C3", "no 'calibrated' wording beside a published label",
                      per(sysname, "confidence", "calibration_claims", lambda v: None if v is None else v == 0))]),
            ("Speed", [
                _crit("S1", f">= {TH.speed_pass_fraction:.0%} of candidates analysed in <= {TH.speed_s} s",
                      per(sysname, "speed", "within", lambda v: _ge(v, TH.speed_pass_fraction)))]),
        ]

    pf = TH.param_pass_fraction
    phases = [
        ("Detect", [
            _crit("D1", f"recall >= {TH.detect_recall_min:.0%} at >= 5 dB",
                  per("shipped", "detect", "recall", lambda v: _ge(v, TH.detect_recall_min))),
            _crit("D2", f"<= {TH.detect_noise_false_max:.0%} false detections on noise",
                  per("shipped", "detect", "noise_false", lambda v: _le(v, TH.detect_noise_false_max))),
            _crit("D3", f"fragmentation (single signal -> >= 2 detections) <= {TH.detect_fragmentation_max:.0%}",
                  per("shipped", "detect", "fragmentation", lambda v: _le(v, TH.detect_fragmentation_max)))]),
        ("Parameters", [
            _crit("P1", f"centre-frequency error <= {TH.cf_err_frac_bw:.0%} of true bandwidth (>= {pf:.0%} of captures)",
                  per(product, "params", "cf_ok", lambda v: _ge(v, pf))),
            _crit("P2", f"-3 dB bandwidth within +-{TH.bw3_tol:.0%} of truth (>= {pf:.0%} of captures)",
                  per(product, "params", "bw3_ok", lambda v: _ge(v, pf))),
            _crit("P3", f"SNR error <= {TH.snr_err_db:g} dB at >= 5 dB (>= {pf:.0%} of captures)",
                  per(product, "params", "snr_ok", lambda v: _ge(v, pf)))]),
    ] + estimator_phases(product) + [
        ("Real data (G3)", [extra["real"]]),
        ("Automation", [extra["cli"]]),
        ("Docs", [extra["docs"]]),
    ]
    alt = [s for s in rows_by if s != product]
    candidate = {s: estimator_phases(s) for s in alt}
    return phases, candidate, stats


def gen_marks(criteria):
    marks = {}
    for g in GENS:
        vals = [c["gens"][g]["passed"] for c in criteria if g in c["gens"] and c["gens"][g]["passed"] is not None]
        marks[g] = None if not vals else all(vals)
    return marks


# ------------------------------------------------------------------ non-generator criteria

def real_criterion():
    from . import real
    return real.criterion()


def cli_criterion():
    test = ROOT / "backend" / "tests" / "test_cli.py"
    exists = (ROOT / "backend" / "cli.py").exists() and test.exists()
    ok = False
    if exists:
        ok = subprocess.run([sys.executable, "-m", "pytest", str(test), "-q", "-p", "no:cacheprovider"],
                            cwd=ROOT, capture_output=True).returncode == 0
    return _crit("A1", "batch CLI exists and its test passes", {"G3": (ok, ok if exists else False, None)})


def docs_criterion(readiness):
    from . import docs_check
    ok, problems = docs_check.check(readiness)
    return dict(_crit("X1", "README, PROJECT_STATUS and CLAIMS agree with readiness.json",
                      {"G3": (len(problems), ok, None)}), problems=problems)


# ------------------------------------------------------------------ output

def render(phases, candidate, stats, product, meta):
    width = max(len(n) for n, _ in phases) + 3
    lines = ["# PinPoint readiness", "",
             f"Generated by `python -m experiments.readiness.scoreboard` at commit `{meta['commit']}` "
             f"({meta['date']}). Product estimator: **{product}**. "
             "A bar is the fraction of that phase's pass/fail criteria that pass; thresholds are fixed in "
             "`experiments/readiness/config.py`. G1 = spike corpus (seed 7), G2 = widened shipped fixtures, "
             "G3 = real recordings. ✓ all criteria pass on that generator, ✗ at least one fails, – no data.", "",
             "```"]
    passed_all = total_all = 0
    for name, crits in phases:
        p = sum(c["passed"] for c in crits)
        passed_all += p
        total_all += len(crits)
        lines.append(render_bar(name, p, len(crits), gen_marks(crits), width))
    lines += ["-" * 20, render_bar("Overall", passed_all, total_all, {}, width).rstrip(" []"), "```", ""]
    for sysname, ph in candidate.items():
        lines += [f"Candidate estimator **{sysname}** on the same criteria (not the product default):", "", "```"]
        for name, crits in ph:
            lines.append(render_bar(name, sum(c["passed"] for c in crits), len(crits), gen_marks(crits), width))
        lines += ["```", ""]
    lines += ["## Criteria", "", "| Phase | ID | Criterion | G1 | G2 | G3 | Pass |", "|---|---|---|---|---|---|---|"]

    def cell(c, g):
        e = c["gens"].get(g)
        if e is None or e["passed"] is None:
            return "–" if e is None or e["value"] is None else _fmt(e["value"])
        n = "" if e["n"] is None else " (n=%d)" % e["n"]
        return "%s%s %s" % (_fmt(e["value"]), n, "✓" if e["passed"] else "✗")
    for name, crits in phases:
        for c in crits:
            lines.append(f"| {name} | {c['id']} | {c['desc']} | {cell(c, 'G1')} | {cell(c, 'G2')} | {cell(c, 'G3')} "
                         f"| {'✓' if c['passed'] else '✗'} |")
    for sysname, ph in candidate.items():
        for name, crits in ph:
            for c in crits:
                lines.append(f"| {name} ({sysname}) | {c['id']} | {c['desc']} | {cell(c, 'G1')} | {cell(c, 'G2')} "
                             f"| {cell(c, 'G3')} | {'✓' if c['passed'] else '✗'} |")
    lines += ["", "## Diagnostics (not criteria)", "", "| System | Gen | Labels published | Harmonic rate errors | "
              "Median BW3 ratio | Median SNR error dB | Speed p50 / p95 s |", "|---|---|---|---|---|---|---|"]
    for sysname, by in stats.items():
        for g, s in by.items():
            pr = s.get("params", {})
            lines.append(f"| {sysname} | {g} | {_fmt(s['label']['published'])} | {_fmt(s['rate']['harmonic_errors'])} "
                         f"| {_fmt(pr.get('median_bw3_ratio'), pct=False)} | {_fmt(pr.get('median_snr_err_db'), pct=False)} "
                         f"| {_fmt(s['speed']['p50_s'], pct=False)} / {_fmt(s['speed']['p95_s'], pct=False)} |")
    for name, crits in phases:
        for c in crits:
            if c.get("problems"):
                lines += ["", f"Docs problems ({len(c['problems'])}):", ""] + [f"- {p}" for p in c["problems"]]
    return "\n".join(lines) + "\n"


def _fmt(v, pct=True):
    if v is None:
        return "–"
    if isinstance(v, bool):
        return "yes" if v else "no"
    if isinstance(v, (int, str)):
        return str(v)
    return f"{100 * v:.1f}%" if pct else f"{v:.3g}"


def bars_block(md: str) -> str:
    start = md.index("```")
    return md[start:md.index("```", start + 3) + 3]


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--reuse", action="store_true", help="re-score cached rows")
    ap.add_argument("--fresh", default="", help="with --reuse: systems to recompute anyway (comma list)")
    ap.add_argument("--systems", default="shipped,verify")
    ap.add_argument("--gens", default="G1,G2")
    ap.add_argument("--workers", type=int, default=10)
    ap.add_argument("--g1-n", type=int, default=config.G1_TEST_N)
    ap.add_argument("--out", type=Path, default=ROOT / "docs")
    ap.add_argument("--sync-docs", action="store_true",
                    help="rewrite the bars in PROJECT_STATUS and the rj-marked numbers in CLAIMS first")
    args = ap.parse_args(argv)
    CACHE.mkdir(parents=True, exist_ok=True)
    rows_by = {}
    for sysname in args.systems.split(","):
        for gen in args.gens.split(","):
            path = CACHE / f"rows_{sysname}_{gen}.json"
            cached = json.loads(path.read_text()) if args.reuse and path.exists() \
                and sysname not in args.fresh.split(",") else []
            t0 = time.time()
            rows = compute_rows(sysname, gen, args.workers, args.g1_n, cached)
            if len(rows) != len(cached) or not cached:
                path.write_text(json.dumps(rows, default=float))
                print(f"{sysname} {gen}: {len(rows) - len(cached)} new rows in {time.time() - t0:.0f} s", flush=True)
            rows_by.setdefault(sysname, {})[gen] = refresh_library_flags(rows)
    product = systems.product_estimator()
    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True,
                            text=True).stdout.strip()
    meta = dict(commit=commit, date=time.strftime("%Y-%m-%d"), thresholds=TH.__dict__,
                in_library=sorted(config.IN_LIBRARY), out_of_library=sorted(config.OUT_OF_LIBRARY))
    extra = dict(real=real_criterion(), cli=cli_criterion(), docs=_crit("X1", "docs agree", {}))
    phases, candidate, stats = evaluate(rows_by, product, extra)
    # docs are checked against the readiness numbers computed in this run
    draft = dict(meta=meta, product=product, phases=[dict(name=n, criteria=c) for n, c in phases], stats=stats)
    draft["bars"] = bars_block(render(phases, candidate, stats, product, meta))
    if args.sync_docs:
        from . import docs_check
        docs_check.sync(draft)
    extra["docs"] = docs_criterion(draft)
    phases, candidate, stats = evaluate(rows_by, product, extra)
    md = render(phases, candidate, stats, product, meta)
    out = dict(meta=meta, product=product, bars=bars_block(md),
               phases=[dict(name=n, passed=sum(c["passed"] for c in cr), total=len(cr), criteria=cr) for n, cr in phases],
               candidate={s: [dict(name=n, passed=sum(c["passed"] for c in cr), total=len(cr), criteria=cr)
                              for n, cr in ph] for s, ph in candidate.items()},
               stats=stats)
    if args.sync_docs:   # the final bars (the Docs/Overall lines are not compared, so X1 is unchanged)
        from . import docs_check
        docs_check.sync(out)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "READINESS.md").write_text(md)
    (args.out / "readiness.json").write_text(json.dumps(out, indent=1, default=float) + "\n")
    print(bars_block(md))


if __name__ == "__main__":
    main()
