"""Gardner timing-error-detector symbol-timing recovery.

This is timing recovery only: it estimates *where the symbol centers are* in
an already frequency-corrected baseband segment. It does not decode symbols
to bits, demodulate, or claim any decoding capability -- see
backend/pipeline/classify.py's SYMBOL_RATE_LABELS boundary for that
distinction, which this module does not change.

Algorithm: an interpolating (linear) resampler driven by a Gardner timing-
error detector and a standard 2nd-order proportional-integral loop filter
(gains from Rice, "Digital Communications: A Discrete-Time Approach", the
interpolator-controlled loop of Fig 8.4.15 / Eq 8.113). The Gardner error at
symbol index n is

    e[n] = Re{ y[n-1/2]* (y[n] - y[n-1]) }

evaluated at one sample halfway between consecutive symbol instants -- it is
zero at the correct sampling phase and its sign indicates early/late timing,
independent of the data pattern for baseband PSK/ASK-style constellations.
"""
import numpy as np


def _linear_interp(x, idx):
    """Linear-interpolated complex sample at fractional index `idx` into x."""
    i0 = int(np.floor(idx))
    frac = idx - i0
    return x[i0] * (1 - frac) + x[i0 + 1] * frac


def _loop_gains(loop_bw, damping):
    """2nd-order PI loop filter gains, normalized to unit detector gain."""
    theta = loop_bw / (damping + 1.0 / (4.0 * damping))
    denom = 1.0 + 2.0 * damping * theta + theta ** 2
    kp = (4.0 * damping * theta) / denom
    ki = (4.0 * theta ** 2) / denom
    return kp, ki


def gardner_timing_recovery(x, sps, loop_bw=0.001, damping=1.0,
                             lock_std_threshold=0.01, lock_window=2000,
                             estimate_window=2000):
    """Recover symbol timing from a baseband IQ segment with a Gardner TED.

    Parameters
    ----------
    x : array-like of complex
        Baseband samples, already frequency- and DC-corrected (e.g. the
        output of classify.corrected_segment).
    sps : float
        Nominal samples per symbol (sample_rate / symbol_rate_hz). Must be
        >= 4: the Gardner error needs a sample roughly halfway between
        symbol instants, and linear interpolation of a two-sample/symbol
        signal is too coarse to locate it accurately.
    loop_bw : float
        Loop noise bandwidth, normalized to the symbol rate. Smaller tracks
        more slowly but rejects more noise; the default and the validated
        1%-of-symbol-period accuracy at >=10 dB SNR (see
        backend/tests/test_timing_recovery.py) assume a long-enough segment
        (tens of thousands of symbols) for the slow loop to settle.
    damping : float
        Loop damping factor (1.0 is critically damped).

    Returns
    -------
    dict with:
      symbols : ndarray, one complex sample per recovered symbol instant.
      timing_offset_hat : float or None, the converged sampling-phase offset
        from the free-running sample grid, as a fraction of a symbol period
        wrapped to [-0.5, 0.5) -- the circular mean of the trailing
        `estimate_window` per-symbol estimates (steady state, not a single
        noisy sample).
      timing_offset_trace : ndarray, that same per-symbol estimate over time
        (for inspecting/testing convergence).
      lock_indicator : bool, True if the trailing `lock_window` timing-offset
        estimates are internally consistent: the circular mean of its first
        and second half differ by less than `lock_std_threshold` (a fraction
        of a symbol period). The raw per-symbol Gardner error is too noisy
        sample-to-sample to threshold directly (measured RMS ~0.3-0.6 even
        when well converged). A single window's standard deviation was also
        measured to false-lock too often on pure noise (noise's offset trace
        randomly wanders through +/-0.5 and can sit still for a window purely
        by chance); comparing the window's two halves catches a genuinely
        settled estimate (both halves agree, measured max disagreement 0.009
        symbol on synthetic BPSK/QPSK) against a wandering one (disagreement
        was measured to reach 0.08+ on pure noise, though rare low values
        cannot be ruled out -- this is a diagnostic on candidates already
        gated by Detect/Estimate SNR, not a standalone noise/signal test).
      residual_error : ndarray, the raw per-symbol Gardner error trace.
    """
    x = np.asarray(x, dtype=np.complex128)
    if sps < 4:
        raise ValueError("Gardner timing recovery needs at least 4 samples/symbol")
    kp, ki = _loop_gains(loop_bw, damping)
    n = len(x)
    # Normalize the error by the segment's *average* power, fixed once. Dividing
    # by each sample's own instantaneous power instead (the naive per-symbol
    # normalization) correlates the normalizer with the numerator for
    # real-alphabet modulations like BPSK and measurably biases the loop's
    # equilibrium point (~2% of a symbol period at high SNR in validation,
    # sufficient by itself to fail the 1%-of-symbol-period acceptance target).
    avg_power = float(np.mean(np.abs(x) ** 2)) or 1.0
    idx = sps
    nominal_idx = sps
    integrator = 0.0
    prev_symbol = 0j
    symbols, errors, offsets = [], [], []
    while idx + sps / 2 + 1 < n and idx - sps / 2 - 1 >= 0:
        mid = _linear_interp(x, idx - sps / 2)
        cur = _linear_interp(x, idx)
        err = float((cur.real - prev_symbol.real) * mid.real
                    + (cur.imag - prev_symbol.imag) * mid.imag)
        err /= avg_power
        integrator += ki * err
        adjustment = kp * err + integrator
        symbols.append(cur)
        errors.append(err)
        prev_symbol = cur
        nominal_idx += sps
        idx += sps - adjustment
        offset = ((idx - nominal_idx) / sps + 0.5) % 1.0 - 0.5
        offsets.append(offset)
    symbols = np.array(symbols, dtype=np.complex128)
    errors = np.array(errors, dtype=np.float64)
    offsets = np.array(offsets, dtype=np.float64)
    def _circular_mean(a):
        return float(np.angle(np.mean(np.exp(2j * np.pi * a))) / (2 * np.pi))

    if len(offsets) >= lock_window:
        tail = offsets[-lock_window:]
        half = len(tail) // 2
        m1, m2 = _circular_mean(tail[:half]), _circular_mean(tail[half:])
        disagreement = abs(((m1 - m2) + 0.5) % 1.0 - 0.5)
        lock_indicator = bool(disagreement < lock_std_threshold)
    else:
        lock_indicator = False
    if len(offsets):
        tail = offsets[-estimate_window:]
        # Circular mean: offsets wrap at +/-0.5 symbol, so a plain mean would be
        # wrong for a tail straddling the wrap point.
        angle = np.mean(np.exp(2j * np.pi * tail))
        timing_offset_hat = float((np.angle(angle) / (2 * np.pi)) % 1.0)
        if timing_offset_hat >= 0.5:
            timing_offset_hat -= 1.0
    else:
        timing_offset_hat = None
    return {
        "symbols": symbols,
        "timing_offset_hat": timing_offset_hat,
        "timing_offset_trace": offsets,
        "lock_indicator": lock_indicator,
        "residual_error": errors,
    }
