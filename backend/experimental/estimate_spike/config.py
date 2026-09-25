"""Tunable constants for the propose -> verify Estimate spike.

Every frequency is stored as a fraction of the sample rate so the method
works at any fs; defaults reproduce the prototype at fs = 1 MS/s.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Thresholds:
    """Decision margins fit on a calibration half (never on test data)."""
    m_fam: float = 0.411
    m_rate: float = 0.149
    unexplained_max: float = 0.097


@dataclass(frozen=True)
class SpikeConfig:
    rate_band: tuple[float, float] = (0.01, 0.3)      # symbol-rate search band, x fs
    nfft: int = 16384
    carrier_power: int = 4                           # M-th power carrier estimate
    psk_scales: tuple[int, ...] = (1, 2, 4, 8)
    fsk_scales: tuple[int, ...] = (2, 4, 8, 16)
    peaks_per_scale: int = 3
    finalists: int = 3
    dedupe_tol: float = 0.02
    refine_dedupe_tol: float = 0.01
    needle_offsets: tuple[float, ...] = (-0.006, -0.003, 0.0, 0.003, 0.006)
    alphabets: tuple[int, ...] = (2, 4, 16)
    snap_block: int = 16
    rrc_alpha: float = 0.35
    rrc_span: int = 6
    rrc_phases: int = 8
    fsk_search_block: int = 2
    fsk_score_block: int = 8
    fsk_quick_phases: int = 6
    fsk_search_phases: int = 12
    # Deviation from the prototype: re-refine timing with the scoring block size
    # after the short-block search (the long-block basin is only ~+-0.1 sample wide
    # and the short-block optimum can sit ~0.5 sample away). See results report.
    fsk_rescore_refine: bool = True
    analog_bandwidths: tuple[float, ...] = (3e-3, 6e-3, 12e-3, 25e-3, 50e-3)  # x fs
    rate_margin_tol: float = 0.05
    min_samples: int = 2000


DEFAULT = SpikeConfig()
