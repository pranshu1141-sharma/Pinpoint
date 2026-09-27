"""Opt-in IQ parameter measurements; Detect and its API remain unchanged.

Frequencies are absolute when Capture metadata contains a tuning frequency,
otherwise baseband. SNR uses full-band complex noise power, as synth_gen does.
All intervals are end-exclusive. These functions do not read synthetic truth.
"""
import numpy as np
from scipy.stats import gamma

from .detect import EPS, estimate_noise_floor
from .ingest import Capture

NFFT = 1024


def occupied_windows(capture: Capture, candidate: dict) -> list[tuple[int, int]]:
    """Validate occupied intervals and merge their union without bridging gaps."""
    start, end = candidate["start_sample"], candidate["end_sample"]
    if not (isinstance(start, (int, np.integer)) and isinstance(end, (int, np.integer))
            and 0 <= start < end <= len(capture.iq)):
        raise ValueError("Invalid candidate sample interval.")
    raw = candidate.get("pulse_windows", []) if candidate["is_pulsed"] else [candidate]
    windows = []
    for w in raw:
        a, b = w["start_sample"], w["end_sample"]
        if not (isinstance(a, (int, np.integer)) and isinstance(b, (int, np.integer))
                and start <= a < b <= end):
            raise ValueError("Invalid pulse sample interval.")
        windows.append((int(a), int(b)))
    merged = []
    for a, b in sorted(windows):
        if merged and a <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(b, merged[-1][1]))
        else:
            merged.append((a, b))
    return merged


def occupied_psd(capture: Capture, windows: list[tuple[int, int]]):
    """Equal-weight average of every occupied window's 1024-point Welch PSD.

    Do not concatenate pulses (which creates false transitions), or silently
    discard short pulses. The caller returns unknown if any is too short.
    """
    if not windows or any(b-a < NFFT for a, b in windows):
        raise ValueError("Insufficient occupied samples for 1024-point Welch PSD.")
    total = np.zeros(NFFT, dtype=np.float64)
    for a, b in windows:
        f, p, _ = estimate_noise_floor(capture.iq[a:b], capture.sample_rate)
        total += p
    return f, total/len(windows)


def interpolated_peak(frequencies, power):
    """Log-power, three-bin parabolic peak for a resolved raised-signal tone.

    Deliberately separate from Stage 1's noise-subtracted spectral centroid.
    Edge peaks cannot be interpolated and return None (aliasing is ambiguous).
    """
    k = int(np.argmax(power))
    if k == 0 or k == len(power)-1 or power[k] <= 0:
        return None
    a, b, c = np.log(np.maximum(power[k-1:k+2], EPS))
    curvature = a-2*b+c
    if curvature >= 0:
        return None
    delta = float(np.clip(.5*(a-c)/curvature, -.5, .5))
    return float(frequencies[k]+delta*(frequencies[1]-frequencies[0]))


def measure_bandwidths(frequencies, power):
    """Connected half-power lobe and shortest band with >=99% in-band power.

    Half-power crossings are linearly interpolated. Occupied power integrates
    whole frequency cells, so its resolution is one Welch bin. Both use the
    averaged measured PSD, before noise subtraction, within the Detect band.
    An unobserved half-power crossing is unknown, not a clipped width.
    """
    if len(power) < 3 or np.max(power) <= 0:
        return None, None
    k = int(np.argmax(power))
    half = power[k]/2
    left = right = k
    while left > 0 and power[left-1] >= half:
        left -= 1
    while right < len(power)-1 and power[right+1] >= half:
        right += 1
    width = None
    if left > 0 and right < len(power)-1:
        lo = np.interp(half, power[left-1:left+1], frequencies[left-1:left+1])
        hi = np.interp(half, power[right:right+2][::-1], frequencies[right:right+2][::-1])
        width = float(hi-lo)
    cumulative = np.r_[0., np.cumsum(power, dtype=np.float64)]
    target = .99*cumulative[-1]
    best = len(power)
    for start in range(len(power)):
        stop = int(np.searchsorted(cumulative, cumulative[start]+target, side="left"))
        if stop <= len(power):
            best = min(best, stop-start)
    occupied = float(best*(frequencies[1]-frequencies[0]))
    return width, occupied


FLOOR_PERCENTILE = 20


def robust_noise_floor(iq: np.ndarray, fs: float) -> float:
    """Noise density from a low percentile of the Welch PSD, bias-corrected.

    The frequency median over-estimates noise once a signal (and its sidelobes)
    occupies a large share of the band, which biased SNR low by 3-6 dB on
    wideband captures. For noise alone, each Welch bin averages K Hann segments
    with 50% overlap: approximately gamma-distributed with shape K/1.056, so the
    20th percentile is divided by that distribution's 20% quantile / mean. Stopband
    bins (> 10 dB under the median) are excluded, and the result is bounded to within
    6 dB under the median.
    """
    _, psd, median = estimate_noise_floor(iq, fs)
    k = max(1, (len(iq) - NFFT // 2) // (NFFT // 2))
    shape = k / 1.056
    q = gamma.ppf(FLOOR_PERCENTILE / 100, shape) / shape
    # A receiver anti-alias stopband holds bins far below the in-band noise; they are not
    # noise samples of the band of interest (they sent SNR to +70 dB). Ignore bins more than
    # 10 dB under the median, and never go more than 6 dB under the median.
    usable = psd[psd >= median / 10]
    floor = np.percentile(usable if usable.size >= 16 else psd, FLOOR_PERCENTILE) / q
    return float(max(floor, median / 10 ** 0.6, EPS))


def half_power_width(frequencies, excess):
    """-3 dB width of a noise-subtracted PSD, smoothed across frequency first.

    A 1024-point Welch PSD of a short capture is spiky; the connected half-power
    lobe of the raw estimate stops at the first dip (3 kHz for a 121 kHz lobe).
    Smooth with a box of ~1/8 of the current width estimate (starting from 1/16
    of the candidate band, at least 3 bins, three updates), then take the
    connected half-power lobe (measure_bandwidths).
    """
    df = frequencies[1] - frequencies[0]
    top = max(3, len(excess) // 4)
    w = int(np.clip(len(excess) // 16, 3, top))
    width = None
    for _ in range(3):
        width, _ = measure_bandwidths(frequencies, np.convolve(excess, np.ones(w | 1) / (w | 1), mode="same"))
        if width is None:
            break
        w = int(np.clip(round(width / df / 8), 3, top))
    return width


def width_psd(capture: Capture, windows: list[tuple[int, int]]):
    """Welch PSD for the -3 dB width: segment length chosen for >= ~16 averages per window
    (64..1024 points), so short captures are not measured on a 7-average spiky estimate."""
    shortest = min(b - a for a, b in windows)
    nper = int(np.clip(1 << int(np.floor(np.log2(max(shortest // 16, 1)))), 64, NFFT))
    total = None
    for a, b in windows:
        f, p, _ = estimate_noise_floor(capture.iq[a:b], capture.sample_rate, nperseg=nper)
        total = p if total is None else total + p
    return f, total / len(windows)


def tuning_frequency(capture: Capture) -> float:
    """Ingest stores validated SigMF core:frequency under this metadata key."""
    offset = capture.metadata.get("center_frequency_hz")
    if offset is None:
        return 0.
    if not np.isfinite(offset):
        raise ValueError("Metadata tuning frequency must be finite.")
    return float(offset)


def estimate_candidate(capture: Capture, candidate: dict, *, noise_floor=None) -> dict:
    """Return an enriched copy; an optional noise density can reuse Detect's floor.

    No IQ is invented for real audio. Missing evidence returns null measurement
    fields plus estimate_status. Invalid bounds/nonfinite inputs raise ValueError.
    SNR is total occupied-sample power minus full-band estimated noise: overlapping
    sources contaminate it, and this function does not separate such sources.
    """
    out = {**candidate, "center_frequency_hz": None, "bandwidth_3db_hz": None,
           "bandwidth_99pct_hz": None, "bandwidth_99pct_caveat": None,
           "snr_db": None, "snr_method": None, "estimate_status": "not reliably estimated"}
    if capture.metadata.get("source_kind") != "iq":
        out["estimate_status"] = "not reliably estimated (requires complex IQ)"
        return out
    fs = capture.sample_rate
    if not np.isfinite(fs) or fs <= 0 or not np.isfinite(capture.iq).all():
        raise ValueError("Samples and positive sample rate must be finite.")
    lo, hi = candidate["freq_lower_hz"], candidate["freq_upper_hz"]
    if not (np.isfinite(lo) and np.isfinite(hi) and -fs/2 <= lo < hi <= fs/2):
        raise ValueError("Invalid candidate frequency bounds.")
    offset = tuning_frequency(capture)
    windows = occupied_windows(capture, candidate)
    if not windows or min(b-a for a, b in windows) < NFFT:
        out["estimate_status"] = "not reliably estimated (insufficient occupied samples)"
        return out
    if noise_floor is None:
        _, _, noise_floor = estimate_noise_floor(capture.iq, fs)
    if not np.isfinite(noise_floor) or noise_floor <= 0:
        raise ValueError("Noise floor must be a positive finite power density.")
    # SNR and the -3 dB width use the percentile floor; Detect's median floor is kept for Detect.
    noise_floor = min(noise_floor, robust_noise_floor(capture.iq, fs))
    f, p = occupied_psd(capture, windows)
    in_band = (f >= lo) & (f <= hi)
    f, p = f[in_band], p[in_band]
    excess = np.maximum(p-noise_floor, 0)
    on_power = sum(float(np.sum(np.abs(capture.iq[a:b]).astype(np.float64)**2))
                   for a, b in windows)/sum(b-a for a, b in windows)
    off_power = noise_floor*fs
    if len(p) < 3 or on_power <= off_power or np.sum(excess) <= 0:
        out["estimate_status"] = "not reliably estimated (no resolved excess power)"
        return out
    out["center_frequency_hz"] = float(np.sum(f*excess)/np.sum(excess)+offset)
    out["snr_db"] = float(10*np.log10((on_power-off_power)/off_power))
    out["snr_method"] = "spectral (occupied power vs percentile noise floor)"
    _, bw99 = measure_bandwidths(f, p)
    fw, pw = width_psd(capture, windows)
    sel = (fw >= lo) & (fw <= hi)
    bw3 = half_power_width(fw[sel], np.maximum(pw[sel] - noise_floor, 0)) if sel.sum() >= 3 else None
    out.update(bandwidth_3db_hz=bw3, bandwidth_99pct_hz=bw99)
    if bw3 is not None and bw99 > 5*bw3:
        out["bandwidth_99pct_caveat"] = "unshaped-pulse-sidelobes"
    out["estimate_status"] = ("estimated" if bw3 is not None else
                              "partial (half-power lobe truncated by candidate band)")
    return out
