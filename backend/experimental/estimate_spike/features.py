"""Cheap scalar features used by the optional expert router."""
import numpy as np

FEATURE_NAMES = ("env", "carrier", "m2", "m4", "if_kurt", "if_std")


def router_features(x: np.ndarray) -> dict[str, float]:
    """Envelope spread, carrier / 2nd / 4th-power line prominence (dB), inst.-frequency shape."""
    a = np.abs(x)
    spec = np.abs(np.fft.fft(x)) ** 2 + 1e-30
    spec2 = np.abs(np.fft.fft(x ** 2)) + 1e-30
    spec4 = np.abs(np.fft.fft(x ** 4)) + 1e-30
    fi = np.angle(x[1:] * np.conj(x[:-1]))
    fi = fi - np.median(fi)
    c = fi - fi.mean()
    return dict(env=float(a.std() / a.mean()),
                carrier=float(10 * np.log10(spec.max() / np.median(spec))),
                m2=float(10 * np.log10(spec2.max() / np.median(spec2))),
                m4=float(10 * np.log10(spec4.max() / np.median(spec4))),
                if_kurt=float(np.mean(c ** 4) / (np.mean(c ** 2) ** 2 + 1e-12)),
                if_std=float(fi.std()))
