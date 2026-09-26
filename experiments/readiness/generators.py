"""The scoreboard's signal generators and their ground truth (never shown to a system).

G1: the spike corpus (experiments/estimate_spike/signals.py), test seed 7.
G2: the shipped fixture family, widened (synth_wide.py).
G3: real recordings listed in real_manifest.json (WP7).

Truth fields: label, family, snr_db, rate, fc, bw3 (expected -3 dB width of the
PSD for linear modulations, else None), band (nominal occupied lo/hi, for
matching detections), digital, linear, in_library, out_of_library.
"""
from dataclasses import dataclass
import numpy as np

from experiments.estimate_spike.signals import KIND_PROBS, KINDS, REF_FS, generate
from . import synth_wide
from .config import G1_TEST_N, G1_TEST_SEED, IN_LIBRARY, OUT_OF_LIBRARY

NRZ_BW3 = 0.8859       # sinc^2 half-power full width, x Rs
RRC_BW3 = 1.0          # |RRC|^2 = raised cosine: half power at +-Rs/2 for any roll-off

G2_KINDS_DIGITAL = ("bpsk", "qpsk", "8psk", "qam", "fsk", "ask")
G2_LABEL = {"bpsk": "BPSK", "qpsk": "QPSK", "8psk": "8PSK", "qam": "QAM16", "fsk": "FSK4",
            "ask": "ASK2", "fm": "FM", "noise": "noise"}
G2_CARRIERS = (0, 3000, 8000, 15000)
G2_SPS = (12, 24, 48, 96)
G2_SNRS = (5, 10, 20)
G2_SEEDS_PER_CELL = 3
G2_N = 24000                                     # 0.5 s at 48 kHz (see ledger ruling)
G2_TEST_SEED_BASE = 100_000
G2_CALIBRATION_SEEDS = range(200_000, 210_000)   # reserved; never used by the test grid


@dataclass
class Capture:
    gen: str
    id: str
    x: np.ndarray
    fs: float
    clean: np.ndarray
    truth: dict


def _family(label: str) -> str:
    return {"BPSK": "PSK", "QPSK": "PSK", "8PSK": "PSK"}.get(label, label.rstrip("0123456789") or label)


def _truth(label, snr, rate, fc, bw3, band_width, linear):
    return dict(label=label, family=_family(label), snr_db=snr, rate=rate, fc=fc, bw3=bw3,
                band=(fc - band_width / 2, fc + band_width / 2) if band_width else None,
                digital=rate is not None, linear=linear, in_library=label in IN_LIBRARY,
                out_of_library=label in OUT_OF_LIBRARY)


# ---------------------------------------------------------------- G1

def _replay_g1(state, kind, fs, n):
    """Re-draw generate()'s first random numbers to recover the noise and hidden draws."""
    rng = np.random.default_rng()
    rng.bit_generator.state = state
    scale = fs / REF_FS
    snr = rng.uniform(-6, 14)
    w = (rng.standard_normal(n) + 1j * rng.standard_normal(n)) * np.sqrt(10 ** (-snr / 10) / 2)
    if kind == "noise":
        return w, {}
    foff = rng.uniform(-1e5, 1e5) * scale
    rng.uniform(0, 2 * np.pi)
    hidden = dict(foff=foff)
    if kind in ("AM", "FM"):
        hidden["f1"], hidden["f2"] = rng.uniform(300, 3000) * scale, rng.uniform(3000, 8000) * scale
        if kind == "FM":
            hidden["dev"] = rng.uniform(5e3, 30e3) * scale
    return w, hidden


def g1_captures(count: int = G1_TEST_N, seed: int = G1_TEST_SEED, fs: float = REF_FS, n: int = 4096):
    rng = np.random.default_rng(seed)
    for i in range(count):
        kind = str(rng.choice(KINDS, p=KIND_PROBS))
        state = rng.bit_generator.state
        x, t = generate(rng, kind, fs, n)
        w, hid = _replay_g1(state, kind, fs, n)
        clean = x - w
        if kind == "noise":
            truth = _truth("noise", None, None, None, None, None, False)
            clean = np.zeros(n, complex)
        else:
            label, rate, fc = t["label"], t["Rs"], hid["foff"]
            linear = label in ("BPSK", "QPSK", "QAM16", "8PSK")
            if linear:
                bw3 = (NRZ_BW3 if t["shaping"] == "NRZ" else RRC_BW3) * rate
                width = 2 * rate if t["shaping"] == "NRZ" else 1.35 * rate
            elif label == "FSK2":
                bw3, width = None, (t["h"] + 1) * rate
            elif label == "AM":
                bw3, width = None, 2 * hid["f2"]
            else:
                bw3, width = None, 2 * (hid["dev"] + hid["f2"])
            truth = _truth(label, float(t["snr"]), rate, fc, bw3, width, linear)
            truth["shaping"] = t["shaping"]
        yield Capture("G1", f"G1-{seed}-{i:04d}", x, fs, clean, truth)


# ---------------------------------------------------------------- G2

def g2_specs() -> list[dict]:
    specs, s = [], G2_TEST_SEED_BASE
    for kind in G2_KINDS_DIGITAL:
        for fc in G2_CARRIERS:
            for sps in G2_SPS:
                for snr in G2_SNRS:
                    for _ in range(G2_SEEDS_PER_CELL):
                        specs.append(dict(kind=kind, carrier_hz=fc, sps=sps, snr_db=snr, seed=s))
                        s += 1
    for kind in ("fm", "noise"):
        for fc in G2_CARRIERS:
            for snr in G2_SNRS:
                for _ in range(G2_SEEDS_PER_CELL):
                    specs.append(dict(kind=kind, carrier_hz=fc, sps=96, snr_db=snr, seed=s))
                    s += 1
    return specs


def pulse_bw3(sps: int) -> float:
    """-3 dB full width (Hz) of |P(f)|^2 for the smoothed NRZ pulse (i.i.d. zero-mean symbols)."""
    p = np.convolve(np.ones(sps), synth_wide.smoothing_taps(sps))
    nf = 1 << 18
    spec = np.abs(np.fft.rfft(p, nf)) ** 2
    k = int(np.argmax(spec < spec[0] / 2))
    return 2 * k * synth_wide.FS / nf


def g2_capture(kind: str, snr_db: float, carrier_hz: float, sps: int, seed: int, n: int = G2_N) -> Capture:
    x, clean = synth_wide.make_signal(kind, snr_db, carrier_hz, sps, seed, n)
    fs = synth_wide.FS
    label = G2_LABEL[kind]
    rate = fs / sps if kind in G2_KINDS_DIGITAL else None
    linear = kind in synth_wide.LINEAR
    if kind == "noise":
        truth = _truth("noise", None, None, None, None, None, False)
    else:
        width = {"fsk": 3.4 * rate if rate else None, "fm": 2200.0}.get(kind, 3.6 * rate if rate else None)
        truth = _truth(label, float(snr_db), rate, float(carrier_hz), pulse_bw3(sps) if linear else None,
                       width, linear)
    return Capture("G2", f"G2-{kind}-{carrier_hz}-{sps}-{snr_db}-{seed}", x, fs, clean, truth)


def g2_captures():
    for s in g2_specs():
        yield g2_capture(**s)
