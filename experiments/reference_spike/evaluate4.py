import json, sys, numpy as np
from decide4 import decide, truth_ok, FAM
from sklearn.tree import DecisionTreeClassifier
rows = json.load(open(sys.argv[1]))
rng = np.random.default_rng(0)
half = rng.random(len(rows)) < 0.5          # A = calibration, ~A = test
KINDS = ["PSK", "QAM16", "FSK2", "AM", "FM", "8PSK", "noise"]
ALL = ("nrz", "rrc", "fsk", "analog")

def run(active=ALL, use_null=True):
    out = []
    for r in rows:
        rr = r if use_null else dict(r, hyps=[h for h in r["hyps"] if h[0] != "null"])
        if not use_null:
            rr["hyps"] = rr["hyps"] + [["null", None, np.inf, "none", 0.0]]
        d = decide(rr, active)
        f, l, ra = truth_ok(r, d)
        out.append(dict(d, fam_ok=f, label_ok=l, rate_ok=ra))
    return out

def thresholds(D):
    """pick the smallest margins that give >=95% precision on half A (8PSK excluded: held out)"""
    A = [i for i in range(len(rows)) if half[i] and rows[i]["kind"] != "8PSK"]
    def pick(key, okkey, subset):
        vals = sorted(set(round(D[i][key], 4) for i in subset if not np.isnan(D[i][key])))
        for th in vals:
            sel = [i for i in subset if D[i][key] >= th]
            if len(sel) >= 8 and np.mean([D[i][okkey] for i in sel]) >= 0.95:
                return th
        return np.inf
    t_fam = pick("m_fam", "label_ok", [i for i in A if D[i]["fam"] != "none"])
    t_rate = pick("m_rate", "rate_ok", [i for i in A if D[i]["expert"] in ("nrz", "rrc", "fsk")])
    good = [D[i]["unexpl"] for i in A if D[i]["label_ok"] and D[i]["m_fam"] >= t_fam and rows[i]["kind"] != "noise"]
    u_max = float(np.percentile(good, 95)) if good else 1.0
    return t_fam, t_rate, u_max

def report(D, title, show=True):
    t_fam, t_rate, u_max = thresholds(D)
    B = [i for i in range(len(rows)) if not half[i]]
    if show:
        print(f"\n{title}\n  thresholds from half A: family margin {t_fam:.3f}, rate margin {t_rate:.3f}, unexplained <= {u_max:.3f}")
        print(f"  {'kind':6s} {'n':>4s} | label shipped  label right | 'unknown family' | rate shipped  rate right | confidently WRONG (label or rate)")
    tot = dict(cw=0, n=0)
    for k in KINDS:
        I = [i for i in B if rows[i]["kind"] == k]
        if not I: continue
        lab = [i for i in I if D[i]["fam"] != "none" and D[i]["m_fam"] >= t_fam and D[i]["unexpl"] <= u_max]
        unk = [i for i in I if D[i]["fam"] != "none" and D[i]["m_fam"] >= t_fam and D[i]["unexpl"] > u_max]
        rat = [i for i in I if D[i]["expert"] in ("nrz", "rrc", "fsk") and D[i]["m_rate"] >= t_rate]
        lr = np.mean([D[i]["label_ok"] for i in lab]) * 100 if lab else float("nan")
        rr_ = np.mean([D[i]["rate_ok"] for i in rat]) * 100 if rat else float("nan")
        cw = sum(1 for i in I if (i in lab and not D[i]["label_ok"]) or (i in rat and not D[i]["rate_ok"]))
        tot["cw"] += cw; tot["n"] += len(I)
        if show:
            print(f"  {k:6s} {len(I):4d} | {len(lab)/len(I)*100:8.0f}%    {lr:6.0f}%   |   {len(unk)/len(I)*100:6.0f}%        | {len(rat)/len(I)*100:8.0f}%    {rr_:6.0f}%   |  {cw:3d}/{len(I):3d} = {cw/len(I)*100:4.1f}%")
    return tot

dense = run()
# raw accuracy (no thresholds) per kind
print("RAW best-hypothesis accuracy, all trials (no abstention):")
for k in KINDS:
    I = [i for i in range(len(rows)) if rows[i]["kind"] == k]
    fa = np.mean([dense[i]["label_ok"] for i in I]) * 100
    ra = np.mean([dense[i]["rate_ok"] for i in I]) * 100 if rows[I[0]]["Rs"] is not None else float("nan")
    print(f"  {k:6s} n={len(I):3d}  label right {fa:5.1f}%   rate right {ra:5.1f}%")
report(dense, "DENSE (all experts) — decisions on held-out half B")

# per-SNR for digital rate
print("\n  rate right (raw) by SNR, digital kinds:")
for lo, hi in [(-6, -1), (-1, 4), (4, 9), (9, 14)]:
    for k in ("PSK", "QAM16", "FSK2"):
        I = [i for i in range(len(rows)) if rows[i]["kind"] == k and lo <= rows[i]["snr"] < hi]
        if I: print(f"    {lo:3d}..{hi:<3d}dB {k:6s} n={len(I):3d}  {np.mean([dense[i]['rate_ok'] for i in I])*100:5.1f}%", end="")
    print()

# ---------------- Law 6: ablations
print("\nLAW 6 — remove one part at a time (held-out half B, confidently-wrong total):")
base = report(dense, "", show=False)
print(f"  full system                 confidently wrong {base['cw']}/{base['n']}")
for drop in ("rrc", "fsk", "analog"):
    act = tuple(e for e in ALL if e != drop)
    D = run(act); tt = report(D, "", show=False)
    acc = np.mean([D[i]["label_ok"] for i in range(len(rows)) if not half[i]]) * 100
    print(f"  without {drop:7s} expert        confidently wrong {tt['cw']}/{tt['n']}   raw label acc {acc:.1f}%")
D = run(use_null=False); tt = report(D, "", show=False)
print(f"  without null model          confidently wrong {tt['cw']}/{tt['n']}")

# ---------------- Law 1: learned router, top-k experts
print("\nLAW 1 — sparse activation: a small decision tree (trained on half A) picks which experts to run")
fk = ["env", "carrier", "m2", "m4", "if_kurt", "if_std"]
X = np.array([[r["feats"][k] for k in fk] for r in rows])
y = np.array([dense[i]["expert"] if dense[i]["expert"] != "null" else "nrz" for i in range(len(rows))])
clf = DecisionTreeClassifier(max_depth=4, random_state=0).fit(X[half], y[half])
P = clf.predict_proba(X); cls = list(clf.classes_)
shared = np.array([r["times"]["features"] + r["times"]["screen"] for r in rows])
et = {e: np.array([r["times"][e] for r in rows]) for e in ALL}
dense_t = shared + sum(et.values())
B = ~half
print(f"  dense: mean time {dense_t[B].mean()*1e3:.0f} ms/capture")
for kk in (1, 2):
    Ds, tm = [], []
    for i, r in enumerate(rows):
        order = [cls[j] for j in np.argsort(-P[i])]
        act = tuple(order[:kk])
        d = decide(r, act); f, l, ra = truth_ok(r, d)
        Ds.append(dict(d, fam_ok=f, label_ok=l, rate_ok=ra))
        tm.append(shared[i] + sum(et[e][i] for e in act))
    tm = np.array(tm)
    agree = np.mean([Ds[i]["label"] == dense[i]["label"] and Ds[i]["expert"] == dense[i]["expert"] for i in range(len(rows)) if B[i]]) * 100
    acc = np.mean([Ds[i]["label_ok"] for i in range(len(rows)) if B[i]]) * 100
    dacc = np.mean([dense[i]["label_ok"] for i in range(len(rows)) if B[i]]) * 100
    tt = report(Ds, "", show=False)
    print(f"  top-{kk}: mean time {tm[B].mean()*1e3:.0f} ms ({tm[B].mean()/dense_t[B].mean()*100:.0f}% of dense)  same answer as dense {agree:.1f}%  "
          f"raw label acc {acc:.1f}% (dense {dacc:.1f}%)  confidently wrong {tt['cw']}/{tt['n']}")
