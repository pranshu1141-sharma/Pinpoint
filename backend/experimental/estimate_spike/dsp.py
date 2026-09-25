"""Shared deterministic DSP helpers for the Estimate spike."""
import numpy as np
from scipy.signal import find_peaks, welch

TINY = 1e-30


def fft_size(n: int, minimum: int) -> int:
    """Zero-padded FFT length: at least `minimum`, never shorter than the data."""
    return max(minimum, 1 << int(np.ceil(np.log2(max(n, 1)))))


def rrc_pulse(tau: np.ndarray, alpha: float) -> np.ndarray:
    """Root-raised-cosine pulse; tau in symbol periods, singular points handled."""
    tau = np.asarray(tau, dtype=float)
    h = np.empty_like(tau)
    zero = np.isclose(tau, 0)
    sing = np.isclose(np.abs(tau), 1 / (4 * alpha))
    other = ~(zero | sing)
    h[zero] = 1 - alpha + 4 * alpha / np.pi
    h[sing] = (alpha / np.sqrt(2)) * ((1 + 2 / np.pi) * np.sin(np.pi / (4 * alpha))
                                      + (1 - 2 / np.pi) * np.cos(np.pi / (4 * alpha)))
    u = tau[other]
    h[other] = (np.sin(np.pi * u * (1 - alpha)) + 4 * alpha * u * np.cos(np.pi * u * (1 + alpha))) / \
               (np.pi * u * (1 - (4 * alpha * u) ** 2))
    return h


def moving_average(v: np.ndarray, width: int) -> np.ndarray:
    if width <= 1:
        return v
    return np.convolve(v, np.ones(width) / width, mode="same")


def parabolic_offset(a: float, b: float, c: float) -> float:
    """Vertex offset (in bins) of a parabola through three log-magnitudes."""
    den = a - 2 * b + c
    return 0.5 * (a - c) / den if den else 0.0


def rate_band(fs: float, band: tuple[float, float]) -> tuple[float, float]:
    return band[0] * fs, band[1] * fs


def line_peaks(g: np.ndarray, fs: float, band: tuple[float, float], nfft: int, topk: int) -> list[float]:
    """Top-k spectral lines of a (real) transition track within [band], parabolic-refined."""
    g = g - g.mean()
    nf = fft_size(len(g), nfft)
    power = np.abs(np.fft.fft(g * np.hanning(len(g)), nf)) ** 2 + TINY
    freqs = np.arange(nf) * fs / nf
    sel = (freqs >= band[0]) & (freqs <= band[1])
    pb, fb = power[sel], freqs[sel]
    peaks, _ = find_peaks(pb)
    out = []
    for i in peaks[np.argsort(-pb[peaks], kind="stable")[:topk]]:
        d = parabolic_offset(np.log(pb[i - 1]), np.log(pb[i]), np.log(pb[i + 1]))
        out.append(float(fb[i] + d * fs / nf))
    return out


def dedupe(rates, band: tuple[float, float], tol: float) -> list[float]:
    """Keep in-band rates, dropping any within `tol` (relative) of an earlier one."""
    out: list[float] = []
    for r in rates:
        if band[0] <= r <= band[1] and all(abs(r - q) / q >= tol for q in out):
            out.append(float(r))
    return out


def mth_power_carrier(x: np.ndarray, fs: float, nfft: int, power: int = 4) -> float:
    """Coarse carrier offset from the M-th power line (Hann, zero-padded, parabolic)."""
    y = x ** power
    nf = fft_size(len(y), nfft)
    mag = np.abs(np.fft.fft(y * np.hanning(len(y)), nf))
    k = int(np.argmax(mag))
    d = 0.0
    if 0 < k < nf - 1:
        d = parabolic_offset(np.log(mag[k - 1] + TINY), np.log(mag[k] + TINY), np.log(mag[k + 1] + TINY))
    f = (k + d) * fs / nf
    if f > fs / 2:
        f -= fs
    return f / power


def derotate(x: np.ndarray, f: float, fs: float) -> np.ndarray:
    return x * np.exp(-2j * np.pi * f * np.arange(len(x)) / fs)


def fft_lowpass(v: np.ndarray, cutoff: float, fs: float) -> np.ndarray:
    spec = np.fft.fft(v)
    spec[np.abs(np.fft.fftfreq(len(v), 1 / fs)) > cutoff] = 0
    return np.fft.ifft(spec)


def noise_variance(x: np.ndarray, fs: float) -> float:
    """Noise power: 20th percentile of the two-sided Welch PSD times fs."""
    _, psd = welch(x, fs=fs, nperseg=min(256, len(x)), return_onesided=False)
    return float(np.percentile(psd, 20) * fs)
