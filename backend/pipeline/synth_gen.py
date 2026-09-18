"""Reproducible RF fixtures; ground truth is never passed to the detector."""
from pathlib import Path
import argparse
import json
import numpy as np
from scipy import signal
from scipy.io import wavfile

FS = 48000


def make_signal(kind, snr_db=10, duration=2.0, seed=47, frequency=8000):
    rng = np.random.default_rng(seed)
    n = int(FS * duration)
    t = np.arange(n) / FS
    noise = (rng.standard_normal(n) + 1j * rng.standard_normal(n)) / np.sqrt(2)
    truth = []
    if kind == "noise":
        return noise.astype(np.complex64), truth
    if kind in ("bpsk", "qpsk", "8psk"):
        order = {"bpsk": 2, "qpsk": 4, "8psk": 8}[kind]
        symbols = np.exp(2j * np.pi * rng.integers(0, order, n // 96 + 1) / order)
        # Smooth symbol transitions to bound occupied bandwidth, instead of testing
        # an unrealistically infinite-bandwidth rectangular symbol waveform.
        base = signal.fftconvolve(np.repeat(symbols, 96)[:n], signal.firwin(193, 900, fs=FS), mode="same")
        bandwidth = 1800
    elif kind == "ask":
        # Unipolar 2-level (OOK-style, non-zero low level) amplitude keying:
        # real-valued, varying-envelope by construction. Two levels give more
        # measured envelope-variation margin above envelope_detect's 0.3
        # varying-envelope threshold than more, closer-spaced levels would,
        # while their contrast ratio still stays under its pulse-vs-continuous
        # cutoff, so this is one continuous varying-envelope band, not a
        # misread gated burst.
        levels = np.array([.4, 1.])
        symbols = levels[rng.integers(0, len(levels), n // 96 + 1)]
        base = signal.fftconvolve(np.repeat(symbols, 96)[:n], signal.firwin(193, 900, fs=FS), mode="same")
        bandwidth = 1800
    elif kind == "qam":
        # 16-QAM: independent 4-level in-phase/quadrature symbols, jointly
        # varying amplitude and phase (unlike PSK's constant-modulus symbols).
        # Levels are spread just past envelope_detect's varying-envelope
        # threshold while staying inside its pulse-vs-continuous contrast
        # ratio, so this is detected as one continuous varying-envelope band
        # rather than misread as a gated burst.
        levels = np.array([-1., -.45, .45, 1.])
        i_sym = levels[rng.integers(0, len(levels), n // 96 + 1)]
        q_sym = levels[rng.integers(0, len(levels), n // 96 + 1)]
        symbols = i_sym + 1j * q_sym
        base = signal.fftconvolve(np.repeat(symbols, 96)[:n], signal.firwin(193, 900, fs=FS), mode="same")
        bandwidth = 1800
    elif kind == "fsk":
        # 4-FSK: discrete tone switching per symbol with continuous phase
        # (integrated frequency), constant envelope by construction.
        deviations = np.array([-600., -200., 200., 600.])
        chosen = deviations[rng.integers(0, len(deviations), n // 96 + 1)]
        freq_seq = np.repeat(chosen, 96)[:n]
        base = np.exp(1j * 2 * np.pi * np.cumsum(freq_seq) / FS)
        bandwidth = 2 * float(np.max(np.abs(deviations))) + FS / 96
    elif kind == "fm":
        # Integrating a sinusoidal frequency deviation gives phase index Δf/fm;
        # an extra 2π here would incorrectly multiply the requested deviation.
        base = np.exp(1j * 700 / 230 * np.sin(2 * np.pi * 230 * t))
        bandwidth = 2200
    elif kind == "pulsed":
        gate = (np.arange(n) >= 4800) & ((np.arange(n) - 4800) % 12000 < 2400)
        base = gate.astype(float)
        bandwidth = 500
    else:
        raise ValueError(f"Unknown generator kind: {kind}")
    # SNR denotes full-band signal power / complex-noise power; for pulses it is
    # the on-pulse SNR, so changing duty cycle does not change pulse amplitude.
    norm = np.mean(np.abs(base[base != 0]) ** 2)
    base = base / np.sqrt(norm) * 10 ** (snr_db / 20)
    iq = base * np.exp(2j * np.pi * frequency * t) + noise
    truth.append(dict(kind=kind, snr_db=snr_db, freq_lower_hz=frequency-bandwidth/2,
                      freq_upper_hz=frequency+bandwidth/2, start_sample=0, end_sample=n,
                      symbol_rate_hz=FS/96 if kind in ("bpsk", "qpsk", "8psk", "ask", "qam", "fsk") else None,
                      pulse_width_samples=2400 if kind == "pulsed" else None,
                      pri_samples=12000 if kind == "pulsed" else None))
    return iq.astype(np.complex64), truth


def save_capture(path, iq, truth):
    path.parent.mkdir(parents=True, exist_ok=True)
    iq.astype("<c8").tofile(path.with_suffix(".sigmf-data"))
    meta = {"global": {"core:datatype": "cf32_le", "core:sample_rate": FS,
                       "core:version": "1.2.0", "core:description": "Synthetic Detect validation capture"},
            "captures": [{"core:sample_start": 0, "core:frequency": 100000000}], "annotations": []}
    path.with_suffix(".sigmf-meta").write_text(json.dumps(meta, indent=2))
    path.with_suffix(".truth.json").write_text(json.dumps({"sample_rate": FS, "signals": truth}, indent=2))


def generate_suite(directory):
    directory = Path(directory)
    for kind in ("bpsk", "qpsk", "8psk", "ask", "qam", "fsk", "fm"):
        for snr in (20, 10, 0, -5):
            x, truth = make_signal(kind, snr)
            save_capture(directory / f"{kind}_{snr}db", x, truth)
    for kind in ("pulsed", "noise"):
        x, truth = make_signal(kind, 10)
        save_capture(directory / kind, x, truth)
    # A real file with three independent synthetic sources makes the default
    # dashboard useful without inventing any frontend detection data.
    bpsk, a = make_signal("bpsk", 10, 4, frequency=-11000)
    fm, b = make_signal("fm", 3, 4, seed=48, frequency=4000)
    pulse, c = make_signal("pulsed", 14, 4, seed=49, frequency=14000)
    demo = (bpsk + fm + pulse).astype(np.complex64)
    save_capture(directory / "demo", demo, a+b+c)
    rate = 16000
    t = np.arange(rate * 2) / rate
    audio = .3*np.sin(2*np.pi*1200*t) + np.random.default_rng(3).normal(0, .02, t.size)
    wavfile.write(directory / "audio_demo.wav", rate, audio.astype(np.float32))
    return directory


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="backend/data/generated")
    args = parser.parse_args()
    print(f"Generated captures and ground truth in {generate_suite(args.output)}")
