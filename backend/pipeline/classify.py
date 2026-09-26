"""Opt-in, explicitly heuristic IQ modulation measurements."""
import numpy as np
from scipy import signal as scipy_signal
from scipy.cluster.vq import kmeans2

from .detect import EPS, estimate_noise_floor, isolate_band
from .estimate import NFFT, estimate_candidate, interpolated_peak, occupied_windows, tuning_frequency
from .ingest import Capture

# Master-context Stage 5 Monte Carlo validation: ~100/95% correct at 10/5 dB,
# collapsing below 0 dB where differentiation noise amplification dominates.
# 4.5, not 5.0, so measurement noise around a true 5 dB signal (+/-0.1 dB here)
# does not arbitrarily exclude half of exactly-5-dB fixtures from the gate.
SYMBOL_RATE_MIN_SNR_DB = 4.5


def corrected_segment(capture: Capture, candidate: dict, frequency_hz):
    """Longest occupied window, isolated then corrected to the requested center.

    isolate_band already mixes by the midpoint of the Detect bounds. Only the
    remaining offset is removed here; subtract acquisition tuning metadata once.
    Trim 128 samples at each end (the existing FIR's half support), so zero-padding
    transients do not masquerade as envelope variation. No pulses are joined.
    """
    if (capture.metadata.get("source_kind") != "iq" or frequency_hz is None
            or not np.isfinite(frequency_hz)):
        return None
    windows = occupied_windows(capture, candidate)
    if not windows:
        return None
    a, b = max(windows, key=lambda w: w[1]-w[0])
    if b-a < NFFT+256:
        return None
    lo, hi = candidate["freq_lower_hz"], candidate["freq_upper_hz"]
    fs = capture.sample_rate
    if not (np.isfinite(fs) and fs > 0 and np.isfinite(lo) and np.isfinite(hi)
            and -fs/2 <= lo < hi <= fs/2 and np.isfinite(capture.iq[a:b]).all()):
        raise ValueError("Finite IQ, positive sample rate and valid frequency bounds required.")
    isolated = isolate_band(capture.iq[a:b], fs, lo, hi)
    residual = frequency_hz-tuning_frequency(capture)-(lo+hi)/2
    corrected = isolated*np.exp(-2j*np.pi*residual*np.arange(b-a)/fs)
    return corrected[128:-128].astype(np.complex64)


def classify_coarse(capture: Capture, candidate: dict) -> dict:
    """Constant/varying envelope family, never an analog/digital assertion."""
    out = {**candidate, "modulation_family": None, "modulation_confidence": None,
           "envelope_variation": None,
           "modulation_confidence_kind": "heuristic, not a calibrated probability",
           "modulation_status": "not reliably classified (insufficient IQ evidence)"}
    x = corrected_segment(capture, candidate, candidate.get("center_frequency_hz"))
    if x is None:
        return out
    envelope = np.abs(x).astype(np.float64)
    mean = float(np.mean(envelope))
    if not np.isfinite(envelope).all() or mean <= 0:
        return out
    variation = float(np.std(envelope)/mean)
    out.update(envelope_variation=variation,
               modulation_family="constant-envelope" if variation < .3 else "varying-envelope",
               modulation_confidence=min(1., abs(variation-.3)/.3),
               modulation_status="classified (isolated-envelope heuristic)")
    return out


def refine_frequency(capture: Capture, candidate: dict) -> dict:
    """Choose the sharper M=2/4 raised tone; retain Stage 1's direct estimate.

    This is a PSK synchronization hypothesis, not proof of modulation. FM can
    also have sharp spectral lines. Fine classification must independently test
    phase concentration. A peak at the Nyquist boundary is left unresolved.
    """
    out = {**candidate, "center_frequency_refined_hz": None, "refinement_order": None,
           "refinement_sharpness": None,
           "refinement_status": "not reliably refined (requires constant-envelope evidence)"}
    if candidate.get("modulation_family") != "constant-envelope":
        return out
    center = candidate.get("center_frequency_hz")
    x = corrected_segment(capture, candidate, center)
    if x is None:
        return out
    scale = float(np.max(np.abs(x)))
    if scale <= 0 or not np.isfinite(scale):
        return out
    # Normalization preserves frequency/sharpness and avoids Mth-power overflow.
    x = (x/scale).astype(np.complex64)
    # A fixed 1024-point Welch average caps raw resolution at fs/1024 (~46.9 Hz
    # here) regardless of how long the occupied segment is. Over a ~2 s segment
    # that residual, multiplied by the M=4 (QPSK) raised-tone order, accumulates
    # into multiple radians of phase drift and defeats fine classification below.
    # A single full-segment periodogram trades averaging (unneeded for a strong,
    # near-stationary raised tone) for resolution matched to the segment length.
    nperseg = min(len(x), 1 << 20)
    hypotheses = []
    for order in (2, 4, 8):
        f, p, _ = estimate_noise_floor(x**order, capture.sample_rate, nperseg=nperseg)
        peak = interpolated_peak(f, p)
        if peak is None:
            continue
        sharpness = float(np.max(p)/max(float(np.median(p)), EPS))
        hypotheses.append((sharpness, order, peak/order))
    if not hypotheses:
        out["refinement_status"] = "not reliably refined (unresolved raised tone)"
        return out
    sharpness, order, residual = max(hypotheses)
    out.update(center_frequency_refined_hz=float(center+residual), refinement_order=order,
               refinement_sharpness=sharpness, refinement_status="refined (Mth-power peak heuristic)")
    return out


FINE_LABELS = {2: "bpsk", 4: "qpsk", 8: "8psk"}
# Higher raising orders amplify residual phase/frequency noise faster (an
# order-8 raise turns the same phase jitter into 4x the phase excursion an
# order-2 raise would), so 8PSK needs a looser acceptance threshold than
# BPSK/QPSK to avoid false "not reliably classified" on genuinely clean 8PSK.
FINE_SPREAD_THRESHOLD = {2: .8, 4: .8, 8: 1.4}


def classify_fine(capture: Capture, candidate: dict) -> dict:
    """Publish a fine PSK label only when the measured phase spread clears the
    threshold; otherwise expose the diagnostic without a label.

    Matching the Mth-power peak search's resolution to the segment length (see
    refine_frequency) removed the residual-frequency phase drift that previously
    failed QPSK's majority acceptance check; both BPSK (order 2) and QPSK
    (order 4) now pass 5/5 at 20 and 10 dB. FM stays above threshold because its
    continuous phase modulation, not carrier-frequency imprecision, drives its
    spread.

    Pulsed candidates are excluded: an unmodulated gated carrier has trivially
    perfect phase concentration (spread near zero), which this rule cannot
    distinguish from genuine phase-locked PSK. Only continuous candidates were
    validated, so pulsed bursts stay an explicit unknown rather than a false
    "bpsk" label.
    """
    out = {**candidate, "fine_modulation_label": None, "fine_modulation_confidence": None,
           "phase_cluster_spread_rad": None, "envelope_level_count": None, "frequency_level_count": None,
           "fine_modulation_status": "not reliably classified (no phase refinement)"}
    order = candidate.get("refinement_order")
    if candidate.get("is_pulsed"):
        out["fine_modulation_status"] = "not reliably classified (pulsed bursts not validated)"
        return out
    if candidate.get("modulation_family") != "constant-envelope" or order not in FINE_LABELS:
        return out
    x = corrected_segment(capture, candidate, candidate.get("center_frequency_refined_hz"))
    if x is None or not np.any(np.abs(x) > 0):
        return out
    phase = np.angle(x).astype(np.float64)
    concentration = float(abs(np.mean(np.exp(1j*order*phase))))
    if concentration <= 0:
        out["fine_modulation_status"] = "not reliably classified (no phase concentration)"
        return out
    spread = float(np.sqrt(max(0., -2*np.log(min(1., concentration)))))
    out["phase_cluster_spread_rad"] = spread
    threshold = FINE_SPREAD_THRESHOLD[order]
    if spread < threshold:
        out.update(fine_modulation_label=FINE_LABELS[order],
                   fine_modulation_confidence=float(1.-spread/threshold),
                   fine_modulation_status="classified (phase-cluster concentration heuristic)")
    else:
        out["fine_modulation_status"] = "not reliably classified (phase spread above threshold)"
    return out


LEVEL_CLUSTER_CANDIDATES = (2, 3, 4)
# A gap-to-spread ratio, in the same explainable-evidence spirit as the PSK
# phase-spread test above: how many within-cluster standard deviations
# separate the closest two levels. Not a calibrated probability.
LEVEL_SEPARATION_THRESHOLD = 3.0
ASK_PHASE_CONCENTRATION_THRESHOLD = .55
# FM's continuous frequency sweep clusters deceptively well at k=2 (a sinusoid
# spends more time near its extremes, mimicking two "levels"), scoring
# consistently ~4.0-4.4 across -5..20 dB in measurement; genuine held-tone FSK
# scores 5.8+ at 10-20 dB. This threshold sits in the gap measured between
# them, so FSK is only published where that gap is validated (10-20 dB) --
# below that FSK's own score drops into FM's range too and is left unknown.
FSK_SEPARATION_THRESHOLD = 5.5
# The delay-and-multiply symbol-rate estimator (see estimate_symbol_rate) is
# an NRZ-transition detector: measured to generalize cleanly from BPSK/QPSK to
# 8PSK and ASK (<0.05% error, same fixtures used to validate PSK). FSK's
# information is carried in frequency, not amplitude/phase transitions -- the
# same nonlinearity measured ~99% error on FSK fixtures, so it is excluded
# rather than published wrong. QAM has no confirmed order and no symbol-timing
# recovery in this project, so it is excluded too.
SYMBOL_RATE_LABELS = frozenset({"bpsk", "qpsk", "8psk", "ask"})


def _cluster_levels(values, ks=LEVEL_CLUSTER_CANDIDATES):
    """Best 1-D k-means fit (by gap/within-cluster-spread ratio) over a small
    set of candidate cluster counts, or None if none of them fit cleanly.

    Used for both ASK's envelope levels and FSK's instantaneous-frequency
    levels: both are "how many discrete values does this take" questions,
    unlike PSK's phase-concentration test.
    """
    values = np.asarray(values, dtype=np.float64)
    best = None
    for k in ks:
        if len(values) < 8*k:
            continue
        centroids, labels = kmeans2(values.reshape(-1, 1), k, seed=0, minit="++")
        centroids = centroids[:, 0]
        order = np.argsort(centroids)
        centroids = centroids[order]
        remap = np.empty(k, dtype=int)
        remap[order] = np.arange(k)
        labels = remap[labels]
        within = [float(np.std(values[labels == i])) for i in range(k) if np.any(labels == i)]
        if len(within) < k or max(within) <= 0:
            continue
        gap = float(np.min(np.diff(centroids)))
        score = gap/max(within)
        if best is None or score > best[0]:
            best = (score, k, centroids, labels)
    return best


def classify_fine_ask(capture: Capture, candidate: dict) -> dict:
    """Amplitude/phase-keying discrimination for varying-envelope candidates,
    which refine_frequency's Mth-power search never attempts (it requires
    constant envelope). ASK/QAM don't produce a PSK raised-tone carrier, so
    this clusters the envelope's discrete levels instead.

    QAM's exact order (16-QAM vs 64-QAM, ...) needs symbol-timing recovery
    this project doesn't have, so a jointly amplitude- and phase-varying
    signal (checked via phase concentration within the top envelope cluster)
    is published only as an unordered, explicitly lower-confidence "qam" flag
    -- never a specific guessed order.
    """
    out = {**candidate}
    if candidate.get("fine_modulation_label") is not None or candidate.get("is_pulsed"):
        return out
    if candidate.get("modulation_family") != "varying-envelope":
        return out
    # Below 0 dB, even the coarse envelope-family test itself is unvalidated
    # (test_coarse_family_acceptance only asserts it for snr>=0): a genuinely
    # constant-envelope signal (e.g. BPSK) can measure as varying-envelope
    # from noise alone at very low SNR, so trusting an envelope-level cluster
    # built from noise would risk a wrong "ask"/"qam" label, not just "unknown".
    snr = candidate.get("snr_db")
    if snr is None or not np.isfinite(snr) or snr < 0:
        out["fine_modulation_status"] = "not reliably classified (SNR too low for envelope-family evidence)"
        return out
    x = corrected_segment(capture, candidate, candidate.get("center_frequency_hz"))
    if x is None or len(x) < 8*min(LEVEL_CLUSTER_CANDIDATES):
        return out
    found = _cluster_levels(np.abs(x))
    if found is None or found[0] < LEVEL_SEPARATION_THRESHOLD:
        out["fine_modulation_status"] = "not reliably classified (envelope levels not well separated)"
        return out
    score, k, _, labels = found
    out["envelope_level_count"] = k
    top = labels == k-1
    concentration = float(abs(np.mean(np.exp(1j*np.angle(x[top]))))) if np.any(top) else 0.
    confidence = float(min(1., (score-LEVEL_SEPARATION_THRESHOLD)/LEVEL_SEPARATION_THRESHOLD))
    if concentration >= ASK_PHASE_CONCENTRATION_THRESHOLD:
        out.update(fine_modulation_label="ask", fine_modulation_confidence=confidence,
                   fine_modulation_status="classified (envelope-cluster heuristic)")
    else:
        out.update(fine_modulation_label="qam", fine_modulation_confidence=confidence*.5,
                   fine_modulation_status="classified (low-confidence joint amplitude/phase "
                                          "heuristic, order unresolved)")
    return out


def classify_fine_fsk(capture: Capture, candidate: dict) -> dict:
    """Discrete-tone detection for constant-envelope candidates that failed
    every Mth-power PSK hypothesis in classify_fine. FSK carries information
    in frequency switching, not phase concentration, so this clusters
    instantaneous frequency (the unwrapped phase derivative) instead.
    """
    out = {**candidate}
    if candidate.get("fine_modulation_label") is not None or candidate.get("is_pulsed"):
        return out
    if candidate.get("modulation_family") != "constant-envelope":
        return out
    x = corrected_segment(capture, candidate, candidate.get("center_frequency_hz"))
    if x is None or len(x) < 8*min(LEVEL_CLUSTER_CANDIDATES)+1:
        return out
    inst_freq = np.diff(np.unwrap(np.angle(x.astype(np.complex128))))*capture.sample_rate/(2*np.pi)
    found = _cluster_levels(inst_freq)
    if found is None or found[0] < FSK_SEPARATION_THRESHOLD:
        out["fine_modulation_status"] = "not reliably classified (frequency levels not well separated)"
        return out
    score, k, _, _ = found
    out["frequency_level_count"] = k
    confidence = float(min(1., (score-FSK_SEPARATION_THRESHOLD)/FSK_SEPARATION_THRESHOLD))
    out.update(fine_modulation_label="fsk", fine_modulation_confidence=confidence,
               fine_modulation_status="classified (instantaneous-frequency-cluster heuristic)")
    return out


def estimate_symbol_rate(capture: Capture, candidate: dict) -> dict:
    """Delay-and-multiply symbol rate: differentiate, square, and Welch-PSD the
    refined, corrected segment's real part; rectangular-NRZ transitions make
    every harmonic of the true rate nearly equal-strength, so the lowest bin
    within ~3 dB of the global max is picked instead of the raw argmax.

    The nonlinearity is non-negative, so its huge DC term leaks into the first
    few bins under the Hann window's main lobe; left unmasked, that leakage can
    sit within 3 dB of the true rate and get selected as the "lowest" harmonic.
    The first four bins (the observed main-lobe width) are excluded from the
    search entirely, not just the DC bin itself.

    Gated to the validated ~5-20 dB SNR range; differentiation's noise
    amplification below that range was not solved and is reported explicitly
    rather than returning a wrong number.
    """
    out = {**candidate, "symbol_rate_hz": None,
           "symbol_rate_status": "not reliably estimated (requires a confirmed PSK/ASK fine label)"}
    if candidate.get("fine_modulation_label") not in SYMBOL_RATE_LABELS:
        return out
    snr = candidate.get("snr_db")
    if snr is None or not np.isfinite(snr):
        out["symbol_rate_status"] = "not reliably estimated (unknown SNR)"
        return out
    if snr < SYMBOL_RATE_MIN_SNR_DB:
        out["symbol_rate_status"] = "not reliably estimated (SNR below validated 5-20 dB range)"
        return out
    frequency_hz = candidate.get("center_frequency_refined_hz") or candidate.get("center_frequency_hz")
    x = corrected_segment(capture, candidate, frequency_hz)
    if x is None:
        return out
    nonlin = np.diff(np.real(x).astype(np.float64))**2
    nperseg = min(len(nonlin), 1 << 20)
    if nperseg < 8:
        out["symbol_rate_status"] = "not reliably estimated (insufficient occupied samples)"
        return out
    f, p = scipy_signal.welch(nonlin, fs=capture.sample_rate, window="hann", nperseg=nperseg,
                              noverlap=nperseg//2, detrend=False, scaling="density")
    # Exclude the DC bin and its Hann-window leakage neighbors (observed main-lobe
    # width: 4 bins), not just bin 0 -- they carry the nonlinearity's mean, not a
    # symbol harmonic, but can be strong enough to masquerade as one.
    skip = 4
    if len(p) < skip+2 or np.max(p[skip:]) <= 0:
        out["symbol_rate_status"] = "not reliably estimated (no resolved spectral peak)"
        return out
    peak_power = float(np.max(p[skip:]))
    threshold = peak_power/10**.3
    candidates_idx = np.flatnonzero(p[skip:] >= threshold)+skip
    rate = float(f[int(candidates_idx.min())])
    if rate <= 0:
        out["symbol_rate_status"] = "not reliably estimated (nonpositive candidate rate)"
        return out
    out.update(symbol_rate_hz=rate,
               symbol_rate_status="estimated (nonlinearity + lowest-near-peak spectral heuristic)")
    return out


def symbol_rate_diagnostic(capture: Capture, candidate: dict) -> dict:
    """The Welch PSD behind estimate_symbol_rate's harmonic pick, recomputed
    on demand for evidence-trail display only; never used for the published
    symbol_rate_hz itself, so this cannot drift from the validated pipeline."""
    if candidate.get("estimator", "legacy") != "legacy":
        return {"applicable": False, "reason": "the verify estimator does not use this spectral heuristic; "
                                               "see its rate margin (m_rate)"}
    if candidate.get("symbol_rate_hz") is None:
        return {"applicable": False, "reason": candidate.get("symbol_rate_status") or "not reliably estimated"}
    frequency_hz = candidate.get("center_frequency_refined_hz") or candidate.get("center_frequency_hz")
    x = corrected_segment(capture, candidate, frequency_hz)
    if x is None:
        return {"applicable": False, "reason": "insufficient occupied samples"}
    nonlin = np.diff(np.real(x).astype(np.float64))**2
    nperseg = min(len(nonlin), 1 << 20)
    f, p = scipy_signal.welch(nonlin, fs=capture.sample_rate, window="hann", nperseg=nperseg,
                              noverlap=nperseg//2, detrend=False, scaling="density")
    skip = 4
    peak_power = float(np.max(p[skip:]))
    threshold = peak_power/10**.3
    # Downsample for transport only; selection already happened upstream.
    step = max(1, len(f)//800)
    return {
        "applicable": True,
        "frequencies_hz": f[::step].tolist(),
        "power_db": (10*np.log10(np.maximum(p[::step], 1e-300))).tolist(),
        "skip_frequency_hz": float(f[skip]),
        "selected_frequency_hz": candidate["symbol_rate_hz"],
        "peak_power_db": float(10*np.log10(peak_power)),
        "threshold_power_db": float(10*np.log10(threshold)),
    }


ESTIMATORS = ("verify", "legacy")
LEGACY_PROVENANCE = "legacy (fixture-validated only)"
_LEGACY_FIELDS = ("fine_modulation_label", "fine_modulation_confidence", "fine_modulation_status",
                  "phase_cluster_spread_rad", "envelope_level_count", "frequency_level_count",
                  "symbol_rate_status", "qam_symbol_rate_hz", "qam_order", "qam_order_confidence",
                  "constellation_family", "qam_order_status")


# Both estimators return the same key set (large_capture merges on it).
_VERIFY_NOT_RUN = {"verify_family": None, "m_fam": None, "m_rate": None, "unexplained": None,
                   "estimate_tier": None, "label_needs_review": None, "verify_best_hypothesis": None,
                   "verify_segment": None, "verify_elapsed_ms": None, "verify_thresholds": None,
                   "verify_model_snr_db": None, "verify_carrier_hz": None,
                   "verify_status": "not run (estimator=legacy)"}


def analyze_candidate(capture: Capture, candidate: dict, *, noise_floor=None, estimator: str = "verify") -> dict:
    """Run the downstream stages on a copy of one Detect candidate.

    Parameters (centre frequency, bandwidths, SNR, envelope family, carrier
    refinement) always run. Modulation label and symbol rate come from
    `estimator`: "verify" (default; propose -> verify with MDL margins, see
    verify_estimator) or "legacy" (the fixture-validated heuristics, marked
    as such). Neither downstream field can retain a guessed value from the input.
    """
    if estimator not in ESTIMATORS:
        raise ValueError(f"Unknown estimator {estimator!r}; expected one of {ESTIMATORS}.")
    out = estimate_candidate(capture, candidate, noise_floor=noise_floor)
    out = classify_coarse(capture, out)
    out = refine_frequency(capture, out)
    if estimator == "legacy":
        out = classify_fine(capture, out)
        out = classify_fine_fsk(capture, out)
        out = classify_fine_ask(capture, out)
        out = estimate_symbol_rate(capture, out)
        from .qam_order import resolve_qam_order  # deferred: qam_order imports classify itself
        out = resolve_qam_order(capture, out)
        label = out.get("fine_modulation_label")
        return {**out, **_VERIFY_NOT_RUN, "estimator": "legacy", "label_provenance": LEGACY_PROVENANCE,
                "modulation_label": label.upper() if label else None}
    from .verify_estimator import verify_candidate  # deferred: keeps the legacy path importable alone
    skipped = "not run (estimator=verify; legacy heuristics only with estimator=legacy)"
    out.update({k: None for k in _LEGACY_FIELDS})
    out.update(fine_modulation_status=skipped, symbol_rate_status=None, qam_order_status=skipped)
    out.update(verify_candidate(capture, out))
    out["symbol_rate_status"] = out["verify_status"]
    # The legacy M-th power refinement is fixture-validated only (it mis-refined wideband 8PSK
    # by 12-26 kHz); in verify mode the refined centre is verify's carrier for a published
    # linear label, and otherwise not published.
    if out["verify_carrier_hz"] is not None:
        out.update(center_frequency_refined_hz=out["verify_carrier_hz"] + tuning_frequency(capture),
                   refinement_status="refined (verify M-th power carrier, published linear label)")
    else:
        out.update(center_frequency_refined_hz=None, refinement_order=None, refinement_sharpness=None,
                   refinement_status="not refined (verify: no published linear label)")
    model = out["verify_model_snr_db"]
    if model is not None and (out["snr_db"] is None or model > out["snr_db"]):
        # Both estimates are biased low: signal sidelobes can only raise the spectral floor, and
        # model misfit can only raise the rebuild residual, so the larger SNR is kept. The model
        # wins on wideband/short captures whose sidelobes leave no noise-only spectral region.
        out.update(snr_db=model, snr_method="model residual (published verify rebuild)")
    out["label_provenance"] = "verify (propose -> verify, MDL margins)"
    return out
