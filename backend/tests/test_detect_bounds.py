"""Detect bounds: occupied-bandwidth edge refinement (docs/superpowers/specs/2026-10-23-detect-bounds-design.md)."""
import numpy as np
import pytest

from backend.pipeline.detect import refine_edges, MIN_REFINE_BINS

FLOOR = 1.0


def test_flat_band_keeps_nearly_its_whole_extent():
    spectrum = np.full(40, 100.0)
    i0, i1 = refine_edges(spectrum, FLOOR, fraction=0.95)
    assert 0 <= i0 <= 1 and 39 <= i1 <= 40


def test_skirts_a_few_db_above_the_floor_are_trimmed():
    spectrum = np.r_[np.full(20, 2.0), np.full(10, 1000.0), np.full(20, 2.0)]
    assert refine_edges(spectrum, FLOOR, fraction=0.95) == (20, 30)


def test_a_narrow_spike_does_not_collapse_a_wide_pedestal():
    spectrum = np.full(31, 500.0)
    spectrum[15] = 1e4
    i0, i1 = refine_edges(spectrum, FLOOR, fraction=0.95)
    assert i1 - i0 >= 25


def test_an_off_centre_signal_keeps_its_own_position():
    spectrum = np.r_[np.full(5, 1.5), np.full(8, 400.0), np.full(30, 1.5)]
    assert refine_edges(spectrum, FLOOR, fraction=0.95) == (5, 13)


@pytest.mark.parametrize("spectrum", [np.full(MIN_REFINE_BINS - 1, 100.0), np.full(30, 0.5), np.full(30, FLOOR)])
def test_too_few_bins_or_nothing_above_the_floor_keeps_the_extent(spectrum):
    assert refine_edges(spectrum, FLOOR, fraction=0.95) is None


def test_edges_never_leave_the_extent():
    rng = np.random.default_rng(0)
    for _ in range(200):
        spectrum = rng.exponential(5.0, rng.integers(MIN_REFINE_BINS, 80))
        out = refine_edges(spectrum, FLOOR, fraction=0.95)
        if out is not None:
            i0, i1 = out
            assert 0 <= i0 < i1 <= len(spectrum)


def test_legacy_estimator_analyses_the_threshold_extent_it_was_validated_on():
    """Legacy heuristics are fixture-validated on threshold-extent bounds; refinement must not change them.
    The published bounds stay refined for both estimators."""
    from backend.pipeline.classify import analyze_candidate
    from backend.pipeline.detect import analyze_capture
    from backend.pipeline.ingest import load_capture
    from backend.pipeline.synth_gen import make_signal, FS
    x, _ = make_signal("ask", 20, seed=47)
    c = load_capture("a.iq", x.astype("<c8").tobytes(), FS, "cf32_le")
    r = analyze_capture(c)
    d = next(d for d in r.response["detections"] if d["freq_lower_hz"] < 8000 < d["freq_upper_hz"])
    assert (d["freq_lower_hz"], d["freq_upper_hz"]) != (d["freq_extent_lower_hz"], d["freq_extent_upper_hz"])
    as_extent = {**d, "freq_lower_hz": d["freq_extent_lower_hz"], "freq_upper_hz": d["freq_extent_upper_hz"]}
    legacy = analyze_candidate(c, d, noise_floor=r.noise_floor, estimator="legacy")
    reference = analyze_candidate(c, as_extent, noise_floor=r.noise_floor, estimator="legacy")
    assert (legacy["freq_lower_hz"], legacy["freq_upper_hz"]) == (d["freq_lower_hz"], d["freq_upper_hz"])
    for key in ("fine_modulation_label", "symbol_rate_hz", "modulation_confidence", "snr_db", "bandwidth_3db_hz"):
        assert legacy[key] == reference[key], key
