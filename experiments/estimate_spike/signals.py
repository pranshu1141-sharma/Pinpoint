"""Seeded synthetic captures for evaluating the Estimate spike (never used by product code).

Draws from the generator in exactly the same order as the prototype's
spike4.gen, so a given seed reproduces the prototype's captures bit-for-bit
at fs = 1 MS/s, N = 4096. Rates and deviations scale with fs.
"""
import numpy as np

from backend.experimental.estimate_spike.dsp import rrc_pulse

KINDS = ("PSK", "QAM16", "FSK2", "AM", "FM", "8PSK", "noise")
KIND_PROBS = (0.35, 0.12, 0.13, 0.10, 0.10, 0.08, 0.12)
REF_FS = 1e6


def generate(rng: np.random.Generator, kind: str, fs: float = REF_FS, n: int = 4096,
             snr_db: float | None = None, rate: float | None = None, label: str | None = None,
             shaping: str | None = None, h: float | None = None) -> tuple[np.ndarray, dict]:
    """One capture of `kind`. Unit signal power plus complex AWGN at `snr_db` (default U(-6, 14))."""
    scale = fs / REF_FS
    t = np.arange(n) / fs
    snr = rng.uniform(-6, 14) if snr_db is None else snr_db
    w = (rng.standard_normal(n) + 1j * rng.standard_normal(n)) * np.sqrt(10 ** (-snr / 10) / 2)
    if kind == "noise":
        return w, dict(kind=kind, snr=None, Rs=None, fam="none", label="none", shaping="-")
    foff, ph0 = rng.uniform(-1e5, 1e5) * scale, rng.uniform(0, 2 * np.pi)
    carrier = np.exp(1j * (2 * np.pi * foff * t + ph0))
    if kind in ("AM", "FM"):
        f1, f2 = rng.uniform(300, 3000) * scale, rng.uniform(3000, 8000) * scale
        msg = 0.6 * np.cos(2 * np.pi * f1 * t) + 0.4 * np.cos(2 * np.pi * f2 * t + 1)
        if kind == "AM":
            s = 1 + rng.uniform(0.3, 0.8) * msg
        else:
            s = np.exp(1j * 2 * np.pi * np.cumsum(rng.uniform(5e3, 30e3) * scale * msg) / fs)
        s = s / np.sqrt(np.mean(np.abs(s) ** 2))
        return s * carrier + w, dict(kind=kind, snr=snr, Rs=None, fam=kind, label=kind, shaping="-")
    draw_rate = rng.uniform(25e3, 160e3) * scale
    rate = draw_rate if rate is None else rate
    k = int(n * rate / fs) + 40
    phi = rng.uniform(0, 1)
    if kind == "FSK2":
        hh = rng.choice([0.5, 1.0])
        hh = hh if h is None else h
        b = rng.choice([-1.0, 1.0], k)[np.floor(t * rate + phi).astype(int) + 10]
        s = np.exp(1j * 2 * np.pi * np.cumsum(b * hh * rate / 2) / fs)
        return s * carrier + w, dict(kind=kind, snr=snr, Rs=rate, fam="FSK", label="FSK2",
                                     shaping="NRZ", h=float(hh))
    if kind == "PSK":
        lab = rng.choice(["BPSK", "QPSK"])
    elif kind == "QAM16":
        lab = "QAM16"
    else:
        lab = "8PSK"  # held out: not in the checker's library
    lab = str(lab) if label is None else label
    if lab == "BPSK":
        sy = rng.choice([-1.0, 1.0], k).astype(complex)
    elif lab == "QPSK":
        sy = (rng.choice([-1.0, 1.0], k) + 1j * rng.choice([-1.0, 1.0], k)) / np.sqrt(2)
    elif lab == "QAM16":
        lv = np.array([-3, -1, 1, 3.0])
        sy = rng.choice(lv, k) + 1j * rng.choice(lv, k)
    else:
        sy = np.exp(1j * 2 * np.pi * rng.integers(0, 8, k) / 8)
    shp = "RRC" if rng.random() < 0.3 else "NRZ"
    shp = shp if shaping is None else shaping
    tt = t * rate + phi
    if shp == "NRZ":
        s = sy[np.floor(tt).astype(int) + 10]
    else:
        k0 = np.floor(tt).astype(int)
        s = sum(sy[k0 + d + 10] * rrc_pulse(tt - (k0 + d), 0.35) for d in range(-8, 9))
    s = s / np.sqrt(np.mean(np.abs(s) ** 2))
    fam = "PSK" if lab in ("BPSK", "QPSK") else lab
    return s * carrier + w, dict(kind=kind, snr=snr, Rs=rate, fam=fam, label=lab, shaping=shp)


def corpus(n_captures: int, seed: int, fs: float = REF_FS, n: int = 4096):
    """Yield (x, truth) with the prototype's kind mix and draw order."""
    rng = np.random.default_rng(seed)
    for _ in range(n_captures):
        kind = str(rng.choice(KINDS, p=KIND_PROBS))
        yield generate(rng, kind, fs, n)
