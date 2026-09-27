"""Cheap symbol-rate proposers and rankers (the 'propose' half of propose -> verify).

Transitions are measured across a gap equal to the smoothing width: an adjacent
difference of a smoothed signal shrinks the jump by 1/w, exactly like the noise.
"""
from typing import Optional

import numpy as np

from .config import SpikeConfig
from .dsp import dedupe, line_peaks, moving_average
from .experts_psk import flat_score, nrz_quick_score
from .expert_fsk import FskExpert, fsk_quick_score


def _gap_lines(track: np.ndarray, w: int, fs: float, band, cfg: SpikeConfig) -> list[float]:
    return line_peaks(np.abs(track[w:] - track[:-w]) ** 2, fs, band, cfg.nfft, cfg.peaks_per_scale)


def psk_proposals(xc: np.ndarray, fs: float, band, cfg: SpikeConfig) -> list[float]:
    """Multi-scale gap-difference lines of the carrier-corrected signal, plus 1/2x and 2x the first."""
    out: list[float] = []
    for w in cfg.psk_scales:
        out += _gap_lines(moving_average(xc, w), w, fs, band, cfg)
    props = dedupe(out, band, cfg.dedupe_tol)
    if props:
        props = props + dedupe([props[0] / 2, props[0] * 2], band, cfg.dedupe_tol)
    return props


def fsk_proposals(x: np.ndarray, fs: float, band, cfg: SpikeConfig) -> list[float]:
    """Same idea on the smoothed instantaneous-frequency (discriminator) track."""
    dd = x[1:] * np.conj(x[:-1])
    out: list[float] = []
    for w in cfg.fsk_scales:
        out += _gap_lines(np.angle(moving_average(dd, w)), w, fs, band, cfg)
    return dedupe(out, band, cfg.dedupe_tol)


def rank_psk(xc: np.ndarray, fs: float, props: list[float], cfg: SpikeConfig) -> list[float]:
    """Keep the finalists with the best quick NRZ (QPSK, no fine timing) score."""
    q = [nrz_quick_score(xc, fs, r, cfg) for r in props]
    return [props[i] for i in np.argsort(q)[:cfg.finalists]]


def needle_refine(xc: np.ndarray, fs: float, finalists: list[float], band, cfg: SpikeConfig) -> list[float]:
    """The rate fit is needle-sharp: nudge every finalist by fractions of a percent.

    Then add 1/2 and 1/3 of the top finalist: the flat-pulse quick score ranks
    harmonics of smoothed pulses above the true rate, so the experts must see it.
    """
    offsets = np.array(cfg.needle_offsets)
    refined = []
    for r0 in finalists:
        rr = r0 * (1 + offsets)
        qq = [flat_score(xc, fs, v) for v in rr]      # alphabet-free: QPSK snapping misjudges ASK/QAM
        refined.append(float(rr[int(np.argmin(qq))]))
    if refined:
        refined += [refined[0] / m for m in cfg.subharmonics]
    return dedupe(refined, band, cfg.refine_dedupe_tol)


def rank_fsk(x: np.ndarray, fs: float, props: list[float], cfg: SpikeConfig) -> list[float]:
    """Keep the finalists whose per-symbol frequencies split most cleanly into two clusters."""
    q = [fsk_quick_score(x, fs, r, cfg) for r in props]
    return [props[i] for i in np.argsort(q)[::-1][:cfg.fsk_finalists]]


def fsk_needle_refine(x: np.ndarray, fs: float, finalists: list[float], band,
                      cfg: SpikeConfig) -> list[tuple[float, Optional[float]]]:
    """Needle-refine every FSK finalist with the FSK model itself.

    Returns (rate, timing hint) pairs, deduped within 1% (first kept).
    """
    expert = FskExpert(cfg)
    pairs = [expert.refine_rate(x, fs, r) for r in finalists]
    keep = dedupe([r for r, _ in pairs], band, cfg.refine_dedupe_tol)
    return [pair for pair in pairs if pair[0] in keep]
