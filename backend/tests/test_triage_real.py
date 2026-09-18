from pathlib import Path

import numpy as np

from backend.triage_real import clipping_suspected, dc_spike_suspected, noise_floor_nonflat, triage_one


def flat_psd(n=64, level=-70.0):
    return [{"frequency_hz": f, "power_db": level} for f in np.linspace(-1e6, 1e6, n)]


def test_dc_spike_suspected_flags_a_real_spike():
    psd = flat_psd()
    psd[len(psd)//2]["power_db"] = -20.0  # dead-center bin, i.e. 0 Hz
    assert dc_spike_suspected(psd) is True


def test_dc_spike_suspected_ignores_an_offset_peak():
    psd = flat_psd()
    psd[5]["power_db"] = -20.0  # far from 0 Hz
    assert dc_spike_suspected(psd) is False


def test_noise_floor_nonflat_true_for_lumpy_psd():
    psd = flat_psd(level=-70.0)
    for p in psd[::2]:
        p["power_db"] = -40.0
    assert noise_floor_nonflat(psd) is True


def test_noise_floor_nonflat_false_for_flat_psd():
    assert noise_floor_nonflat(flat_psd()) is False


def test_clipping_suspected_integer_datatype_uses_absolute_full_scale():
    # Half the samples pinned near the ci16 rail (post-normalization, ~1.0);
    # the rest far below it. Absolute full-scale comparison should catch this
    # regardless of what the observed peak happens to be.
    iq = np.concatenate([np.full(600, 0.999, dtype=np.complex64),
                         np.full(400, 0.1, dtype=np.complex64)])
    assert clipping_suspected(iq, "ci16_le") is True


def test_clipping_suspected_float_datatype_falls_back_to_relative_peak():
    # No absolute full scale for float formats; a handful of samples at the
    # capture's own observed peak should still trip the relative heuristic.
    iq = np.concatenate([np.full(50, 5.0, dtype=np.complex64),
                         np.full(950, 0.1, dtype=np.complex64)])
    assert clipping_suspected(iq, "cf32_le") is True


def test_clipping_suspected_clean_signal_not_flagged():
    rng = np.random.default_rng(0)
    iq = (rng.standard_normal(1000) + 1j*rng.standard_normal(1000)).astype(np.complex64) * 0.1
    assert clipping_suspected(iq, "cf32_le") is False


def test_triage_one_missing_file_produces_an_error_row_not_a_crash():
    row = triage_one(Path("/nonexistent/does-not-exist.sigmf-data"), None)
    assert row["error"] is not None
    assert "size_bytes" not in row
