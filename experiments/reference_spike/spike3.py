# THROWAWAY SPIKE — not project code.
# Question: do DeepSeek-style ideas (group voting, generator+verifier,
# meta-verification, synthetic-twin bootstrap) improve symbol-rate accuracy
# and give a confidence score that actually predicts correctness?
import numpy as np, sys, time, json
from scipy.signal import find_peaks

FS = 1e6
N = 4096
n = np.arange(N)
t = n / FS
TOL = 0.05  # "correct" = within 5% of true symbol rate


# ---------------------------------------------------------------- signals
def rrc(tau, a=0.35):
    """Root-raised-cosine pulse, tau in symbol periods."""
    h = np.empty_like(tau)
    z = np.isclose(tau, 0)
    s = np.isclose(np.abs(tau), 1 / (4 * a))
    o = ~(z | s)
    h[z] = 1 - a + 4 * a / np.pi
    h[s] = (a / np.sqrt(2)) * ((1 + 2 / np.pi) * np.sin(np.pi / (4 * a))
                               + (1 - 2 / np.pi) * np.cos(np.pi / (4 * a)))
    x = tau[o]
    h[o] = (np.sin(np.pi * x * (1 - a)) + 4 * a * x * np.cos(np.pi * x * (1 + a))) / \
           (np.pi * x * (1 - (4 * a * x) ** 2))
    return h


def gen(rng, kind, snr=None, Rs=None, mod=None, shaping=None):
    if snr is None:
        snr = rng.uniform(-6, 14)
    sig2 = 10 ** (-snr / 10)
    w = (rng.standard_normal(N) + 1j * rng.standard_normal(N)) * np.sqrt(sig2 / 2)
    if kind == "noise":
        return w.astype(np.complex128), dict(kind="noise", snr=None, Rs=None)
    foff = rng.uniform(-1e5, 1e5)
    ph0 = rng.uniform(0, 2 * np.pi)
    if kind == "AM":
        fm1, fm2 = rng.uniform(300, 3000), rng.uniform(3000, 8000)
        s = 1 + 0.4 * np.cos(2 * np.pi * fm1 * t) + 0.3 * np.cos(2 * np.pi * fm2 * t + 1)
        s = s / np.sqrt(np.mean(np.abs(s) ** 2))
        x = s * np.exp(1j * (2 * np.pi * foff * t + ph0)) + w
        return x, dict(kind="AM", snr=snr, Rs=None, mod="AM", shaping="-")
    if kind in ("QAM16", "FSK2"):
        Rs = rng.uniform(25e3, 160e3)
        K = int(N * Rs / FS) + 40
        idx = np.floor(t * Rs + rng.uniform(0, 1)).astype(int) + 10
        if kind == "QAM16":
            lv = np.array([-3, -1, 1, 3.0])
            sy = rng.choice(lv, K) + 1j * rng.choice(lv, K)
            s = sy[idx]
        else:  # continuous-phase 2-FSK, tone spacing = Rs (h = 1)
            b = rng.choice([-1.0, 1.0], K)[idx]
            s = np.exp(1j * 2 * np.pi * np.cumsum(b * Rs / 2) / FS)
        s = s / np.sqrt(np.mean(np.abs(s) ** 2))
        x = s * np.exp(1j * (2 * np.pi * foff * t + ph0)) + w
        return x, dict(kind=kind, snr=snr, Rs=Rs, mod=kind, shaping="NRZ")
    Rs = Rs if Rs is not None else rng.uniform(25e3, 160e3)
    mod = mod or rng.choice(["BPSK", "QPSK"])
    shaping = shaping or ("RRC" if rng.random() < 0.3 else "NRZ")
    K = int(N * Rs / FS) + 40
    if mod == "BPSK":
        sy = rng.choice([-1.0, 1.0], K)
    else:
        sy = (rng.choice([-1.0, 1.0], K) + 1j * rng.choice([-1.0, 1.0], K)) / np.sqrt(2)
    phi = rng.uniform(0, 1)
    tt = t * Rs + phi
    if shaping == "NRZ":
        s = sy[np.floor(tt).astype(int) + 10]
    else:
        k0 = np.floor(tt).astype(int)
        s = np.zeros(N, complex)
        for d in range(-8, 9):
            s += sy[k0 + d + 10] * rrc(tt - (k0 + d))
    s = s / np.sqrt(np.mean(np.abs(s) ** 2))
    foff = rng.uniform(-1e5, 1e5)
    x = s * np.exp(1j * (2 * np.pi * foff * t + rng.uniform(0, 2 * np.pi))) + w
    return x, dict(kind="signal", snr=snr, Rs=Rs, mod=mod, shaping=shaping)


# ------------------------------------------------------------ estimators
NFFT = 16384
_f = np.arange(NFFT) * FS / NFFT


def peak_rate(nl, lo=10e3, hi=250e3):
    """Project Stage-5 rule: lowest spectral peak within 3 dB of the max."""
    nl = nl - nl.mean()
    P = np.abs(np.fft.fft(nl * np.hanning(len(nl)), NFFT)) ** 2 + 1e-30
    band = (_f >= lo) & (_f <= hi)
    Pb, fb = P[band], _f[band]
    pk, _ = find_peaks(Pb)
    if len(pk) == 0:
        return fb[np.argmax(Pb)], 0.0
    mx = Pb[pk].max()
    i = pk[Pb[pk] >= mx / 2].min()
    if 0 < i < len(Pb) - 1:
        a, b, c = np.log(Pb[i - 1]), np.log(Pb[i]), np.log(Pb[i + 1])
        den = a - 2 * b + c
        d = 0.5 * (a - c) / den if den != 0 else 0.0
    else:
        d = 0.0
    df = FS / NFFT
    return fb[i] + d * df, 10 * np.log10(Pb[i] / np.median(Pb))


def freq_est(x):
    """Mth-power (M=4) carrier estimate — project Stage 3.5."""
    y = x ** 4
    P = np.abs(np.fft.fft(y * np.hanning(len(y)), NFFT))
    k = np.argmax(P)
    if 0 < k < NFFT - 1:
        a, b, c = np.log(P[k - 1] + 1e-30), np.log(P[k] + 1e-30), np.log(P[(k + 1) % NFFT] + 1e-30)
        den = a - 2 * b + c
        d = 0.5 * (a - c) / den if den != 0 else 0.0
    else:
        d = 0.0
    f = (k + d) * FS / NFFT
    if f > FS / 2:
        f -= FS
    return f / 4


def correct(x):
    tt = np.arange(len(x)) / FS
    return x * np.exp(-2j * np.pi * freq_est(x) * tt)


def E1(x):  # derivative-energy of frequency-corrected signal (Stage 5, phase-invariant)
    return peak_rate(np.abs(np.diff(correct(x))) ** 2)


def E2(x):  # delay-and-multiply phase-difference (no frequency correction needed)
    d = x[1:] * np.conj(x[:-1])
    ang = np.angle(d * np.conj(np.mean(d)))
    return peak_rate(np.abs(ang))


def E3(x):  # envelope power (helps on pulse-shaped signals)
    return peak_rate(np.abs(x) ** 2)


ESTS = [E1, E2, E3]


# ------------------------------------------------------ 1. group voting
def votes(x):
    segs = [x] + [x[i * N // 4:(i + 1) * N // 4] for i in range(4)]
    return np.array([E(s)[0] for E in ESTS for s in segs])


def cluster(v):
    sup = np.array([np.sum(np.abs(v - vi) / vi < TOL) for vi in v])
    order = np.lexsort((v, -sup))  # max support, tie -> lowest rate
    best = v[order[0]]
    members = v[np.abs(v - best) / best < TOL]
    return np.median(members), sup[order[0]] / len(v), sup, order


# ---------------------------------------------- 2. verifier (analysis by synthesis)
QP = np.array([1+1j, 1-1j, -1+1j, -1-1j]) / np.sqrt(2)
BP = np.array([1.0 + 0j, -1.0 + 0j])
_lv = np.array([-3, -1, 1, 3.0])
Q16 = (_lv[:, None] + 1j * _lv[None, :]).ravel() / np.sqrt(10)
ALPH = {2: BP, 4: QP, 16: Q16}


def _quantize(m, M):
    """Snap per-symbol values to BPSK / QPSK / 16-QAM, tracking a slowly
    drifting phase and amplitude in blocks of 16 symbols."""
    K = len(m)
    B = -(-K // 16)
    mp = np.zeros(B * 16, complex); mp[:K] = m
    mb = mp.reshape(B, 16)
    valid = np.zeros(B * 16, bool); valid[:K] = True; valid = valid.reshape(B, 16)
    pts = ALPH[M]
    A = (np.abs(mb) * valid).sum(1) / valid.sum(1) / np.mean(np.abs(pts)) + 1e-12
    if M == 2:
        th = np.angle((mb ** 2).sum(1)) / 2
    else:
        th = np.angle(-(mb ** 4).sum(1)) / 4
    u = mb * np.exp(-1j * th)[:, None] / A[:, None]
    q = pts[np.argmin(np.abs(u[..., None] - pts), axis=-1)]
    return ((A * np.exp(1j * th))[:, None] * q).reshape(-1)[:K]


def mdl(xc, R, return_mod=False):
    """Analysis-by-synthesis check: rebuild the capture as BPSK/QPSK symbols
    at rate R, measure the leftover, charge log2(M) bits per symbol (MDL).
    Lower = this rate (and alphabet) explains the data better."""
    L = FS / R
    best, bmod, bres = np.inf, None, np.nan
    nn = np.arange(len(xc))
    # timing from the phase of the symbol-rate line in the transition energy
    # (Oerder & Meyr-style), then a few fine offsets around it
    nl = np.abs(np.diff(xc)) ** 2
    c = np.sum(nl * np.exp(-2j * np.pi * R * (np.arange(len(nl)) + 1.0) / FS))
    tau0 = (np.angle(c) / (2 * np.pi)) % 1.0
    for tau in (tau0 + np.array([-1.0, -0.5, 0.0, 0.5, 1.0]) / L) % 1.0:
        k = np.floor(nn / L + tau).astype(int)
        k -= k.min()
        msk = (k > 0) & (k < k.max())
        kk = k[msk] - 1
        cnt = np.bincount(kk).astype(float)
        cnt[cnt == 0] = 1
        m = (np.bincount(kk, xc[msk].real) + 1j * np.bincount(kk, xc[msk].imag)) / cnt
        Neff = msk.sum()
        K = len(m)
        for M in (2, 4, 16):
            rec = _quantize(m, M)
            res = np.mean(np.abs(xc[msk] - rec[kk]) ** 2) + 1e-30
            sc = np.log(res) + (K * np.log(M) + 2 * np.ceil(K / 16) * np.log(Neff) / 2) / Neff
            if sc < best:
                best, bmod, bres = sc, M, res
    rb, rm, rr = mdl_rrc(xc, R)
    if rb < best:
        best, bmod, bres = rb, rm, rr
    return (best, bmod, bres) if return_mod else best


def mdl_rrc(xc, R, span=6):
    """Same check with a root-raised-cosine pulse model: matched-filter the
    symbols, snap to the alphabet, rebuild with the RRC pulse, measure leftover."""
    L = FS / R
    nn = np.arange(len(xc))
    best, bmod, bres = np.inf, None, np.nan
    for phi in np.arange(8) / 8:
        u = nn / L - phi
        k0 = np.floor(u).astype(int)
        ks, ps = [], []
        for d in range(-span, span + 1):
            k = k0 + d
            ks.append(k); ps.append(rrc(u - k))
        kmin = min(k.min() for k in ks)
        ks = [k - kmin for k in ks]
        Kt = max(k.max() for k in ks) + 1
        num = sum(np.bincount(k, xc.real * p, Kt) + 1j * np.bincount(k, xc.imag * p, Kt) for k, p in zip(ks, ps))
        den = sum(np.bincount(k, p * p, Kt) for k, p in zip(ks, ps)) + 1e-12
        a = num / den
        inner = slice(span + 1, Kt - span - 1)
        edge = int(np.ceil((span + 1) * L))
        msk = np.zeros(len(xc), bool); msk[edge:len(xc) - edge] = True
        Neff = msk.sum()
        if Neff < 256:
            continue
        for M in (2, 4, 16):
            aq = a.copy()
            aq[inner] = _quantize(a[inner], M)
            rec = sum(aq[k] * p for k, p in zip(ks, ps))
            res = np.mean(np.abs(xc[msk] - rec[msk]) ** 2) + 1e-30
            K = inner.stop - inner.start
            sc = np.log(res) + (K * np.log(M) + 2 * np.ceil(K / 16) * np.log(Neff) / 2 + np.log(Neff)) / Neff
            if sc < best:
                best, bmod, bres = sc, M, res
    return best, bmod, bres


GRID = np.geomspace(10e3, 300e3, 64)


def candidate_rates(v, a0, a1):
    _, _, sup, order = cluster(v)
    reps = []
    for i in order:
        if all(abs(v[i] - r) / r >= TOL for r in reps):
            reps.append(v[i])
        if len(reps) == 3:
            break
    base = set(reps + [a0])
    for mlt in (1 / 3, 1 / 2, 2, 3):
        base.add(a1 * mlt)
    out = list(GRID)
    for r in base:
        for d in np.linspace(-0.03, 0.03, 7):
            rr = r * (1 + d)
            if 10e3 <= rr <= 300e3:
                out.append(rr)
    return np.array(out)


def verify(xc, cands):
    s = np.array([mdl(xc, r) for r in cands])
    i = np.argmin(s)
    win = cands[i]
    other = np.abs(cands - win) / win >= TOL
    margin = (s[other].min() - s[i]) if other.any() else 0.0
    _, M, res = mdl(xc, win, return_mod=True)
    return win, margin, s, M, res


# ----------------------------------------------- 3. meta-verifier (null copies)
def surrogate(x, rng):
    """Same power spectrum, random phases: keeps the 'look' of the signal,
    destroys the symbol structure. A verifier that is equally sure on this
    copy was fooled by the spectrum, not by real symbols."""
    X = np.fft.fft(x)
    return np.fft.ifft(np.abs(X) * np.exp(1j * rng.uniform(0, 2 * np.pi, len(X))))


def m2m4_snr(xc):
    M2 = np.mean(np.abs(xc) ** 2)
    M4 = np.mean(np.abs(xc) ** 4)
    S = np.sqrt(max(2 * M2 ** 2 - M4, 1e-12))
    Nn = max(M2 - S, 1e-12)
    return float(np.clip(10 * np.log10(S / Nn), -10, 30))


# ------------------------------------------------------------ full pipeline
def analyze(x, rng, do_meta=False, do_boot=False, n_twin=6):
    a0, c0 = E1(x)
    v = votes(x)
    a1, c1, _, _ = cluster(v)
    xc = correct(x)
    cands = candidate_rates(v, a0, a1)
    a2, c2, s, Mhat, res = verify(xc, cands)
    out = dict(a0=a0, c0=c0, a1=a1, c1=c1, a2=a2, c2=c2, mod_hat={2: "BPSK", 4: "QPSK", 16: "QAM16"}[Mhat])
    from scipy.signal import welch
    _, P = welch(xc, fs=FS, nperseg=256, return_onesided=False)
    noise_var = np.percentile(P, 20) * FS
    out["fit_db"] = float(10 * np.log10(res / noise_var))
    ptot = float(np.mean(np.abs(xc) ** 2))
    out["res"], out["noise_var"], out["ptot"] = float(res), float(noise_var), ptot
    # share of the SIGNAL power the rebuild failed to explain
    out["unexplained"] = float(max(res - noise_var, 0) / max(ptot - noise_var, 1e-12))
    # GRPO-style group-relative advantage of the winner
    out["c2_adv"] = float((s.mean() - s.min()) / (s.std() + 1e-12))
    if do_meta:
        # score the SAME candidate group on 3 structure-free copies
        nm = []
        for _ in range(3):
            xs = correct(surrogate(x, rng))
            _, mg, _, _, _ = verify(xs, cands)
            nm.append(mg)
        out["c2_null"] = float(np.max(nm))
        out["c2_meta"] = float(c2 - np.max(nm))
    else:
        out["c2_meta"] = np.nan
    snr_est = m2m4_snr(xc)
    out["snr_est"] = snr_est
    if do_boot:
        # synthetic twins: simulate our own answer at our own estimated SNR,
        # rerun the pipeline, count how often it gets the twin right
        ok = 0
        for _ in range(n_twin):
            xt, _ = gen(rng, "signal", snr=snr_est, Rs=a2, shaping="NRZ")
            r = analyze(xt, rng, do_meta=False, do_boot=False)
            ok += abs(r["a2"] - a2) / a2 < TOL
        out["c3"] = ok / n_twin
    return out


if __name__ == "__main__":
    ntr = int(sys.argv[1]); seed = int(sys.argv[2])
    rng = np.random.default_rng(seed)
    kinds = ["signal", "QAM16", "FSK2", "AM", "noise"]
    probs = [0.60, 0.12, 0.12, 0.06, 0.10]
    rows = []
    out = f"rows3_{seed}.json"
    t0 = time.time()
    for i in range(ntr):
        kind = rng.choice(kinds, p=probs)
        x, info = gen(rng, kind)
        r = analyze(x, rng)
        r.update(info)
        for a in ("a0", "a1", "a2"):
            r["ok_" + a] = bool(info["Rs"] is not None and abs(r[a] - info["Rs"]) / info["Rs"] < TOL)
        rows.append(r)
        if (i + 1) % 20 == 0:
            json.dump(rows, open(out, "w"), default=str)
            print(i + 1, round(time.time() - t0, 1), flush=True)
    json.dump(rows, open(out, "w"), default=str)
    print("done", len(rows), round(time.time() - t0, 1))
