"""Phase 1 acceptance tests for Gardner symbol-timing recovery.

Validates backend/pipeline/timing_recovery.py against the stated acceptance
criterion: on synthetic BPSK/QPSK at SNR >= 10 dB with a known symbol clock
offset, the recovered symbol timing must be within 1% of a symbol period
across 20 seeds. A separate section validates lock-indicator behavior on
real captures where classify.py has already estimated a symbol rate with a
confirmed PSK/ASK label.
"""
from pathlib import Path

import numpy as np
import pytest
from scipy import signal as scipy_signal

from backend.pipeline import classify
from backend.pipeline.ingest import load_capture
from backend.pipeline.timing_recovery import gardner_timing_recovery

SPS = 8
DATA_DIR = Path(__file__).resolve().parents[1] / "data" / "real"


def _rrc_taps(beta, span_symbols, sps_over):
    """Root-raised-cosine pulse, sps_over samples/symbol. Standard closed-form
    definition (e.g. Proakis, "Digital Communications"); used only to build
    this module's own synthetic test fixtures, independent of synth_gen.py.
    """
    n = span_symbols * sps_over
    t = np.arange(-n, n + 1) / sps_over
    h = np.zeros_like(t)
    for i, ti in enumerate(t):
        if abs(ti) < 1e-8:
            h[i] = 1.0 - beta + 4 * beta / np.pi
        elif beta > 0 and abs(abs(ti) - 1 / (4 * beta)) < 1e-8:
            h[i] = (beta / np.sqrt(2)) * (
                (1 + 2 / np.pi) * np.sin(np.pi / (4 * beta)) + (1 - 2 / np.pi) * np.cos(np.pi / (4 * beta)))
        else:
            h[i] = (np.sin(np.pi * ti * (1 - beta)) + 4 * beta * ti * np.cos(np.pi * ti * (1 + beta))) / (
                np.pi * ti * (1 - (4 * beta * ti) ** 2))
    return h / np.sqrt(np.sum(h ** 2))


def make_timing_fixture(kind, snr_db, seed, delay_frac, n_symbols=40000, sps=SPS, beta=0.35, oversample=16):
    """A pulse-shaped baseband PSK segment with a known, injected fractional
    sample-timing offset (`delay_frac`, in symbols), for validating timing
    recovery in isolation from Detect/Estimate/classify's own SNR-gated
    pipeline (backend/pipeline/synth_gen.py's fixtures are not used here:
    they are shaped for spectral-occupancy realism, not for injecting a
    precisely known sub-sample timing offset).
    """
    rng = np.random.default_rng(seed)
    order = {"bpsk": 2, "qpsk": 4}[kind]
    symbols = np.exp(2j * np.pi * rng.integers(0, order, n_symbols) / order)
    sps_over = sps * oversample
    taps = _rrc_taps(beta, 6, sps_over)
    upsampled = np.zeros(n_symbols * sps_over, dtype=complex)
    upsampled[::sps_over] = symbols
    shaped = scipy_signal.fftconvolve(upsampled, taps, mode="full")
    group_delay = (len(taps) - 1) // 2
    start = group_delay + int(round(delay_frac * sps_over))
    x = shaped[start:start + (n_symbols - 8) * sps_over:oversample]
    noise_power = np.mean(np.abs(x) ** 2) / (10 ** (snr_db / 10))
    noise = (rng.standard_normal(len(x)) + 1j * rng.standard_normal(len(x))) * np.sqrt(noise_power / 2)
    return (x + noise).astype(np.complex128)


@pytest.mark.parametrize("kind", ["bpsk", "qpsk"])
@pytest.mark.parametrize("snr_db", [10, 20])
def test_timing_offset_within_one_percent_across_20_seeds(kind, snr_db):
    """Acceptance criterion: recovered timing within 1% of a symbol period,
    across 20 seeds, at SNR >= 10 dB. The injected delay convention makes the
    ground truth for the recovered offset equal to -delay_frac (see
    make_timing_fixture / classify.corrected_segment's sign convention is not
    involved here -- this validates the algorithm on its own inputs)."""
    errors = []
    for seed in range(20):
        rng = np.random.default_rng(9000 + seed)
        delay = rng.uniform(-0.2, 0.2)
        x = make_timing_fixture(kind, snr_db, seed, delay)
        out = gardner_timing_recovery(x, SPS)
        assert out["lock_indicator"], f"seed {seed} failed to lock"
        truth = -delay
        error = abs(((out["timing_offset_hat"] - truth + 0.5) % 1.0) - 0.5)
        errors.append(error)
    errors = np.array(errors)
    assert np.all(errors <= 0.01), errors


def test_timing_recovery_reports_required_fields():
    x = make_timing_fixture("qpsk", 15, 0, 0.1)
    out = gardner_timing_recovery(x, SPS)
    assert set(out) == {"symbols", "timing_offset_hat", "timing_offset_trace",
                         "lock_indicator", "residual_error"}
    assert out["timing_offset_hat"] is not None
    assert -0.5 <= out["timing_offset_hat"] < 0.5
    assert len(out["symbols"]) == len(out["timing_offset_trace"]) == len(out["residual_error"])


def test_rejects_undersampled_input():
    with pytest.raises(ValueError):
        gardner_timing_recovery(np.zeros(100, dtype=complex), sps=2)


def _real_fixture(name):
    data_path = DATA_DIR / f"{name}.sigmf-data"
    meta_path = DATA_DIR / f"{name}.sigmf-meta"
    if not data_path.exists():
        pytest.skip(f"real capture {name} not present in {DATA_DIR}")
    sigmf_meta = meta_path.read_bytes() if meta_path.exists() else None
    return load_capture(data_path.name, data_path.read_bytes(), sigmf_meta=sigmf_meta)


@pytest.mark.parametrize("name", ["sigid3_full", "sigid3_trimmed", "grcon23_qam"])
def test_lock_indicator_agrees_with_confirmed_symbol_rate_on_real_captures(name):
    """Where Detect/Estimate/classify already produced a confirmed PSK/ASK
    label and symbol_rate_hz on a real file, timing recovery's own lock
    indicator should agree that the segment is trackable. Where no confirmed
    rate exists (label unresolved, e.g. this project's own "qam" flag), no
    claim is made either way -- this is an agreement check, not a claim that
    timing recovery resolves cases classify.py already declined."""
    from backend.pipeline.detect import analyze_capture
    c = _real_fixture(name)
    detections = analyze_capture(c).response["detections"]
    checked = 0
    for d in detections:
        out = classify.analyze_candidate(c, d)
        if out.get("symbol_rate_hz") is None or out.get("fine_modulation_label") not in classify.SYMBOL_RATE_LABELS:
            continue
        checked += 1
        frequency_hz = out.get("center_frequency_refined_hz") or out.get("center_frequency_hz")
        segment = classify.corrected_segment(c, out, frequency_hz)
        sps = c.sample_rate / out["symbol_rate_hz"]
        if segment is None or sps < 4 or len(segment) < 2 * 2000 * sps:
            pytest.skip(f"{name}: confirmed candidate too short for this validated timing-recovery config")
        recovery = gardner_timing_recovery(segment, sps)
        assert recovery["lock_indicator"], (
            f"{name}: classify.py confirmed {out['fine_modulation_label']} at "
            f"{out['symbol_rate_hz']:.1f} Hz but timing recovery failed to lock")
    if checked == 0:
        pytest.skip(f"{name}: no confirmed bpsk/qpsk/8psk/ask candidate to check")
