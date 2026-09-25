"""The prototype's old single-shot rate proposers, kept only for the recall comparison.

E1: derivative energy of the carrier-corrected signal; E2: delay-and-multiply
phase difference; E4 (FSK): instantaneous-frequency changes. Each uses the
'lowest peak within 3 dB of the maximum' rule and adjacent-sample differences.
"""
import numpy as np
from scipy.signal import find_peaks

from backend.experimental.estimate_spike.dsp import derotate, mth_power_carrier, parabolic_offset


def _peak_rate(track, fs, band, nfft=16384):
    track = track - track.mean()
    power = np.abs(np.fft.fft(track * np.hanning(len(track)), nfft)) ** 2 + 1e-30
    freqs = np.arange(nfft) * fs / nfft
    sel = (freqs >= band[0]) & (freqs <= band[1])
    pb, fb = power[sel], freqs[sel]
    peaks, _ = find_peaks(pb)
    if len(peaks) == 0:
        return float(fb[np.argmax(pb)])
    i = peaks[pb[peaks] >= pb[peaks].max() / 2].min()
    d = parabolic_offset(*np.log(pb[i - 1:i + 2])) if 0 < i < len(pb) - 1 else 0.0
    return float(fb[i] + d * fs / nfft)


def legacy_psk(x, fs, band=(10e3, 250e3)):
    xc = derotate(x, mth_power_carrier(x, fs, 16384), fs)
    d = x[1:] * np.conj(x[:-1])
    return [_peak_rate(np.abs(np.diff(xc)) ** 2, fs, band),
            _peak_rate(np.abs(np.angle(d * np.conj(np.mean(d)))), fs, band)]


def legacy_fsk(x, fs, band=(10e3, 250e3)):
    fi = np.angle(x[1:] * np.conj(x[:-1]))
    return [_peak_rate(np.abs(np.diff(fi)), fs, band)]
