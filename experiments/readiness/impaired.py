"""G4: impaired synthetic captures (WP2); the only RNG user is the generator. Same families as G1/G2, long enough for many
4,096-sample windows after decimation, with receiver and channel impairments drawn per capture.

Signal chain (all draws from one seeded RNG per capture; the generator is the only RNG user):
  target symbols -> pulse (RRC 0.25/0.35 or G2's smoothed NRZ; CPFSK for FSK) -> 2-3 tap multipath
  -> carrier with slow linear frequency drift and Wiener phase noise
  + one adjacent-channel interferer (QPSK RRC 0.35 or 2-FSK, -6..+6 dB, 0.5-1.5 bandwidths away)
  + coloured Gaussian noise (first-order FIR shaped, power set by the full-band SNR)
  -> receiver IQ gain/phase imbalance -> DC offset (a spike at 0 Hz) -> mild ADC clipping (I and Q).
SNR is full-band (target signal power / noise power over the whole capture bandwidth), as in G1/G2.
Noise captures get the receiver impairments (colour, imbalance, DC, clipping) but no emitter.
"""
import numpy as np
from scipy import signal

FS = 200_000.0
N = 1 << 19                                   # 2.62 s: >= 16 decimated 4,096-sample windows at every rate
SPS = (8, 16, 32, 64)                         # 25, 12.5, 6.25, 3.125 kBd
SNRS = (0, 5, 10, 20)
KINDS_DIGITAL = ("bpsk", "qpsk", "8psk", "qam16", "ask2", "fsk2", "fsk4")
KINDS_HELD_OUT = ("fsk8", "qam8")
LABEL = {"bpsk": "BPSK", "qpsk": "QPSK", "8psk": "8PSK", "qam16": "QAM16", "ask2": "ASK2", "fsk2": "FSK2",
         "fsk4": "FSK4", "fsk8": "FSK8", "qam8": "QAM8", "fm": "FM", "noise": "noise"}
LINEAR = ("bpsk", "qpsk", "8psk", "qam16", "qam8")
_QAM16 = np.array([-3, -1, 1, 3.0])


def smoothing_taps(sps: int, fs: float = FS) -> np.ndarray:
    """G2's smoothing FIR scaled to this sample rate (2*sps+1 taps, cutoff 1.8 Rs)."""
    return signal.firwin(2 * sps + 1, 1.8 * fs / sps, fs=fs)


def rrc_taps(sps: int, alpha: float, span: int = 8) -> np.ndarray:
    t = np.arange(-span * sps, span * sps + 1) / sps
    h = np.empty_like(t)
    zero = np.isclose(t, 0)
    sing = np.isclose(np.abs(t), 1 / (4 * alpha))
    other = ~(zero | sing)
    h[zero] = 1 - alpha + 4 * alpha / np.pi
    h[sing] = alpha / np.sqrt(2) * ((1 + 2 / np.pi) * np.sin(np.pi / (4 * alpha)) + (1 - 2 / np.pi) * np.cos(np.pi / (4 * alpha)))
    u = t[other]
    h[other] = (np.sin(np.pi * u * (1 - alpha)) + 4 * alpha * u * np.cos(np.pi * u * (1 + alpha))) / \
        (np.pi * u * (1 - (4 * alpha * u) ** 2))
    return h / np.sqrt(np.sum(h ** 2))


def _symbols(kind, rng, k):
    if kind in ("bpsk", "qpsk", "8psk"):
        m = {"bpsk": 2, "qpsk": 4, "8psk": 8}[kind]
        return np.exp(2j * np.pi * rng.integers(0, m, k) / m)
    if kind == "qam16":
        return _QAM16[rng.integers(0, 4, k)] + 1j * _QAM16[rng.integers(0, 4, k)]
    if kind == "qam8":
        return _QAM16[rng.integers(0, 4, k)] + 1j * np.array([-1.0, 1.0])[rng.integers(0, 2, k)]
    raise ValueError(kind)


def _linear(kind, rng, sps, n, shaping):
    k = n // sps + 64
    a = _symbols(kind, rng, k) if kind != "ask2" else np.array([rng.choice([0.0, 0.4]), 1.0])[rng.integers(0, 2, k)]
    up = np.zeros(k * sps, complex)
    if shaping == "nrz":
        up = np.repeat(a, sps).astype(complex)
        x = signal.fftconvolve(up, smoothing_taps(sps), mode="same")
    else:
        up[::sps] = a
        x = signal.fftconvolve(up, rrc_taps(sps, float(shaping[3:])), mode="same")
    s = 32 * sps
    return x[s:s + n]


def _cpfsk(rng, sps, n, levels, h):
    """Continuous-phase M-FSK, rectangular frequency pulse, deviations (m - (M-1)/2) * h * Rs."""
    k = n // sps + 2
    dev = (np.arange(levels) - (levels - 1) / 2) * h / sps          # cycles per sample
    f = np.repeat(dev[rng.integers(0, levels, k)], sps)[:n]
    return np.exp(2j * np.pi * np.cumsum(f))


def _frac_delay(x, d):
    """Delay by d samples (fractional) with an FFT phase ramp (circular; edges are discarded by callers)."""
    f = np.fft.fftfreq(len(x))
    return np.fft.ifft(np.fft.fft(x) * np.exp(-2j * np.pi * f * d))


def _multipath(x, rng, sps):
    taps = int(rng.integers(2, 4))
    y = x.copy()
    for _ in range(taps - 1):
        d = rng.uniform(0.1, 0.8) * sps
        a = rng.uniform(0.1, 0.35) * np.exp(2j * np.pi * rng.uniform())
        y = y + a * _frac_delay(x, d)
    return y, taps


def _emitter(kind, rng, sps, n, fs):
    """(baseband waveform, truth extras) at unit mean power."""
    extra = {}
    if kind in LINEAR or kind == "ask2":
        shaping = str(rng.choice(["rrc0.25", "rrc0.35", "nrz"]))
        x = _linear(kind, rng, sps, n, shaping)
        extra["shaping"] = shaping
    elif kind in ("fsk2", "fsk4", "fsk8"):
        levels = {"fsk2": 2, "fsk4": 4, "fsk8": 8}[kind]
        h = {"fsk2": float(rng.choice([0.5, 1.0])), "fsk4": 0.8, "fsk8": 0.4}[kind]
        x = _cpfsk(rng, sps, n, levels, h)
        extra["h"] = h
    elif kind == "fm":
        t = np.arange(n) / fs
        f1, f2 = rng.uniform(300, 3000), rng.uniform(3000, 8000)
        dev = rng.uniform(5e3, 20e3)
        msg = 0.6 * np.sin(2 * np.pi * f1 * t) + 0.4 * np.sin(2 * np.pi * f2 * t + rng.uniform(0, 2 * np.pi))
        x = np.exp(2j * np.pi * dev * np.cumsum(msg) / fs)
        extra.update(f_max=f2, dev=dev)
    else:
        raise ValueError(kind)
    return x / np.sqrt(np.mean(np.abs(x) ** 2)), extra


def width_hz(kind, rate, extra):
    """Nominal occupied width (for matching detections and placing the interferer)."""
    if kind == "fm":
        return 2 * (extra["dev"] + extra["f_max"])
    if kind in ("fsk2", "fsk4", "fsk8"):
        levels = {"fsk2": 2, "fsk4": 4, "fsk8": 8}[kind]
        return ((levels - 1) * extra["h"] + 2) * rate
    return (1 + float(extra["shaping"][3:])) * rate if extra["shaping"].startswith("rrc") else 2 * rate


def make_capture(kind, snr_db, sps, seed, n=N, fs=FS):
    """(x complex64, clean target complex128, truth-extras dict)."""
    rng = np.random.default_rng(seed)
    t = np.arange(n) / fs
    rate = fs / sps if kind not in ("fm", "noise") else None
    info = dict(kind=kind)
    clean = np.zeros(n, complex)
    others = np.zeros(n, complex)
    if kind != "noise":
        base, extra = _emitter(kind, rng, sps if rate else 16, n, fs)
        info.update(extra)
        base, info["multipath_taps"] = _multipath(base, rng, sps if rate else 16)
        base = base / np.sqrt(np.mean(np.abs(base) ** 2))
        width = width_hz(kind, rate, extra)
        fc = rng.uniform(-0.25, 0.25) * fs
        drift = rng.uniform(-1, 1) * 0.02 * (rate or 1000.0)                     # total drift over the capture, Hz
        linewidth = rng.uniform(0, 1e-3) * (rate or 1000.0)                      # Wiener phase noise, Hz
        phase = np.cumsum(rng.standard_normal(n)) * np.sqrt(2 * np.pi * linewidth / fs)
        freq = fc + drift * (t / t[-1] - 0.5)
        carrier = np.exp(1j * (2 * np.pi * np.cumsum(freq) / fs + phase + 2 * np.pi * rng.uniform()))
        clean = base * carrier * 10 ** (snr_db / 20)
        info.update(fc=float(fc), width=float(width), drift_hz=float(drift), linewidth_hz=float(linewidth))
        # adjacent-channel interferer on the side with more room, 0.5-1.5 target widths from the band edge
        i_kind = str(rng.choice(["qpsk", "fsk2"]))
        i_sps = int(rng.choice([s for s in SPS if s >= 8]))
        ib, iextra = _emitter(i_kind, rng, i_sps, n, fs)
        iw = width_hz(i_kind, fs / i_sps, iextra)
        side = -1.0 if fc > 0 else 1.0
        ifc = fc + side * (width / 2 + rng.uniform(0.5, 1.5) * width + iw / 2)
        if abs(ifc) + iw / 2 < 0.48 * fs:
            ipow = rng.uniform(-6, 6)
            others = ib * np.exp(2j * np.pi * ifc * t) * 10 ** ((snr_db + ipow) / 20)
            info.update(interferer=dict(kind=i_kind, rate=fs / i_sps, fc=float(ifc), width=float(iw),
                                        rel_power_db=float(ipow)))
        else:
            info["interferer"] = None
    # coloured noise: white through a first-order FIR [1, rho e^{j theta}], unit mean power
    w = (rng.standard_normal(n + 1) + 1j * rng.standard_normal(n + 1)) / np.sqrt(2)
    rho, theta = rng.uniform(0.2, 0.6), rng.uniform(0, 2 * np.pi)
    noise = (w[1:] + rho * np.exp(1j * theta) * w[:-1]) / np.sqrt(1 + rho ** 2)
    y = clean + others + noise
    # receiver: IQ imbalance y -> mu y + nu conj(y), DC offset, then ADC clipping of I and Q
    g = 10 ** (rng.uniform(0.3, 1.5) / 20)
    phi = np.deg2rad(rng.uniform(1, 5))
    mu, nu = (1 + g * np.exp(-1j * phi)) / 2, (1 - g * np.exp(1j * phi)) / 2
    y = mu * y + nu * np.conj(y)
    ref = np.sqrt(np.mean(np.abs(y) ** 2))
    dc = ref * 10 ** (rng.uniform(-25, -10) / 20) * np.exp(2j * np.pi * rng.uniform())
    y = y + dc
    clip = rng.uniform(2.5, 3.5) * ref / np.sqrt(2)          # per-rail sigma multiples: ~0.05-1.2% clipped
    y = np.clip(y.real, -clip, clip) + 1j * np.clip(y.imag, -clip, clip)
    info.update(iq_gain_db=float(20 * np.log10(g)), iq_phase_deg=float(np.rad2deg(phi)), dc_db=float(20 * np.log10(abs(dc) / ref)),
                clip_rel=float(clip / ref), noise_rho=float(rho), clipped_fraction=float(np.mean(np.abs(y.real) >= clip)))
    return y.astype(np.complex64), clean, info
