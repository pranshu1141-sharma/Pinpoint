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
    # Fixed by principle (a 1% test), not fit: a label names an alphabet, so every point must be
    # in use; p < 0.01 that the least-used point is this rare under uniform use -> not published.
    min_usage: float = 0.01
    # FM is published only if it beats the best digital hypothesis by this margin (0 = off)
    m_fm_digital: float = 0.0
    # the label also needs this margin over the best hypothesis with a different label (the
    # family margin never separated QPSK from 8PSK or FSK2 from FSK4); 0 = off
    m_label: float = 0.0


@dataclass(frozen=True)
class SpikeConfig:
    rate_band: tuple[float, float] = (0.01, 0.3)      # symbol-rate search band, x fs
    nfft: int = 16384
    carrier_power: tuple[int, ...] = (4, 8)          # M-th power carrier lines tried (most prominent wins)
    psk_scales: tuple[int, ...] = (1, 2, 4, 8)
    fsk_scales: tuple[int, ...] = (2, 4, 8, 16)
    peaks_per_scale: int = 3
    finalists: int = 3
    fsk_finalists: int = 3                          # FSK rates carried to the (costly) FSK fits
    subharmonics: tuple[int, ...] = (2, 3)           # also try top finalist / m
    dedupe_tol: float = 0.02
    refine_dedupe_tol: float = 0.01
    needle_offsets: tuple[float, ...] = (-0.006, -0.003, 0.0, 0.003, 0.006)
    alphabets: tuple[int, ...] = (2, 4, 8, 16, -2)   # -2: unipolar 2-level ASK
    snap_block: int = 16
    quick_alphabets: tuple[int, ...] = (4, -2)       # ranking: QPSK alone ranks unipolar ASK badly
    rrc_alpha: float = 0.35
    rrc_span: int = 6
    rrc_phases: int = 8
    pulse_orders: int = 2                # alphabets the rrc/lsp experts rebuild (best flat-block scores)
    lsp_span: int = 2                    # least-squares pulse support, +-symbols
    lsp_grid: int = 16                   # pulse samples per symbol (coarser grids favour 2x rates)
    lsp_rate_iters: int = 2              # decision-directed rate refinements
    lsp_drift_chunks: int = 8
    lsp_max_drift: float = 0.002         # larger clock errors are outside the linear regime
    fsk_library_tones: tuple[int, ...] = (2, 4)
    # rate-multiple check: >= this share of tone changes on one boundary residue mod m (and
    # enough changes to judge); true-rate 4-FSK spreads changes evenly over residues
    fsk_multiple_share: float = 0.85
    fsk_multiple_min_changes: int = 20
    fsk_probe_tones: tuple[int, ...] = (8,)   # probe for discrete IF levels outside the library (FM gate)
    fsk_needle_tones: tuple[int, ...] = (2, 4)  # tone counts whose rate the needle refines
    fsk_search_block: int = 2
    fsk_score_block: int = 8
    fsk_quick_phases: int = 6
    fsk_search_phases: int = 12
    # Deviation from the prototype: re-refine timing with the scoring block size
    # after the short-block search (the long-block basin is only ~+-0.1 sample wide
    # and the short-block optimum can sit ~0.5 sample away). See results report.
    fsk_rescore_refine: bool = True
    # FSK needle refinement (another deviation; the prototype refined PSK finalists only).
    fsk_needle: bool = True
    fsk_needle_top: int = 1              # needle-refine only the top-k ranked FSK finalists
    fsk_needle_span: float = 0.0025      # search +-0.25% around each finalist
    fsk_needle_grid_step: float = 0.0005
    fsk_needle_min_step: float = 0.00001
    fsk_needle_block: int = 8            # phase-block length (symbols) while scoring rates
    fsk_needle_timing_step: float = 1.0  # initial timing step (samples) in the joint search
    fsk_needle_min_timing_step: float = 0.0625
    fsk_needle_max_moves: int = 4        # pattern-search moves per step size
    # The score is jagged below one sample (samples switch symbols), so the final
    # FSK fit ends with a dense scan of +-fsk_final_scan samples around its best timing.
    fsk_final_scan: float = 0.5
    fsk_final_scan_step: float = 0.0625
    analog_bandwidths: tuple[float, ...] = (3e-3, 6e-3, 12e-3, 25e-3, 50e-3)  # x fs
    rate_margin_tol: float = 0.05
    min_samples: int = 2000
    threads: int = 2                     # >1: FSK side on a worker thread, concurrently (same result)


DEFAULT = SpikeConfig()
