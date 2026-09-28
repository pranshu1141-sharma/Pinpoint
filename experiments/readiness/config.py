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

    # --- WP2 (registered before G4/G5/throughput were first measured) ---
    # G4, impaired synthetic: the G1/G2 label/rate/abstention bars, applied to impaired captures.
    g4_label_wrong_max: float = 0.03       # W1: published-wrong labels <= 3% of G4 test captures (as L1)
    g4_label_correct_min: float = 0.60     # W2: published-correct >= 60% of in-library digital at >= 5 dB (as L2)
    g4_ool_wrong_max: float = 0.10         # W3: held-out families (8-FSK, 8-QAM) -> <= 10% wrong labels (as C2)
    g4_rate_wrong_max: float = 0.03        # W4: published-wrong rates <= 3% of G4 test captures (as R1)
    # G5, real benchmark (rtl_433_tests + IQEngine test files): real coverage at a fixed wrong-label ceiling.
    real_correct_min: float = 0.50         # RC1: a correct label published on >= 50% of test files that have one
    real_wrong_max: float = 0.05           # RC2: a wrong label published on <= 5% of all test files
    real_rate_wrong_max: float = 0.05      # RC3: a wrong rate published on <= 5% of rate-scored test files
    # Batch throughput on a fixed folder (G3 + G5 test files): wall-clock of the batch CLI divided by the
    # total recorded duration. <= 1 keeps pace with one receiver recording continuously.
    throughput_rtf_max: float = 1.0        # T1


THRESHOLDS = Thresholds()

# Families each estimator claims to model. OUT_OF_LIBRARY are held out to test abstention.
# WP0 baseline: in = BPSK/QPSK/QAM16/FSK2, out = 8PSK/FSK4. WP3 added 8PSK and FSK4 to the
# library, so the held-out set became 8-FSK and rectangular 8-QAM (an appended G2 block).
# WP3b added unipolar 2-level ASK (both estimators claim it).
IN_LIBRARY = frozenset({"BPSK", "QPSK", "8PSK", "QAM16", "FSK2", "FSK4", "ASK2"})
OUT_OF_LIBRARY = frozenset({"FSK8", "QAM8"})

G1_TEST_SEED = 7
G1_TEST_N = 300

# WP2 generators: G4 impaired synthetic (generators.g4_specs; calibration seeds from G4_CALIBRATION_SEED_BASE),
# G5 real benchmark (g5_manifest.json, split frozen by protocol before anything was run on it).
G5_MANIFEST = "g5_manifest.json"
