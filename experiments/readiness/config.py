"""Readiness pass/fail thresholds. Fixed by WP0 of the finale plan: never edit these to make a bar move.

Library membership is not a threshold: it says which families a system claims to
know, and WP3 widens it (which makes the label criteria harder, not easier).
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Thresholds:
    min_snr_db: float = 5.0              # "at >= 5 dB" in every criterion
    detect_recall_min: float = 0.95
    detect_noise_false_max: float = 0.05
    detect_fragmentation_max: float = 0.05
    cf_err_frac_bw: float = 0.10         # |cf error| <= 10% of the true -3 dB bandwidth
    bw3_tol: float = 0.25                # -3 dB bandwidth within +-25% of truth
    snr_err_db: float = 2.0
    param_pass_fraction: float = 0.90    # a parameter criterion passes when >= 90% of eligible captures meet it
    label_wrong_max: float = 0.03
    label_correct_min: float = 0.60
    rate_wrong_max: float = 0.03
    rate_correct_min: float = 0.50
    rate_rel_tol: float = 0.05           # a rate is right within 5% (the spike's evaluation rule)
    ool_wrong_max: float = 0.10
    speed_s: float = 0.5
    speed_pass_fraction: float = 0.95
    real_min_recordings: int = 5


THRESHOLDS = Thresholds()

# Families each estimator claims to model. OUT_OF_LIBRARY are held out to test abstention.
# WP0 baseline: in = BPSK/QPSK/QAM16/FSK2, out = 8PSK/FSK4. WP3 added 8PSK and FSK4 to the
# library, so the held-out set became 8-FSK and rectangular 8-QAM (an appended G2 block).
IN_LIBRARY = frozenset({"BPSK", "QPSK", "8PSK", "QAM16", "FSK2", "FSK4"})
OUT_OF_LIBRARY = frozenset({"FSK8", "QAM8"})

G1_TEST_SEED = 7
G1_TEST_N = 300
