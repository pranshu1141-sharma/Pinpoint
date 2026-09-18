"""Synthetic, labeled corpus for calibrating Detect's confidence scores.

Explicitly synthetic: labels come from generator ground truth, not measured
real-world outcomes. See VALIDATION.md's Phase 3 report for why real-file
calibration was not attempted in this pass (no ground-truth-labeled real
corpus exists in this project).

Each capture varies modulation, SNR, and noise color (white vs. pink/1-over-f
-- real receiver noise is rarely perfectly white, and Detect's Welch
noise-floor estimate implicitly assumes a locally flat spectrum). A clean
signal is generated first via synth_gen.make_signal at high SNR, then
degraded with independently generated colored noise at a controlled power so
noise color and target SNR are decoupled from make_signal's own (always
white) internal noise model.
"""
import numpy as np

from .detect import analyze_capture
from .ingest import Capture
from .synth_gen import FS, make_signal

KINDS = ("bpsk", "qpsk", "fm", "ask", "fsk", "pulsed")
SNRS_DB = (-5, 0, 5, 10, 15, 20)
NOISE_COLORS = ("white", "pink")
SEEDS_PER_COMBO = 3
HIGH_SNR_DB = 40.0


def _colored_noise(n, color, rng):
    white = rng.standard_normal(n) + 1j * rng.standard_normal(n)
    if color == "white":
        return white
    freqs = np.fft.fftfreq(n)
    shaping = 1.0 / np.sqrt(np.maximum(np.abs(freqs), 1.0 / n))
    colored = np.fft.ifft(np.fft.fft(white) * shaping)
    colored = colored / np.std(colored)
    return colored


def make_labeled_capture(kind, snr_db, color, seed, frequency=8000.0):
    """A capture at `snr_db` (relative to `color`-colored noise, not
    make_signal's own always-white noise) with ground truth for TP/FP
    labeling. Returns (Capture, truth_signals list -- empty for pure noise).
    """
    rng = np.random.default_rng(seed)
    if kind == "noise":
        iq = _colored_noise(int(FS * 2), color, rng).astype(np.complex64)
        return Capture(iq, FS, {"source_kind": "iq", "filename": "calibration-corpus",
                                "wav_disambiguation": {"result": "declared_iq"}}), []
    clean, truth = make_signal(kind, HIGH_SNR_DB, seed=seed, frequency=frequency)
    # make_signal's own (negligible at 40 dB) noise plus the signal; treat the
    # whole thing as "signal" and add independently colored noise on top,
    # scaled so the requested SNR holds against that added noise specifically.
    signal_power = float(np.mean(np.abs(clean) ** 2))
    noise = _colored_noise(len(clean), color, rng)
    noise = noise * np.sqrt(signal_power / (10 ** (snr_db / 10)) / np.mean(np.abs(noise) ** 2))
    iq = (clean + noise).astype(np.complex64)
    for t in truth:
        t["snr_db"] = snr_db
    return Capture(iq, FS, {"source_kind": "iq", "filename": "calibration-corpus",
                            "wav_disambiguation": {"result": "declared_iq"}}), truth


def _matches_truth(detection, truth_signals):
    for t in truth_signals:
        center = (t["freq_lower_hz"] + t["freq_upper_hz"]) / 2
        if detection["freq_lower_hz"] < center < detection["freq_upper_hz"]:
            return True
    return False


def build_corpus(kinds=KINDS, snrs=SNRS_DB, colors=NOISE_COLORS, seeds_per_combo=SEEDS_PER_COMBO,
                  include_pure_noise=True, seed_offset=0):
    """Run Detect over the labeled corpus; return a list of per-candidate
    dicts: {confidence, confidence_evidence_based, label, kind, snr_db, color}.
    label is 1 if the candidate overlaps a real generated signal, else 0.
    """
    rows = []
    for kind in kinds:
        for snr in snrs:
            for color in colors:
                for seed in range(seed_offset, seed_offset + seeds_per_combo):
                    capture, truth = make_labeled_capture(kind, snr, color, seed * 97 + 1)
                    detections = analyze_capture(capture).response["detections"]
                    for d in detections:
                        rows.append({
                            "confidence": d["confidence"],
                            "confidence_evidence_based": d["confidence_evidence_based"],
                            "label": int(_matches_truth(d, truth)),
                            "kind": kind, "snr_db": snr, "color": color,
                        })
    if include_pure_noise:
        for color in colors:
            for seed in range(seed_offset, seed_offset + 4 * seeds_per_combo):
                capture, truth = make_labeled_capture("noise", 0, color, 5000 + seed * 13)
                detections = analyze_capture(capture).response["detections"]
                for d in detections:
                    rows.append({
                        "confidence": d["confidence"],
                        "confidence_evidence_based": d["confidence_evidence_based"],
                        "label": int(_matches_truth(d, truth)),
                        "kind": "noise", "snr_db": None, "color": color,
                    })
    return rows
