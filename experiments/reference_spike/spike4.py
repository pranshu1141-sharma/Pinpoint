# THROWAWAY SPIKE v4 — not project code.
# Laws applied: simplify (L6), coarse-to-fine architecture (L4), compute budget (L3),
# expert library + gate data for sparse activation (L1), no randomness inside analyze (L2).
import numpy as np, sys, time, json
from spike3 import (FS, N, n, t, TOL, rrc, peak_rate, freq_est, correct, E1, E2,
                    _quantize, mdl_rrc, ALPH)

# ---------------------------------------------------------------- signals
def gen(rng, kind):
    snr = rng.uniform(-6, 14)
    w = (rng.standard_normal(N) + 1j * rng.standard_normal(N)) * np.sqrt(10 ** (-snr / 10) / 2)
    if kind == "noise":
        return w, dict(kind=kind, snr=None, Rs=None, fam="none", label="none", shaping="-")
    foff, ph0 = rng.uniform(-1e5, 1e5), rng.uniform(0, 2 * np.pi)
    if kind in ("AM", "FM"):
        f1, f2 = rng.uniform(300, 3000), rng.uniform(3000, 8000)
        msg = 0.6 * np.cos(2 * np.pi * f1 * t) + 0.4 * np.cos(2 * np.pi * f2 * t + 1)
        if kind == "AM":
            s = 1 + rng.uniform(0.3, 0.8) * msg
        else:
            dev = rng.uniform(5e3, 30e3)
            s = np.exp(1j * 2 * np.pi * np.cumsum(dev * msg) / FS)
        s = s / np.sqrt(np.mean(np.abs(s) ** 2))
        return s * np.exp(1j * (2 * np.pi * foff * t + ph0)) + w, \
            dict(kind=kind, snr=snr, Rs=None, fam=kind, label=kind, shaping="-")
    Rs = rng.uniform(25e3, 160e3)
    K = int(N * Rs / FS) + 40
    phi = rng.uniform(0, 1)
    if kind == "FSK2":
        h = rng.choice([0.5, 1.0])
        b = rng.choice([-1.0, 1.0], K)[np.floor(t * Rs + phi).astype(int) + 10]
        s = np.exp(1j * 2 * np.pi * np.cumsum(b * h * Rs / 2) / FS)
        return s * np.exp(1j * (2 * np.pi * foff * t + ph0)) + w, \
            dict(kind=kind, snr=snr, Rs=Rs, fam="FSK", label="FSK2", shaping="NRZ")
    if kind == "PSK":
        lab = rng.choice(["BPSK", "QPSK"])
    elif kind == "QAM16":
        lab = "QAM16"
    else:
        lab = "8PSK"  # held out: NOT in the checker's library
    if lab == "BPSK":
        sy = rng.choice([-1.0, 1.0], K).astype(complex)
    elif lab == "QPSK":
        sy = (rng.choice([-1.0, 1.0], K) + 1j * rng.choice([-1.0, 1.0], K)) / np.sqrt(2)
    elif lab == "QAM16":
        lv = np.array([-3, -1, 1, 3.0])
        sy = rng.choice(lv, K) + 1j * rng.choice(lv, K)
    else:
        sy = np.exp(1j * 2 * np.pi * rng.integers(0, 8, K) / 8)
    shaping = "RRC" if rng.random() < 0.3 else "NRZ"
    tt = t * Rs + phi
    if shaping == "NRZ":
        s = sy[np.floor(tt).astype(int) + 10]
    else:
        k0 = np.floor(tt).astype(int)
        s = sum(sy[k0 + d + 10] * rrc(tt - (k0 + d)) for d in range(-8, 9))
    s = s / np.sqrt(np.mean(np.abs(s) ** 2))
    fam = "PSK" if lab in ("BPSK", "QPSK") else lab
    return s * np.exp(1j * (2 * np.pi * foff * t + ph0)) + w, \
        dict(kind=kind, snr=snr, Rs=Rs, fam=fam, label=lab, shaping=shaping)


# ------------------------------------------------------------ cheap features (gate input)
def features(x):
    a = np.abs(x)
    X = np.abs(np.fft.fft(x)) ** 2 + 1e-30
    X2 = np.abs(np.fft.fft(x ** 2)) + 1e-30
    X4 = np.abs(np.fft.fft(x ** 4)) + 1e-30
    fi = np.angle(x[1:] * np.conj(x[:-1]))
    fi = fi - np.median(fi)
    c = fi - fi.mean()
    return dict(env=float(a.std() / a.mean()),
                carrier=float(10 * np.log10(X.max() / np.median(X))),
                m2=float(10 * np.log10(X2.max() / np.median(X2))),
                m4=float(10 * np.log10(X4.max() / np.median(X4))),
                if_kurt=float(np.mean(c ** 4) / (np.mean(c ** 2) ** 2 + 1e-12)),
                if_std=float(fi.std()))


# ------------------------------------------------------------ experts (all deterministic)
def _timing(xc, R):
    nl = np.abs(np.diff(xc)) ** 2
    c = np.sum(nl * np.exp(-2j * np.pi * R * (np.arange(len(nl)) + 1.0) / FS))
    return (np.angle(c) / (2 * np.pi)) % 1.0


def nrz_expert(xc, R, alph=(2, 4, 16), offsets=(-1.0, -0.5, 0.0, 0.5, 1.0)):
    L = FS / R
    tau0 = _timing(xc, R)

    def at(tau):
        k = np.floor(n / L + tau).astype(int); k -= k.min()
        msk = (k > 0) & (k < k.max()); kk = k[msk] - 1
        cnt = np.bincount(kk).astype(float); cnt[cnt == 0] = 1
        m = (np.bincount(kk, xc[msk].real) + 1j * np.bincount(kk, xc[msk].imag)) / cnt
        Neff, K = msk.sum(), len(m)
        b = (np.inf, None, np.nan)
        for M in alph:
            rec = _quantize(m, M)
            res = np.mean(np.abs(xc[msk] - rec[kk]) ** 2) + 1e-30
            sc = np.log(res) + (K * np.log(M) + np.ceil(K / 16) * np.log(Neff)) / Neff
            if sc < b[0]:
                b = (sc, M, res)
        return b
    if offsets == (0.0,):
        return at(tau0)
    return fine_search(at, tau0, L)


NAME = {2: "BPSK", 4: "QPSK", 16: "QAM16"}


def fine_search(fn, tau0, L, full=False):
    """coarse-to-fine timing search: around the estimate (+-1, +-0.5 samples),
    optionally also 6 phases across the whole symbol, then 1/4 and 1/8 sample steps"""
    seen = {}
    def ev(tau):
        key = round(tau % 1.0, 5)
        if key not in seen:
            seen[key] = fn(key)
        return seen[key]
    taus = [tau0 + o / L for o in (-1.0, -0.5, 0.0, 0.5, 1.0)]
    if full:
        taus += [j / 6 for j in range(6)]
    best = min(taus, key=lambda u: ev(u)[0])
    for step in (0.25, 0.125):
        best = min((best - step / L, best, best + step / L), key=lambda u: ev(u)[0])
    return ev(best)


def fsk_expert(x, R, blk_syms=8):
    """Rebuild as 2-tone continuous-phase FSK at rate R; 1 bit per symbol."""
    L = FS / R
    fi = np.angle(x[1:] * np.conj(x[:-1])) * FS / (2 * np.pi)
    f0 = np.median(fi)
    xs = x * np.exp(-2j * np.pi * f0 * t)
    fi = np.append(fi - f0, 0.0)
    dd = np.append(xs[1:] * np.conj(xs[:-1]), 0.0)
    nl = np.abs(np.diff(fi))
    c = np.sum(nl * np.exp(-2j * np.pi * R * (np.arange(len(nl)) + 1.0) / FS))
    tau0 = (np.angle(c) / (2 * np.pi)) % 1.0
    def at(tau, blk_syms=blk_syms):
        u = n / L + tau
        k = np.floor(u).astype(int); k -= k.min()
        frac = u - np.floor(u)
        interior = (frac * L > 1.0) & ((1 - frac) * L > 1.0)
        msk = (k > 0) & (k < k.max())
        nk = k.max() + 1
        # Kay-style: sum complex phase-difference products, take the angle once
        w8 = interior.astype(float)
        sd = np.bincount(k, dd.real * w8, nk) + 1j * np.bincount(k, dd.imag * w8, nk)
        mf = np.angle(sd) * FS / (2 * np.pi)
        inner = mf[1:-1]
        if (inner > 0).sum() == 0 or (inner <= 0).sum() == 0:
            return (np.inf, None, np.nan)
        dec = mf > 0
        for _ in range(4):  # 2-means with Kay tone estimates
            fa = np.angle(sd[1:-1][dec[1:-1]].sum()) * FS / (2 * np.pi) if dec[1:-1].any() else 0.0
            fb = np.angle(sd[1:-1][~dec[1:-1]].sum()) * FS / (2 * np.pi) if (~dec[1:-1]).any() else 0.0
            dec = np.abs(mf - fa) < np.abs(mf - fb)
        # two ways to decide each bit; the checker keeps whichever explains the data better
        za = xs * np.exp(-2j * np.pi * fa * t)
        zb = xs * np.exp(-2j * np.pi * fb * t)
        ea = np.abs(np.bincount(k, za.real, nk) + 1j * np.bincount(k, za.imag, nk))
        eb = np.abs(np.bincount(k, zb.real, nk) + 1j * np.bincount(k, zb.imag, nk))
        blk = k // blk_syms
        nb = blk.max() + 1
        res = np.inf
        for dec in (np.abs(mf - fa) < np.abs(mf - fb), ea >= eb):
            tone = np.where(dec, fa, fb)[k]
            ph = np.exp(1j * 2 * np.pi * np.cumsum(tone) / FS)
            z = xs * np.conj(ph)
            cz = (np.bincount(blk, z.real, nb) + 1j * np.bincount(blk, z.imag, nb)) / np.maximum(np.bincount(blk, minlength=nb), 1)
            res = min(res, np.mean(np.abs(xs[msk] - (cz[blk] * ph)[msk]) ** 2) + 1e-30)
        Neff, K = msk.sum(), k.max() - 1
        sc = np.log(res) + (K * np.log(2) + 1 + (nb + 2) * np.log(Neff)) / Neff
        return (sc, "FSK2", res)
    # find timing with short (2-symbol) phase blocks: wide, smooth basin
    seen = {}
    def ev(tau):
        key = round(tau % 1.0, 5)
        if key not in seen:
            seen[key] = at(key, 2)[0]
        return seen[key]
    taus = [tau0 + o / L for o in (-1.0, -0.5, 0.0, 0.5, 1.0)] + [j / 12 for j in range(12)]
    bt = min(taus, key=ev)
    for step in (0.25, 0.125, 0.0625):
        bt = min((bt - step / L, bt, bt + step / L), key=ev)
    # score the final hypothesis with the full model
    return at(bt % 1.0)


def _lowpass(v, B):
    V = np.fft.fft(v)
    f = np.fft.fftfreq(len(v), 1 / FS)
    V[np.abs(f) > B] = 0
    return np.fft.ifft(V)


def analog_expert(x):
    """AM: real envelope on a carrier. FM: smooth phase. Bandwidth B chosen by MDL."""
    X = np.abs(np.fft.fft(x)) ** 2
    fc = np.fft.fftfreq(N, 1 / FS)[np.argmax(X)]
    xd = x * np.exp(-2j * np.pi * fc * t)
    best = (np.inf, None, np.nan)
    for B in (3e3, 6e3, 12e3, 25e3, 50e3):
        npar = 2 * B * N / FS
        # AM
        ph = np.angle(np.mean(xd))
        r = _lowpass(np.real(xd * np.exp(-1j * ph)), B).real
        res = np.mean(np.abs(xd - r * np.exp(1j * ph)) ** 2) + 1e-30
        sc = np.log(res) + (npar + 1) * 0.5 * np.log(N) / N
        if sc < best[0]:
            best = (sc, "AM", res)
        # FM
        dphi = np.angle(xd[1:] * np.conj(xd[:-1]))
        ps = np.concatenate([[0], np.cumsum(_lowpass(dphi, B).real)])
        A = np.mean(np.abs(xd))
        c = np.angle(np.mean(xd * np.exp(-1j * ps)))
        res = np.mean(np.abs(xd - A * np.exp(1j * (ps + c))) ** 2) + 1e-30
        sc = np.log(res) + (npar + 2) * 0.5 * np.log(N) / N
        if sc < best[0]:
            best = (sc, "FM", res)
    return best


def E4(x):  # FSK proposer: symbol-rate line in instantaneous-frequency changes
    fi = np.angle(x[1:] * np.conj(x[:-1]))
    return peak_rate(np.abs(np.diff(fi)))


GRID = np.geomspace(10e3, 300e3, 40)


# ------------------------------------------------------------ pipeline
def analyze(x):
    T = {}
    t0 = time.perf_counter()
    feats = features(x)
    T["features"] = time.perf_counter() - t0

    # --- coarse screen (cheap QPSK-only NRZ check, one timing) -> top rates
    t0 = time.perf_counter()
    xc = correct(x)
    props = [E1(x)[0], E2(x)[0]]
    cands = np.concatenate([GRID, props])
    q = np.array([nrz_expert(xc, r, alph=(4,), offsets=(0.0,))[0] for r in cands])
    order = np.argsort(q)
    tops = []
    for i in order:
        if all(abs(cands[i] - r) / r >= TOL for r in tops):
            tops.append(cands[i])
        if len(tops) == 3:
            break
    refined = []
    for r in tops:
        rr = r * (1 + np.linspace(-0.04, 0.04, 9))
        qq = [nrz_expert(xc, v, alph=(4,), offsets=(0.0,))[0] for v in rr]
        refined.append(rr[int(np.argmin(qq))])
    rates = refined + [refined[0] / 2, refined[0] * 2]
    rates = [r for r in rates if 10e3 <= r <= 300e3]
    T["screen"] = time.perf_counter() - t0

    hyps = []  # (expert, rate, score, label, residual)
    t0 = time.perf_counter()
    for r in rates:
        sc, M, res = nrz_expert(xc, r)
        hyps.append(("nrz", r, sc, NAME[M], res))
    T["nrz"] = time.perf_counter() - t0

    t0 = time.perf_counter()
    for r in rates[:3]:
        sc, M, res = mdl_rrc(xc, r)
        hyps.append(("rrc", r, sc, NAME[M], res))
    T["rrc"] = time.perf_counter() - t0

    t0 = time.perf_counter()
    fr = E4(x)[0]
    frates = list(rates[:3]) + [fr * (1 + d) for d in np.linspace(-0.04, 0.04, 5)]
    for r in frates:
        if 10e3 <= r <= 300e3:
            sc, lab, res = fsk_expert(x, r)
            hyps.append(("fsk", r, sc, lab, res))
    T["fsk"] = time.perf_counter() - t0

    t0 = time.perf_counter()
    sc, lab, res = analog_expert(x)
    hyps.append(("analog", None, sc, lab, res))
    T["analog"] = time.perf_counter() - t0

    p = float(np.mean(np.abs(x) ** 2))
    hyps.append(("null", None, float(np.log(p)), "none", p))
    from scipy.signal import welch
    _, P = welch(xc, fs=FS, nperseg=256, return_onesided=False)
    return dict(hyps=[list(h) for h in hyps], feats=feats, times=T,
                noise_var=float(np.percentile(P, 20) * FS), ptot=p)


if __name__ == "__main__":
    ntr, seed = int(sys.argv[1]), int(sys.argv[2])
    rng = np.random.default_rng(seed)
    kinds = ["PSK", "QAM16", "FSK2", "AM", "FM", "8PSK", "noise"]
    probs = [0.35, 0.12, 0.13, 0.10, 0.10, 0.08, 0.12]
    rows, out, t0 = [], f"rows4_{seed}.json", time.time()
    for i in range(ntr):
        kind = rng.choice(kinds, p=probs)
        x, info = gen(rng, kind)
        r = analyze(x); r.update(info)
        rows.append(r)
        if (i + 1) % 20 == 0:
            json.dump(rows, open(out, "w"), default=float)
            print(i + 1, round(time.time() - t0, 1), flush=True)
    json.dump(rows, open(out, "w"), default=float)
    print("done", len(rows), round(time.time() - t0, 1))
