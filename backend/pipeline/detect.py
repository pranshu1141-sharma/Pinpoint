"""Blind, offline energy detection. Frequency bands are candidates, not classes."""
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from time import perf_counter
import json
import numpy as np
from scipy import signal, ndimage
from .calibration import IsotonicCalibrator
from .ingest import Capture

REVIEW_THRESHOLD = .70
EPS = 1e-30

_DOCS_DIR = Path(__file__).resolve().parents[2] / "docs"
# Held-out-test ECE from backend/pipeline/calibrate.py's last run (see
# docs/confidence-calibration.json for the full reliability-diagram data and
# VALIDATION.md's Phase 3 report). Both calibrators are fit on a synthetic
# corpus only -- no real-file calibration exists yet, so this is a
# synthetic-validated correction, not a claim about real captures.
CALIBRATION_ECE = {"confidence": 0.0069, "confidence_evidence_based": 0.0594}


@lru_cache(maxsize=None)
def _load_calibrator(score_name):
    path = _DOCS_DIR / f"calibration-{score_name.replace('_', '-')}.json"
    if not path.exists():
        return None
    return IsotonicCalibrator.from_json(json.loads(path.read_text()))


def calibrate_confidence(score_name, raw_value):
    """Isotonic-calibrated value for a raw confidence score, or None with an
    explicit reason if no fitted calibrator is available (e.g. calibrate.py
    has not been run in this checkout)."""
    calibrator = _load_calibrator(score_name)
    if calibrator is None:
        return None, "uncalibrated (no fitted calibrator file present)"
    value = float(calibrator.predict(np.array([raw_value]))[0])
    ece = CALIBRATION_ECE.get(score_name)
    # An isotonic fit on one synthetic generator is not calibration across generators or on
    # real captures, so it is never presented as a calibrated probability.
    note = "uncalibrated across generators (isotonic fit on one synthetic corpus"
    return value, f"{note}, held-out ECE={ece:.4f} on that corpus)" if ece is not None else f"{note})"


def db(value):
    return 10*np.log10(np.maximum(value, EPS))


def runs(mask):
    edges = np.diff(np.r_[False, mask, False].astype(np.int8))
    return list(zip(np.flatnonzero(edges == 1), np.flatnonzero(edges == -1)))


def estimate_noise_floor(iq, sample_rate, nperseg=1024, real_audio=False):
    x = iq.real if real_audio else iq
    f, psd = signal.welch(x, fs=sample_rate, window="hann", nperseg=nperseg,
                          noverlap=nperseg//2, detrend=False, return_onesided=real_audio, scaling="density")
    if not real_audio:
        f, psd = np.fft.fftshift(f), np.fft.fftshift(psd)
    # Welch averages independent-looking windows to reduce PSD variance. The
    # median across frequency resists a minority of occupied signal bins.
    floor = float(np.median(psd))
    return f, psd, max(floor, EPS)


def compute_spectrogram(iq, sample_rate, nperseg=1024, real_audio=False):
    x = iq.real if real_audio else iq
    f, t, power = signal.spectrogram(x, fs=sample_rate, window="hann", nperseg=nperseg,
                                     noverlap=3*nperseg//4, detrend=False,
                                     return_onesided=real_audio, scaling="density", mode="psd")
    if not real_audio:
        f, power = np.fft.fftshift(f), np.fft.fftshift(power, axes=0)
    return f, t, power


def isolate_band(iq, fs, lower, upper, real_audio=False):
    if real_audio:
        nyquist = fs/2
        lower, upper = max(0, lower), min(nyquist, upper)
        if lower <= 0 and upper >= nyquist:
            return iq.real.copy()
        if lower <= 0:
            taps = signal.firwin(257, upper, fs=fs)
        elif upper >= nyquist:
            taps = signal.firwin(257, lower, pass_zero=False, fs=fs)
        else:
            taps = signal.firwin(257, [lower, upper], pass_zero=False, fs=fs)
        return signal.fftconvolve(iq.real, taps, mode="same")
    center = (lower+upper)/2
    mixed = iq * np.exp(-2j*np.pi*center*np.arange(len(iq))/fs)
    cutoff = min(fs*.49, max((upper-lower)/2, fs/1024))
    # Mixing before a linear-phase lowpass isolates positive or negative IQ
    # frequencies symmetrically. Centered convolution removes FIR group delay.
    taps = signal.firwin(257, cutoff, fs=fs)
    return signal.fftconvolve(mixed, taps, mode="same").astype(np.complex64)


def envelope_detect(isolated, fs, noise_power):
    # Smooth |x|² over 1 ms to suppress individual noise spikes while keeping
    # useful pulse edges. This sets an explicit lower pulse-resolution limit.
    window = min(len(isolated), max(3, int(fs*.001)))
    envelope = ndimage.uniform_filter1d(np.abs(isolated).astype(float)**2, size=window)
    # A full-file percentile would miss a single short burst occupying <5% of
    # the capture. The median of the strongest 1 ms estimates on-pulse power
    # while resisting a single numerical peak; it does not assume a duty cycle.
    high = float(np.median(np.partition(envelope, -window)[-window:]))
    low = float(np.percentile(envelope, 10))
    threshold = max(noise_power * 4, low + .45*(high-low))
    on = envelope > threshold
    # Fill sub-resolution gaps, but do not join separate pulses or invent PRI.
    for start, end in runs(~on):
        if start > 0 and end < len(on) and end-start < window:
            on[start:end] = True
    windows = [(int(a), int(b)) for a, b in runs(on) if b-a >= 2*window]
    duty = float(np.mean(on))
    contrast = high/max(low, noise_power, EPS)
    pulsed = bool(windows and contrast > 8 and 0 < duty < .75)
    if not pulsed:
        windows = []
    widths = [b-a for a, b in windows]
    pri = int(round(float(np.median(np.diff([a for a, _ in windows]))))) if len(windows) >= 2 else None
    return {"is_pulsed": pulsed, "pulse_width_samples": int(round(float(np.median(widths)))) if widths else None,
            "pri_samples": pri, "pulse_windows": [{"start_sample": a, "end_sample": b} for a, b in windows],
            "envelope": envelope, "envelope_threshold": threshold}


def power_cv_deviation(power_region):
    """abs(coefficient of variation - 1) of per-bin-mean-normalized raw power.

    A single complex-Gaussian-noise frequency bin's power is exponentially
    distributed with CV (std/mean) exactly 1; normalizing each frequency bin
    by its own time-mean before pooling removes a real signal's own passband
    roll-off (different mean power per bin) from contaminating this shape
    statistic. Deviation from 1 is independent evidence of non-noise content
    -- independent of the threshold-excess/occupancy confidence below, since
    it is a shape test, not an amplitude-threshold test.

    A raw 4th-moment spectral-kurtosis statistic (the roadmap's original
    suggestion) was tried first and rejected on measured evidence: it swung
    between roughly 1 and 16 on pure-noise regions at typical candidate
    sample sizes, because Welch's 75% frame overlap heavily correlates
    adjacent time samples -- a 4th-moment estimator-variance problem this
    2nd-moment ratio does not share. This statistic measured <=0.03 on every
    pure-noise region tested (n=4,000-7,500 samples) and >=0.08 on every real
    synthetic signal region tested (BPSK/QPSK/FM/pulsed).
    """
    row_mean = power_region.mean(axis=1, keepdims=True)
    normalized = power_region/np.maximum(row_mean, EPS)
    mean = float(np.mean(normalized))
    if mean <= 0:
        return 0.
    return float(abs(np.std(normalized)/mean-1.))


def adaptive_threshold_detect(power, noise_floor, margin_db=8, fixed_threshold_db=None):
    # A 3×3 power average reduces speckle false alarms without replacing the
    # time-resolved scan with full-capture averaging (short bursts still count).
    smooth = ndimage.uniform_filter(power.astype(float), size=(3, 3), mode="nearest")
    threshold = float(db(noise_floor)+margin_db) if fixed_threshold_db is None else fixed_threshold_db
    mask = db(smooth) > threshold
    # Require two adjacent time frames and two frequency bins of evidence. This
    # rejects isolated exponential-noise excursions; it limits minimum duration.
    mask = ndimage.binary_opening(mask, structure=np.ones((2, 2)))
    return mask, smooth, threshold


FRAGMENT_GAP_OF_WIDTH = 0.25     # merge co-timed neighbours separated by <= 1/4 of the wider band
SIDELOBE_GAP_OF_WIDTH = 1.0      # ... or by <= the stronger band's width when the other is >= 6 dB weaker
SIDELOBE_DB = 6.0
CO_TIMED = 0.8                   # share of the shorter band's active frames shared with the other
GAP_EXCESS_DB = 1.5              # ... or by any gap whose time-averaged power stays this far above noise


def merge_fragments(bands, mask, smooth, power=None):
    """Join frequency bands that are fragments of one signal; yield (fa, fb, occupied rows).

    Spectral nulls split one signal into a main lobe and sidelobes (sinc/filtered
    pulses), and at low SNR a noisy PSD splits a wide lobe into pieces; the WP0
    scoreboard saw 36% of single-signal captures come back as 2-8 detections.
    Two neighbours are joined only when they are co-timed (>= CO_TIMED of the
    shorter band's active frames overlap) and either the gap is small relative to
    the wider band, or the gap is at most the stronger band's width and the other
    band is >= SIDELOBE_DB weaker (sidelobe-like), or the gap's power averaged over
    the co-active frames stays >= GAP_EXCESS_DB above a noise reference (a wide
    lobe at negative SNR leaves sparse fragments, but signal remains between them;
    between separate signals the gap falls to the noise). The reference is the
    20th percentile of the time-averaged spectrum, bias-corrected for averaging.
    Evidence is later computed over the occupied rows only, not the bridged gap.
    """
    noise_ref = None
    if power is not None and power.shape[1] >= 2:
        from scipy.stats import gamma
        k = max(1.0, power.shape[1] / 2)          # 75%-overlap Hann frames: ~half independent
        q = gamma.ppf(0.2, k) / k
        noise_ref = float(np.percentile(power.mean(axis=1), 20) / q)
    items = []
    for fa, fb in bands:
        on = np.any(mask[fa:fb], axis=0)
        peak = float(db(np.max(smooth[fa:fb][:, on]))) if on.any() else -np.inf
        items.append(dict(fa=fa, fb=fb, rows=list(range(fa, fb)), on=on, peak=peak))
    changed = True
    while changed and len(items) > 1:
        changed = False
        for i in range(len(items) - 1):
            a, b = items[i], items[i + 1]
            gap = b["fa"] - a["fb"]
            shorter = min(a["on"].sum(), b["on"].sum())
            if shorter == 0 or (a["on"] & b["on"]).sum() < CO_TIMED * shorter:
                continue
            strong, weak = (a, b) if a["peak"] >= b["peak"] else (b, a)
            wide = max(a["fb"] - a["fa"], b["fb"] - b["fa"])
            gap_excess = -np.inf
            if noise_ref and gap > 0:
                frames = a["on"] | b["on"]
                gap_excess = float(db(power[a["fb"]:b["fa"]][:, frames].mean()) - db(noise_ref))
            if gap <= FRAGMENT_GAP_OF_WIDTH * wide or gap_excess >= GAP_EXCESS_DB or (
                    gap <= SIDELOBE_GAP_OF_WIDTH * (strong["fb"] - strong["fa"])
                    and strong["peak"] - weak["peak"] >= SIDELOBE_DB):
                items[i] = dict(fa=a["fa"], fb=b["fb"], rows=a["rows"] + b["rows"], on=a["on"] | b["on"],
                                peak=max(a["peak"], b["peak"]))
                del items[i + 1]
                changed = True
                break
    return [(it["fa"], it["fb"], it["rows"]) for it in items]


@dataclass
class DetectionResult:
    response: dict
    frequencies: np.ndarray
    times: np.ndarray
    power: np.ndarray
    envelopes: dict
    # Keep the computed density for downstream consumers; a dB round trip can
    # perturb phase-sensitive diagnostics despite unchanged measurement units.
    noise_floor: float | None = None


def analyze_capture(capture: Capture, margin_db=8, mode="adaptive", fixed_threshold_db=None):
    begin = perf_counter()
    if not np.isfinite(margin_db) or not 3 <= margin_db <= 30:
        raise ValueError("Adaptive margin must be between 3 and 30 dB.")
    if mode not in ("adaptive", "fixed_debug"):
        raise ValueError("Unknown detector mode.")
    if mode == "fixed_debug" and (fixed_threshold_db is None or not np.isfinite(fixed_threshold_db)):
        raise ValueError("Debug mode requires an explicit finite absolute PSD threshold.")
    x, fs = capture.iq, capture.sample_rate
    real = capture.metadata["source_kind"] == "audio"
    nfft = 1024
    pf, psd, floor = estimate_noise_floor(x, fs, nfft, real)
    f, t, power = compute_spectrogram(x, fs, nfft, real)
    mask, smooth, threshold = adaptive_threshold_detect(power, floor, margin_db,
                                                        fixed_threshold_db if mode == "fixed_debug" else None)
    # Join adjacent occupied bins into blind frequency bands. Repeated bursts in
    # the same band form one candidate, retaining every pulse window separately.
    active = np.any(mask, axis=1)
    for a, b in runs(~active):
        if a > 0 and b < len(active) and b-a <= 2:
            active[a:b] = True
    detections, envelopes = [], {}
    df = fs/nfft
    bands = []
    for fa, fb in runs(active):
        if fb-fa < 2:
            continue
        if np.count_nonzero(np.any(mask[fa:fb], axis=0)) < 3 or np.count_nonzero(mask[fa:fb]) < 12:
            continue
        bands.append((fa, fb))
    for fa, fb, rows in merge_fragments(bands, mask, smooth, power):
        time_on = np.any(mask[rows], axis=0)
        ti = np.flatnonzero(time_on)
        lower = max(0 if real else -fs/2, float(f[fa]-df/2))
        upper = min(fs/2, float(f[fb-1]+df/2))
        start = max(0, int(round(t[ti[0]]*fs-nfft/2)))
        end = min(len(x), int(round(t[ti[-1]]*fs+nfft/2)))
        isolated = isolate_band(x, fs, lower, upper, real)
        pulse = envelope_detect(isolated, fs, floor*(upper-lower))
        evidence = smooth[rows][:, ti]
        excess = float(db(np.percentile(evidence, 90))-threshold)
        occupancy = float(np.mean(mask[rows][:, ti]))
        # This is an explainable evidence score, NOT a calibrated probability or
        # a modulation classifier. Borderline energy gets an explicit review flag.
        confidence = float(np.clip(.48 + .38*(1-np.exp(-max(0, excess)/10)) + .12*occupancy, 0, .99))
        # A second, independent evidence channel (roadmap item 2): a shape
        # statistic on raw (unsmoothed) power, not an amplitude threshold.
        # Deliberately NOT collapsed into `confidence` above -- no calibration
        # dataset exists to justify combining the two into one number.
        deviation = power_cv_deviation(power[rows][:, ti])
        confidence_evidence_based = float(np.clip(.48+.5*(1-np.exp(-deviation/.2)), 0, .99))
        idx = len(detections)
        if pulse["is_pulsed"]:
            start = pulse["pulse_windows"][0]["start_sample"]
            end = pulse["pulse_windows"][-1]["end_sample"]
        confidence_calibrated, confidence_calibration_status = calibrate_confidence("confidence", confidence)
        evidence_calibrated, evidence_calibration_status = calibrate_confidence(
            "confidence_evidence_based", confidence_evidence_based)
        d = {"id": idx, "start_sample": start, "end_sample": end,
             "freq_lower_hz": lower, "freq_upper_hz": upper, "confidence": round(confidence, 4),
             "confidence_calibrated": round(confidence_calibrated, 4) if confidence_calibrated is not None else None,
             "confidence_calibration_status": confidence_calibration_status,
             "confidence_evidence_based": round(confidence_evidence_based, 4),
             "confidence_evidence_based_kind": "heuristic, not a calibrated probability",
             "confidence_evidence_based_calibrated": round(evidence_calibrated, 4) if evidence_calibrated is not None else None,
             "confidence_evidence_based_calibration_status": evidence_calibration_status,
             "power_cv_deviation": round(deviation, 4),
             "detection_method": "adaptive_threshold" if mode == "adaptive" else "fixed_threshold_debug",
             **{k: pulse[k] for k in ("is_pulsed", "pulse_width_samples", "pri_samples", "pulse_windows")},
             "needs_review": confidence < REVIEW_THRESHOLD, "threshold_excess_db": round(excess, 3)}
        detections.append(d)
        envelopes[idx] = {"values": pulse["envelope"], "threshold": pulse["envelope_threshold"]}
    elapsed = (perf_counter()-begin)*1000
    logs = [f"Loaded {len(x):,} samples at {fs:g} Hz from {capture.metadata['filename']}",
            f"Input interpretation: {capture.metadata['source_kind']} ({capture.metadata['wav_disambiguation']['result']})",
            f"Welch PSD: Hann window, {nfft} samples, 50% overlap; frequency-median noise estimate",
            f"Estimated noise floor: {float(db(floor)):.2f} dB re 1 sample-unit²/Hz (uncalibrated)",
            f"STFT: {power.shape[1]} time frames × {power.shape[0]} bins; {df:.3f} Hz resolution",
            f"{'Adaptive' if mode == 'adaptive' else 'FIXED DEBUG'} threshold: {threshold:.2f} dB; scan found {len(detections)} candidate bands",
            f"Envelope scan recovered {sum(d['is_pulsed'] for d in detections)} pulsed candidates",
            f"{sum(d['needs_review'] for d in detections)} candidates require review; confidence is a heuristic score",
            f"Detect complete in {elapsed:.1f} ms; no demodulation or classification performed"]
    response = {"detections": detections, "noise_floor_db": float(db(floor)), "threshold_db": threshold,
                "pipeline_log": logs, "metadata": capture.metadata, "elapsed_ms": elapsed,
                "settings": {"margin_db": margin_db, "mode": mode, "nfft": nfft,
                             "hop_samples": nfft//4, "review_threshold": REVIEW_THRESHOLD},
                "psd": [{"frequency_hz": float(a), "power_db": float(b)} for a, b in zip(pf, db(psd))]}
    return DetectionResult(response, f, t, power, envelopes, noise_floor=floor)
