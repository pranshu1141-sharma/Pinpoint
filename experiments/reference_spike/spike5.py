# THROWAWAY SPIKE v5 — not project code.
import numpy as np, sys, time, json
from scipy.signal import find_peaks, welch
from spike4 import (FS, N, n, t, TOL, gen, features, correct, nrz_expert, mdl_rrc,
                    fsk_expert, analog_expert, NAME)

NF = 16384
_f = np.arange(NF) * FS / NF
_band = (_f >= 10e3) & (_f <= 300e3)


def line_peaks(g, topk=3):
    g = g - g.mean()
    P = np.abs(np.fft.fft(g * np.hanning(len(g)), NF)) ** 2 + 1e-30
    Pb, fb = P[_band], _f[_band]
    pk, _ = find_peaks(Pb)
    out = []
    for i in pk[np.argsort(-Pb[pk])[:topk]]:
        a, b, c = np.log(Pb[i - 1]), np.log(Pb[i]), np.log(Pb[i + 1])
        den = a - 2 * b + c
        out.append(fb[i] + (0.5 * (a - c) / den if den else 0.0) * FS / NF)
    return out


def dedupe(rates, tol=0.02):
    out = []
    for r in rates:
        if 10e3 <= r <= 300e3 and all(abs(r - q) / q >= tol for q in out):
            out.append(r)
    return out


def psk_props(xc, scales=(1, 2, 4, 8)):
    """symbol transitions = big jumps in the complex signal; compare samples a
    smoothing-width apart so smoothing lowers noise without shrinking the jump"""
    out = []
    for w in scales:
        sm = np.convolve(xc, np.ones(w) / w, mode="same") if w > 1 else xc
        out += line_peaks(np.abs(sm[w:] - sm[:-w]) ** 2)
    return dedupe(out)


def fsk_props(x, scales=(2, 4, 8, 16)):
    """same idea on the instantaneous-frequency track (FM discriminator)"""
    dd = x[1:] * np.conj(x[:-1])
    out = []
    for w in scales:
        f = np.angle(np.convolve(dd, np.ones(w) / w, mode="same"))
        out += line_peaks(np.abs(f[w:] - f[:-w]) ** 2)
    return dedupe(out)


def fsk_quick(x, R):
    """cheap FSK check: do per-symbol frequencies split into two tight clusters?"""
    dd = np.append(x[1:] * np.conj(x[:-1]), 0)
    L = FS / R
    best = -1.0
    for tau in np.arange(6) / 6:
        u = n / L + tau
        k = np.floor(u).astype(int); k -= k.min(); nk = k.max() + 1
        frac = u - np.floor(u)
        w = ((frac * L > 1) & ((1 - frac) * L > 1)).astype(float)
        mf = np.angle(np.bincount(k, dd.real * w, nk) + 1j * np.bincount(k, dd.imag * w, nk))[1:-1]
        thr = np.median(mf); a, b = mf[mf > thr], mf[mf <= thr]
        if len(a) > 2 and len(b) > 2:
            best = max(best, (a.mean() - b.mean()) ** 2 / (a.var() + b.var() + 1e-9))
    return best


def analyze(x):
    T = {}
    t0 = time.perf_counter(); feats = features(x); T["features"] = time.perf_counter() - t0

    t0 = time.perf_counter()
    xc = correct(x)
    pp = psk_props(xc)
    pp = pp + dedupe([pp[0] / 2, pp[0] * 2]) if pp else pp
    q = [nrz_expert(xc, r, alph=(4,), offsets=(0.0,))[0] for r in pp]
    top = [pp[i] for i in np.argsort(q)[:3]]
    # needle refinement of every finalist (the fit is needle-sharp in rate)
    ref = []
    for r0 in top:
        rr = r0 * (1 + np.array([-0.006, -0.003, 0.0, 0.003, 0.006]))
        qq = [nrz_expert(xc, v, alph=(4,), offsets=(0.0,))[0] for v in rr]
        ref.append(rr[int(np.argmin(qq))])
    top = dedupe(ref, tol=0.01)
    T["screen_psk"] = time.perf_counter() - t0

    t0 = time.perf_counter()
    fp = fsk_props(x)
    fq = [fsk_quick(x, r) for r in fp]
    ftop = [fp[i] for i in np.argsort(fq)[::-1][:3]]
    T["screen_fsk"] = time.perf_counter() - t0

    hyps = []
    t0 = time.perf_counter()
    for r in top:
        sc, M, res = nrz_expert(xc, r); hyps.append(["nrz", r, sc, NAME[M], res])
    T["nrz"] = time.perf_counter() - t0
    t0 = time.perf_counter()
    for r in top:
        sc, M, res = mdl_rrc(xc, r); hyps.append(["rrc", r, sc, NAME[M], res])
    T["rrc"] = time.perf_counter() - t0
    t0 = time.perf_counter()
    for r in ftop:
        sc, lab, res = fsk_expert(x, r); hyps.append(["fsk", r, sc, lab, res])
    T["fsk"] = time.perf_counter() - t0
    t0 = time.perf_counter()
    sc, lab, res = analog_expert(x); hyps.append(["analog", None, sc, lab, res])
    T["analog"] = time.perf_counter() - t0

    p = float(np.mean(np.abs(x) ** 2))
    hyps.append(["null", None, float(np.log(p)), "none", p])
    _, P = welch(xc, fs=FS, nperseg=256, return_onesided=False)
    T["screen"] = T.pop("screen_psk") + T.pop("screen_fsk")
    return dict(hyps=hyps, feats=feats, times=T, noise_var=float(np.percentile(P, 20) * FS), ptot=p)


if __name__ == "__main__":
    ntr, seed = int(sys.argv[1]), int(sys.argv[2])
    rng = np.random.default_rng(seed)
    kinds = ["PSK", "QAM16", "FSK2", "AM", "FM", "8PSK", "noise"]
    probs = [0.35, 0.12, 0.13, 0.10, 0.10, 0.08, 0.12]
    rows, out, t0 = [], f"rows5_{seed}.json", time.time()
    for i in range(ntr):
        kind = rng.choice(kinds, p=probs)
        x, info = gen(rng, kind)
        r = analyze(x); r.update(info); rows.append(r)
        if (i + 1) % 50 == 0:
            json.dump(rows, open(out, "w"), default=float)
            print(i + 1, round(time.time() - t0, 1), flush=True)
    json.dump(rows, open(out, "w"), default=float)
    print("done", len(rows), round(time.time() - t0, 1))
