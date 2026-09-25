"""Tables for docs/estimate_spike_results.md from run_eval rows (calibration/test split, ablations, router).

    python -m experiments.estimate_spike.evaluate artifacts/estimate_spike/rows_seed4.json --md out.md --json out.json

Split and threshold rule match the prototype's evaluate4.py: half A (calibration)
is default_rng(0).random(n) < 0.5; 8PSK is excluded from calibration (held out);
thresholds are the smallest margin reaching >= 95% precision on >= 8 captures.
"""
import argparse
import json
from pathlib import Path

import numpy as np

from backend.experimental.estimate_spike import Thresholds, decide
from backend.experimental.estimate_spike.features import FEATURE_NAMES
from backend.experimental.estimate_spike.hypothesis import ALL_EXPERTS, DIGITAL_EXPERTS, Hypothesis

KINDS = ["PSK", "QAM16", "FSK2", "AM", "FM", "8PSK", "noise"]
SNR_BINS = [(-6, -1), (-1, 4), (4, 9), (9, 14)]

# Prototype v5 numbers from the task brief (seed 4, 500 captures).
REF_RAW = {"PSK": (70.6, 65.0), "QAM16": (65.6, 65.6), "FSK2": (56.4, 50.0), "AM": (38.9, None),
           "FM": (51.0, None), "8PSK": (0.0, 59.6), "noise": (97.9, None)}
REF_SNR = {"PSK": (20.8, 81.6, 85.3, 92.1), "QAM16": (11.8, 72.7, 92.3, 90.0), "FSK2": (0.0, 15.4, 87.5, 80.0)}
REF_DEC = {"PSK": (94, 50, 100, 7, 36, 100, 0), "QAM16": (34, 47, 100, 6, 53, 100, 0),
           "FSK2": (42, 26, 100, 2, 57, 92, 2), "AM": (31, 6, 50, 3, 3, 0, 2), "FM": (26, 38, 100, 0, 0, None, 0),
           "8PSK": (21, 19, 0, 5, 29, 100, 4), "noise": (29, 0, None, 0, 0, None, 0)}
REF_RECALL = {"PSK/QAM gap-difference": (100, 96, 81), "PSK/QAM old E1/E2": (93, 62, 8),
              "FSK gap-difference": (98, "14–16", 4), "FSK old E4": (7, 0, 0),
              "PSK/QAM finalists (after ranking + needle)": (None, None, None),
              "FSK finalists (after Fisher ranking)": (None, None, None)}
REF_ABL = {"full system": (8, 59.6), "without rrc": (15, 61.4), "without fsk": (2, 49.5),
           "without analog": (3, 52.3), "without null": (11, None)}
REF_ROUTER = {"dense": (177, None, 59.6, 8), "top-1": (52, 57.4, 51.3, 1), "top-2": (80, 83.8, 59.6, 1)}


def hyps_of(row, drop_null=False):
    out = [Hypothesis(e, lab, r, s, res) for e, r, s, lab, res in row["hyps"]]
    if drop_null:
        out = [h if h.expert != "null" else Hypothesis("null", "none", None, np.inf, 0.0) for h in out]
    return out


def truth_ok(row, d):
    fam_ok = d.family == row["fam"]
    label_ok = fam_ok and (row["fam"] != "PSK" or d.label == row["label"])
    rate_ok = row["Rs"] is not None and d.rate is not None and abs(d.rate - row["Rs"]) / row["Rs"] < 0.05
    return fam_ok, label_ok, rate_ok


def run(rows, active=ALL_EXPERTS, drop_null=False):
    out = []
    for r in rows:
        d = decide(hyps_of(r, drop_null), r["noise_var"], r["total_power"], Thresholds(), active)
        f, l, ra = truth_ok(r, d)
        out.append(dict(d=d, fam_ok=f, label_ok=l, rate_ok=ra))
    return out


def fit_thresholds(rows, D, half):
    A = [i for i in range(len(rows)) if half[i] and rows[i]["kind"] != "8PSK"]

    def pick(key, okkey, subset):
        vals = sorted(set(round(getattr(D[i]["d"], key), 4) for i in subset
                          if not np.isnan(getattr(D[i]["d"], key))))
        for th in vals:
            sel = [i for i in subset if getattr(D[i]["d"], key) >= th]
            if len(sel) >= 8 and np.mean([D[i][okkey] for i in sel]) >= 0.95:
                return th
        return np.inf
    t_fam = pick("m_fam", "label_ok", [i for i in A if D[i]["d"].family != "none"])
    t_rate = pick("m_rate", "rate_ok", [i for i in A if D[i]["d"].expert in DIGITAL_EXPERTS])
    good = [D[i]["d"].unexplained for i in A if D[i]["label_ok"] and D[i]["d"].m_fam >= t_fam
            and rows[i]["kind"] != "noise"]
    return Thresholds(t_fam, t_rate, float(np.percentile(good, 95)) if good else 1.0)


def held_out(rows, D, half, th):
    B = [i for i in range(len(rows)) if not half[i]]
    table, cw_total = {}, 0
    for k in KINDS:
        I = [i for i in B if rows[i]["kind"] == k]
        if not I:
            continue
        fam_pass = [i for i in I if D[i]["d"].family != "none" and D[i]["d"].m_fam >= th.m_fam]
        lab = [i for i in fam_pass if D[i]["d"].unexplained <= th.unexplained_max]
        unk = [i for i in fam_pass if D[i]["d"].unexplained > th.unexplained_max]
        rat = [i for i in I if D[i]["d"].expert in DIGITAL_EXPERTS and D[i]["d"].m_rate >= th.m_rate]
        cw = sum(1 for i in I if (i in lab and not D[i]["label_ok"]) or (i in rat and not D[i]["rate_ok"]))
        cw_total += cw
        pct = lambda a, b: 100 * len(a) / len(b)
        table[k] = dict(n=len(I), label_shipped=pct(lab, I),
                        label_right=100 * np.mean([D[i]["label_ok"] for i in lab]) if lab else None,
                        unknown=pct(unk, I), rate_shipped=pct(rat, I),
                        rate_right=100 * np.mean([D[i]["rate_ok"] for i in rat]) if rat else None, cw=cw)
    return table, cw_total, len(B)


def recall(rows):
    def hit(props, rs):
        return any(abs(p - rs) / rs < 0.02 for p in props)
    bins = [("≥ 4 dB", lambda s: s >= 4), ("−1..4 dB", lambda s: -1 <= s < 4), ("< −1 dB", lambda s: s < -1)]
    sets = {"PSK/QAM gap-difference": (("PSK", "QAM16"), "psk_proposals"),
            "PSK/QAM old E1/E2": (("PSK", "QAM16"), "legacy_psk"),
            "PSK/QAM finalists (after ranking + needle)": (("PSK", "QAM16"), "psk_finalists"),
            "FSK gap-difference": (("FSK2",), "fsk_proposals"), "FSK old E4": (("FSK2",), "legacy_fsk"),
            "FSK finalists (after Fisher ranking)": (("FSK2",), "fsk_ranked")}
    out = {}
    for name, (kinds, key) in sets.items():
        out[name] = []
        for _, fn in bins:
            I = [r for r in rows if r["kind"] in kinds and fn(r["snr"])]
            # rows from before the FSK needle existed store the ranked finalists as fsk_finalists
            out[name].append((100 * np.mean([hit(r.get(key, r["fsk_finalists"] if key == "fsk_ranked" else None),
                                                 r["Rs"]) for r in I]), len(I)))
    return [b for b, _ in bins], out


def router(rows, dense, half):
    from sklearn.tree import DecisionTreeClassifier
    X = np.array([[r["features"][k] for k in FEATURE_NAMES] for r in rows])
    y = np.array([d["d"].expert if d["d"].expert != "null" else "nrz" for d in dense])
    clf = DecisionTreeClassifier(max_depth=4, random_state=0).fit(X[half], y[half])
    P, cls = clf.predict_proba(X), list(clf.classes_)
    # the FSK needle only has to run when the FSK expert does, so it is charged to that expert
    T = lambda r, e: r["timings_s"].get(e, 0.0) + (r["timings_s"].get("needle_fsk", 0.0) if e == "fsk" else 0.0)
    shared = np.array([T(r, "features") + T(r, "screen_psk") + T(r, "screen_fsk") for r in rows])
    dense_t = shared + np.array([sum(T(r, e) for e in ALL_EXPERTS) for r in rows])
    B = ~half
    res = {"dense": dict(ms=1e3 * dense_t[B].mean(), agree=None,
                         acc=100 * np.mean([dense[i]["label_ok"] for i in np.where(B)[0]]),
                         cw=held_out(rows, dense, half, fit_thresholds(rows, dense, half))[1])}
    for kk in (1, 2):
        Ds, tm = [], []
        for i, r in enumerate(rows):
            act = tuple(cls[j] for j in np.argsort(-P[i])[:kk])
            d = decide(hyps_of(r), r["noise_var"], r["total_power"], Thresholds(), act)
            f, l, ra = truth_ok(r, d)
            Ds.append(dict(d=d, fam_ok=f, label_ok=l, rate_ok=ra))
            tm.append(shared[i] + sum(T(r, e) for e in act))
        tm = np.array(tm)
        Bi = np.where(B)[0]
        agree = 100 * np.mean([Ds[i]["d"].label == dense[i]["d"].label and Ds[i]["d"].expert == dense[i]["d"].expert
                               for i in Bi])
        res[f"top-{kk}"] = dict(ms=1e3 * tm[B].mean(), agree=agree, acc=100 * np.mean([Ds[i]["label_ok"] for i in Bi]),
                                cw=held_out(rows, Ds, half, fit_thresholds(rows, Ds, half))[1])
    return res


def fmt(v, digits=1, suffix="%"):
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return "n/a"
    if isinstance(v, str):
        return v + suffix
    return f"{v:.{digits}f}{suffix}"


def gap(ours, ref):
    """Flag cells more than 10 points from the reference."""
    if ours is None or ref is None or isinstance(ref, str) or np.isnan(ours):
        return ""
    return " ⚠" if abs(ours - ref) > 10 else ""


def evaluate(path: Path):
    blob = json.loads(path.read_text())
    rows = blob["rows"]
    half = np.random.default_rng(0).random(len(rows)) < 0.5
    dense = run(rows)
    th = fit_thresholds(rows, dense, half)
    md, js = [], dict(meta=blob["meta"], thresholds=th.__dict__)

    md.append("#### Raw best-hypothesis accuracy (all captures, no abstention)\n")
    md.append("| Kind | n | Label right | ref | Rate right | ref |\n|---|---|---|---|---|---|")
    js["raw"] = {}
    for k in KINDS:
        I = [i for i in range(len(rows)) if rows[i]["kind"] == k]
        la = 100 * np.mean([dense[i]["label_ok"] for i in I])
        ra = 100 * np.mean([dense[i]["rate_ok"] for i in I]) if rows[I[0]]["Rs"] is not None else None
        rl, rr = REF_RAW[k]
        js["raw"][k] = dict(n=len(I), label=la, rate=ra)
        md.append(f"| {k} | {len(I)} | {fmt(la)}{gap(la, rl)} | {fmt(rl)} | {fmt(ra)}{gap(ra, rr)} | {fmt(rr)} |")

    md.append("\n#### Raw rate accuracy by SNR (ours / ref)\n")
    md.append("| | " + " | ".join(f"{lo}..{hi} dB" for lo, hi in SNR_BINS) + " |\n|---|---|---|---|---|")
    js["rate_by_snr"] = {}
    for k in ("PSK", "QAM16", "FSK2"):
        cells = []
        for (lo, hi), ref in zip(SNR_BINS, REF_SNR[k]):
            I = [i for i in range(len(rows)) if rows[i]["kind"] == k and lo <= rows[i]["snr"] < hi]
            v = 100 * np.mean([dense[i]["rate_ok"] for i in I])
            js["rate_by_snr"].setdefault(k, []).append(dict(n=len(I), rate=v))
            cells.append(f"{fmt(v)} / {fmt(ref)} (n={len(I)}){gap(v, ref)}")
        md.append(f"| {k} | " + " | ".join(cells) + " |")

    table, cw, nB = held_out(rows, dense, half, th)
    js["held_out"], js["confidently_wrong"] = table, cw
    md.append(f"\n#### Held-out decisions (test half, n={nB}); thresholds from calibration half: "
              f"m_fam ≥ {th.m_fam:.3f}, m_rate ≥ {th.m_rate:.3f}, unexplained ≤ {th.unexplained_max:.3f} "
              f"(ref 0.411 / 0.149 / 0.097)\n")
    md.append("| Kind | n | Label shipped | Label right | Unknown-family | Rate shipped | Rate right | Confidently wrong |\n"
              "|---|---|---|---|---|---|---|---|")
    for k, t in table.items():
        rn, rls, rlr, ru, rrs, rrr, rcw = REF_DEC[k]
        md.append(f"| {k} | {t['n']} ({rn}) | {fmt(t['label_shipped'], 0)} ({fmt(rls, 0)}){gap(t['label_shipped'], rls)} "
                  f"| {fmt(t['label_right'], 0)} ({fmt(rlr, 0)}) | {fmt(t['unknown'], 0)} ({fmt(ru, 0)}) "
                  f"| {fmt(t['rate_shipped'], 0)} ({fmt(rrs, 0)}){gap(t['rate_shipped'], rrs)} "
                  f"| {fmt(t['rate_right'], 0)} ({fmt(rrr, 0)}) | {t['cw']} ({rcw}) |")
    md.append(f"\nTotal confidently wrong: **{cw}/{nB}** (ref 8/277). Reference values in parentheses.")

    names, rec = recall(rows)
    js["recall"] = rec
    md.append("\n#### Proposal recall (true rate within 2% of some proposal): ours / ref\n")
    md.append("| | " + " | ".join(names) + " |\n|---|---|---|---|")
    for name, cells in rec.items():
        md.append(f"| {name} | " + " | ".join(f"{fmt(v, 0)} / {fmt(ref, 0)} (n={n})"
                                            for (v, n), ref in zip(cells, REF_RECALL[name])) + " |")

    md.append("\n#### Ablations (test half)\n")
    md.append("| Variant | Confidently wrong | ref | Raw label acc (test half) | ref |\n|---|---|---|---|---|")
    js["ablations"] = {}
    Bi = [i for i in range(len(rows)) if not half[i]]
    variants = [("full system", ALL_EXPERTS, False)] + \
        [(f"without {e}", tuple(x for x in ALL_EXPERTS if x != e), False) for e in ("rrc", "fsk", "analog")] + \
        [("without null", ALL_EXPERTS, True)]
    for name, act, dn in variants:
        D = run(rows, act, dn)
        _, c, _ = held_out(rows, D, half, fit_thresholds(rows, D, half))
        acc = 100 * np.mean([D[i]["label_ok"] for i in Bi])
        js["ablations"][name] = dict(cw=c, acc=acc)
        rc, ra = REF_ABL[name]
        md.append(f"| {name} | {c}/{nB} | {rc}/277 | {fmt(acc)} | {fmt(ra)} |")

    rt = router(rows, dense, half)
    js["router"] = rt
    md.append("\n#### Router (depth-4 tree on the 6 features, trained on calibration half)\n")
    md.append("| Mode | Mean time / capture | ref | Same answer as dense | ref | Raw label acc | ref | Confidently wrong | ref |\n"
              "|---|---|---|---|---|---|---|---|---|")
    for m, v in rt.items():
        rms, rag, racc, rcw = REF_ROUTER[m]
        md.append(f"| {m} | {v['ms']:.0f} ms | {rms} ms | {fmt(v['agree'])} | {fmt(rag)} | {fmt(v['acc'])} | {fmt(racc)} "
                  f"| {v['cw']}/{nB} | {rcw}/277 |")

    stages = ["features", "screen_psk", "screen_fsk", "needle_fsk", "nrz", "rrc", "fsk", "analog"]
    md.append("\n#### Per-stage timing (all captures, one core)\n")
    md.append("| Stage | mean ms | p50 ms | p95 ms | max ms |\n|---|---|---|---|---|")
    js["timing_ms"] = {}
    for s in stages + ["total"]:
        v = 1e3 * np.array([r["total_s"] if s == "total" else r["timings_s"].get(s, 0.0) for r in rows])
        js["timing_ms"][s] = dict(mean=v.mean(), p50=np.median(v), p95=np.percentile(v, 95), max=v.max())
        md.append(f"| {s} | {v.mean():.1f} | {np.median(v):.1f} | {np.percentile(v, 95):.1f} | {v.max():.1f} |")
    over = sum(r["total_s"] > 0.5 for r in rows)
    js["over_budget"] = over
    md.append(f"\nCaptures over the 0.5 s budget: {over}/{len(rows)}.")
    return "\n".join(md) + "\n", js


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("rows", type=Path)
    ap.add_argument("--md", type=Path)
    ap.add_argument("--json", type=Path)
    args = ap.parse_args()
    md, js = evaluate(args.rows)
    print(md)
    if args.md:
        args.md.write_text(md)
    if args.json:
        args.json.write_text(json.dumps(js, indent=1, default=float))


if __name__ == "__main__":
    main()
