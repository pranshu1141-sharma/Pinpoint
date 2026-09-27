"""Acceptance tests for the experimental propose -> verify Estimate spike.

Synthetic fixtures come from experiments/estimate_spike/signals.py (seeded);
the analysis code itself uses no randomness. See docs/estimate_spike_results.md.
"""
import re
import time
from pathlib import Path

import numpy as np
import pytest

from backend.experimental.estimate_spike import DEFAULT, Thresholds, analyze_segment, decide
from backend.experimental.estimate_spike.expert_analog import AnalogExpert
from backend.experimental.estimate_spike.expert_fsk import FskExpert
from backend.experimental.estimate_spike.experts_psk import NrzPskExpert, RrcPskExpert
from backend.experimental.estimate_spike.dsp import derotate, mth_power_carrier
from experiments.estimate_spike.signals import corpus, generate

FS = 1e6
SNR = 13.0
NOISE_LN = np.log(10 ** (-SNR / 10))
BACKEND = Path(__file__).resolve().parents[1]


def _decide(r):
    return decide(r.hypotheses, r.noise_var, r.total_power, Thresholds())


def _xc(x, fs=FS):
    return derotate(x, mth_power_carrier(x, fs, DEFAULT.nfft), fs)


OWN_FAMILY = [
    # (kind, generator overrides, expert name, expected label)
    ("PSK", dict(label="BPSK", shaping="NRZ", rate=50e3), "nrz", "BPSK"),
    ("PSK", dict(label="QPSK", shaping="NRZ", rate=70e3), "nrz", "QPSK"),
    ("QAM16", dict(shaping="NRZ", rate=40e3), "nrz", "QAM16"),
    ("PSK", dict(label="QPSK", shaping="RRC", rate=60e3), "rrc", "QPSK"),
    ("FSK2", dict(h=1.0, rate=80e3), "fsk", "FSK2"),
    # was a strict xfail: the analog expert now interpolates the carrier below one FFT bin
    ("AM", dict(), "analog", "AM"),
    ("FM", dict(), "analog", "FM"),
]


@pytest.mark.parametrize("kind,over,expert,label", OWN_FAMILY)
def test_each_expert_fits_its_own_family(kind, over, expert, label):
    rng = np.random.default_rng(11)
    x, truth = generate(rng, kind, snr_db=SNR, **over)
    xc = _xc(x)
    experts = {"nrz": NrzPskExpert(DEFAULT), "rrc": RrcPskExpert(DEFAULT), "fsk": FskExpert(DEFAULT)}
    if expert == "analog":
        own = AnalogExpert(DEFAULT).fit(x, FS)
        rivals = [e.fit(x, xc, FS, r) for e in experts.values() for r in (30e3, 60e3, 120e3)]
    else:
        own = experts[expert].fit(x, xc, FS, truth["Rs"])
        rivals = [e.fit(x, xc, FS, truth["Rs"]) for n, e in experts.items() if n != expert]
        rivals.append(AnalogExpert(DEFAULT).fit(x, FS))
    assert own.label == label
    assert abs(np.log(own.residual) - NOISE_LN) < 0.3
    assert all(own.score < h.score for h in rivals if h is not None)


@pytest.mark.parametrize("seed", range(10))
def test_fsk_scores_true_rate_below_double_rate(seed):
    rng = np.random.default_rng(seed)
    x, _ = generate(rng, "FSK2", snr_db=13.0, rate=80e3, h=1.0)
    xc = _xc(x)
    fsk = FskExpert(DEFAULT)
    true, double = fsk.fit(x, xc, FS, 80e3), fsk.fit(x, xc, FS, 160e3)
    # 2x never wins: either it scores worse or the rate-multiple check reports the true rate
    assert true.score < double.score or abs(double.rate - 80e3) / 80e3 < 0.05


@pytest.mark.parametrize("h", [0.5, 1.0])
@pytest.mark.parametrize("seed", range(4))
def test_fsk_needle_recovers_rate_from_offset_finalist(seed, h):
    """A finalist 0.15% off drifts ~0.5 symbol over the segment and scores far worse than the
    true rate. After the needle the hypothesis must score like the exact true rate, and the
    drift must at least halve. At 10 dB the score's own optimum can sit ~0.1 symbol of drift
    from the truth, and the hard-boundary score is jagged by ~0.03 nats for rate changes of
    ~1e-5 (measured), so neither exact drift nor an exact score match is asserted."""
    rng = np.random.default_rng(200 + seed)
    rate = rng.uniform(40e3, 140e3)
    x, _ = generate(rng, "FSK2", snr_db=10.0, rate=rate, h=h)
    fsk = FskExpert(DEFAULT)
    start = rate * 1.0015
    refined, hint = fsk.refine_rate(x, FS, start)
    assert abs(refined - rate) <= 0.5 * abs(start - rate)
    xc = _xc(x)
    truth = fsk.fit(x, xc, FS, rate).score
    assert fsk.fit(x, xc, FS, start).score > truth + 0.05  # the problem is real
    assert fsk.fit(x, xc, FS, refined, timing_hint=hint).score <= truth + 0.04


@pytest.mark.parametrize("seed", range(6))
def test_bpsk_not_reported_at_double_rate(seed):
    rng = np.random.default_rng(100 + seed)
    rate = rng.uniform(25e3, 140e3)
    x, _ = generate(rng, "PSK", snr_db=rng.uniform(9, 14), rate=rate, label="BPSK", shaping="NRZ")
    r = analyze_segment(x, FS)
    if not any(abs(p - rate) / rate < 0.02 for p in r.psk_proposals):
        pytest.skip("true rate not proposed; needle regression does not apply")
    d = _decide(r)
    assert d.rate is not None
    assert abs(d.rate - 2 * rate) / (2 * rate) >= 0.05
    assert abs(d.rate - rate) / rate < 0.05


def test_noise_only_abstains():
    for seed in range(20):
        rng = np.random.default_rng(1000 + seed)
        x, _ = generate(rng, "noise")
        d = _decide(analyze_segment(x, FS))
        assert d.tier == "abstain" and not d.rate_shipped and d.needs_review


def _captures(k):
    return [x for x, _ in corpus(k, 21)]


def _scores(r):
    return [(h.expert, h.label, h.rate, h.score) for h in r.hypotheses]


def test_repeatable_and_order_independent():
    xs = _captures(30)
    fwd = [_scores(analyze_segment(x, FS)) for x in xs]
    rev = [_scores(analyze_segment(x, FS)) for x in reversed(xs)][::-1]
    again = [_scores(analyze_segment(x, FS)) for x in xs]
    assert fwd == rev == again  # bit-identical


@pytest.mark.parametrize("transform", [lambda x: 1000 * x, lambda x: x * np.exp(1.1j)],
                         ids=["amplitude_x1000", "phase_1.1rad"])
def test_amplitude_and_phase_invariance(transform):
    for x in _captures(30):
        a, b = _decide(analyze_segment(x, FS)), _decide(analyze_segment(transform(x), FS))
        assert (a.expert, a.label, a.tier, a.rate_shipped) == (b.expert, b.label, b.tier, b.rate_shipped)
        assert (a.rate is None) == (b.rate is None)
        if a.rate is not None:
            assert b.rate == pytest.approx(a.rate, rel=1e-9)
        for m in ("m_fam", "m_null", "m_rate"):
            va, vb = getattr(a, m), getattr(b, m)
            assert (np.isnan(va) and np.isnan(vb)) or vb == pytest.approx(va, abs=1e-6)


def test_timing_budget_per_4096_samples():
    x, _ = generate(np.random.default_rng(5), "PSK", snr_db=8.0)
    analyze_segment(x, FS)  # warm-up
    times = []
    for _ in range(3):
        t0 = time.perf_counter()
        analyze_segment(x, FS)
        times.append(time.perf_counter() - t0)
    assert np.median(times) < 0.5


def test_other_sample_rate_and_length():
    fs = 2e6
    x, truth = generate(np.random.default_rng(8), "PSK", fs=fs, n=8192, snr_db=13.0,
                        label="BPSK", shaping="NRZ", rate=150e3)
    d = _decide(analyze_segment(x, fs))
    assert d.label == "BPSK" and abs(d.rate - truth["Rs"]) / truth["Rs"] < 0.05


@pytest.mark.parametrize("bad,fs", [(np.ones(1000, complex), FS), (np.ones(4096, complex), 0.0),
                                    (np.ones(4096, complex), float("nan")), (np.ones(4096), FS)])
def test_rejects_invalid_input(bad, fs):
    with pytest.raises(ValueError):
        analyze_segment(bad, fs)


def test_isolated_from_product_path_and_rng_free():
    # WP4: the product reaches the estimator only through backend/pipeline/verify_estimator.py
    for sub in ("pipeline", "api"):
        for f in (BACKEND / sub).rglob("*.py"):
            if f.name != "verify_estimator.py":
                assert "experimental" not in f.read_text(), f
    for f in (BACKEND / "experimental").rglob("*.py"):
        assert not re.search(r"\brandom\b|default_rng|np\.random", f.read_text()), f


# ---- WP1: carrier aliasing (the 4th-power line aliases once |carrier| > fs/8)

@pytest.mark.parametrize("carrier", [8000, 15000, -11000])
def test_coarse_carrier_is_not_aliased_above_fs_over_8(carrier):
    from backend.experimental.estimate_spike.dsp import carrier_estimate
    from backend.pipeline.synth_gen import make_signal
    x, _ = make_signal("qpsk", 15, duration=0.5, seed=5, frequency=carrier)
    assert abs(carrier_estimate(np.asarray(x, complex), 48000, DEFAULT.nfft, 4) - carrier) < 20


@pytest.mark.parametrize("kind,label", [("bpsk", "BPSK"), ("qpsk", "QPSK")])
def test_shipped_fixture_at_8khz_is_not_labelled_fm(kind, label):
    from backend.pipeline.synth_gen import make_signal
    x, _ = make_signal(kind, 15, duration=0.5, seed=3, frequency=8000)
    r = analyze_segment(np.asarray(x, complex), 48000)
    d = _decide(r)
    assert d.label != "FM"
    assert d.label == label
    assert abs(r.carrier_hz - 8000) < 20


def test_carrier_hint_is_used_as_the_coarse_estimate():
    from backend.pipeline.synth_gen import make_signal
    x, _ = make_signal("bpsk", 15, duration=0.5, seed=3, frequency=15000)
    r = analyze_segment(np.asarray(x, complex), 48000, carrier_hint=14900.0)
    assert abs(r.carrier_hz - 15000) < 20


# ---- WP2: smoothed pulses must not be reported at 2x / 3x the rate

@pytest.mark.parametrize("kind,sps,carrier,seed", [
    ("bpsk", 24, 0, 1), ("qpsk", 24, 3000, 2), ("bpsk", 48, 8000, 3), ("qpsk", 48, 0, 4),
    ("qpsk", 96, 15000, 5), ("qam", 48, 3000, 6),
])
def test_firwin_smoothed_linear_modulation_reports_true_rate(kind, sps, carrier, seed):
    from experiments.readiness.synth_wide import make_signal
    x, _ = make_signal(kind, 20, carrier, sps, seed, 24000)
    d = _decide(analyze_segment(np.asarray(x, complex), 48000))
    truth = 48000 / sps
    assert d.rate is not None and abs(d.rate - truth) / truth < 0.05, (d.expert, d.rate, truth)
    assert d.label == {"bpsk": "BPSK", "qpsk": "QPSK", "qam": "QAM16"}[kind]


@pytest.mark.parametrize("alpha", [0.2, 0.5, 1.0])
def test_rrc_rolloffs_outside_the_old_library_report_true_rate(alpha):
    from backend.experimental.estimate_spike.dsp import rrc_pulse
    rng = np.random.default_rng(int(alpha * 10))
    sps, n, rate = 10.0, 8192, 1e5
    sy = rng.choice([-1.0, 1.0], n // 10 + 40) + 1j * rng.choice([-1.0, 1.0], n // 10 + 40)
    tt = np.arange(n) / sps
    k0 = np.floor(tt).astype(int)
    s = sum(sy[k0 + d + 10] * rrc_pulse(tt - (k0 + d), alpha) for d in range(-8, 9))
    s = s / np.sqrt(np.mean(np.abs(s) ** 2)) * np.exp(2j * np.pi * 0.03 * np.arange(n))
    x = s + (rng.standard_normal(n) + 1j * rng.standard_normal(n)) * np.sqrt(0.01 / 2)
    d = _decide(analyze_segment(x, 1e6))
    assert d.rate is not None and abs(d.rate - rate) / rate < 0.05, (d.expert, d.rate)
    assert d.label == "QPSK"


# ---- WP3: library gaps (8PSK, 4-FSK) and the FM sink

def _wide(kind, snr, fc, sps, seed):
    from experiments.readiness.synth_wide import make_signal
    x, _ = make_signal(kind, snr, fc, sps, seed, 24000)
    return _decide(analyze_segment(np.asarray(x, complex), 48000))


@pytest.mark.parametrize("sps,fc,seed", [(24, 3000, 1), (48, 8000, 2), (12, 0, 3)])
def test_8psk_is_labelled_8psk(sps, fc, seed):
    d = _wide("8psk", 20, fc, sps, seed)
    assert d.label == "8PSK" and d.label_shipped, d
    assert abs(d.rate - 48000 / sps) / (48000 / sps) < 0.05


@pytest.mark.parametrize("sps,fc,seed", [(24, 3000, 1), (48, 15000, 2), (12, 0, 3)])
def test_4fsk_is_labelled_fsk4_not_fm(sps, fc, seed):
    d = _wide("fsk", 20, fc, sps, seed)
    assert d.label == "FSK4" and d.label_shipped, d


@pytest.mark.parametrize("seed", [1, 2])
def test_fm_is_still_labelled_fm(seed):
    d = _wide("fm", 20, 3000, 96, seed)
    assert d.label == "FM" and d.label_shipped
    x, _ = generate(np.random.default_rng(seed), "FM", snr_db=13.0)
    assert _decide(analyze_segment(x, FS)).label == "FM"


def test_discrete_frequency_levels_outside_the_library_are_never_published_as_fm():
    # 8-FSK is not in the library: FM would explain it, but its IF sits on discrete levels
    rng = np.random.default_rng(8)
    fs, sps, n = 48000, 24, 24000
    dev = (fs / sps) * (np.arange(8) - 3.5) * 0.4
    f = np.repeat(dev[rng.integers(0, 8, n // sps + 1)], sps)[:n]
    x = np.exp(2j * np.pi * (np.cumsum(f) / fs + 3000 * np.arange(n) / fs))
    x = x * 10 + (rng.standard_normal(n) + 1j * rng.standard_normal(n)) / np.sqrt(2)
    d = _decide(analyze_segment(x, fs))
    assert not (d.label == "FM" and d.label_shipped), d


def _qam_capture(points, seed, snr=20.0, sps=10, n=8192):
    rng = np.random.default_rng(seed)
    sy = points[rng.integers(0, len(points), n // sps + 2)]
    s = np.repeat(sy, sps)[:n]
    s = s / np.sqrt(np.mean(np.abs(s) ** 2)) * np.exp(2j * np.pi * 0.02 * np.arange(n))
    return s + (rng.standard_normal(n) + 1j * rng.standard_normal(n)) * np.sqrt(10 ** (-snr / 10) / 2)


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_subset_constellation_is_not_published_with_the_full_alphabet_label(seed):
    # rectangular 8-QAM is a subset of the 16-QAM grid: the model fits, but half the points are unused
    rect8 = (np.array([-3, -1, 1, 3.0])[:, None] + 1j * np.array([-1, 1.0])[None, :]).ravel()
    d = _decide(analyze_segment(_qam_capture(rect8, seed), FS))
    assert not (d.label_shipped and d.label == "QAM16"), d


@pytest.mark.parametrize("seed", [1, 2])
def test_full_16qam_is_still_published(seed):
    grid = (np.array([-3, -1, 1, 3.0])[:, None] + 1j * np.array([-3, -1, 1, 3.0])[None, :]).ravel()
    d = _decide(analyze_segment(_qam_capture(grid, seed), FS))
    assert d.label == "QAM16" and d.label_shipped, d


# ---- WP3b: 2-level ASK (unipolar) joins the library; it must not be published as AM

@pytest.mark.parametrize("sps,fc,seed", [(24, 3000, 1), (48, 8000, 2), (12, 0, 3)])
def test_unipolar_ask_is_labelled_ask_not_am(sps, fc, seed):
    d = _wide("ask", 20, fc, sps, seed)
    assert not (d.label == "AM" and d.label_shipped), d
    # the winner; publication is decided by the calibrated thresholds (scoreboard), not the spike default
    assert d.label == "ASK2", d
    assert abs(d.rate - 48000 / sps) / (48000 / sps) < 0.05


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_am_is_not_labelled_ask(seed):
    x, _ = generate(np.random.default_rng(seed), "AM", snr_db=13.0)
    d = _decide(analyze_segment(x, FS))
    assert d.label != "ASK2" or not d.label_shipped, d


@pytest.mark.parametrize("seed", [100582, 100581, 7])
def test_4fsk_timing_does_not_depend_on_the_2fsk_optimum(seed):
    # a 2-FSK model fits 4-FSK badly, so its timing optimum is no start for 4 tones
    from experiments.readiness.synth_wide import make_signal
    x, _ = make_signal("fsk", 20, 0, 12, seed, 8192)
    x = np.asarray(x, complex)
    fsk = FskExpert(DEFAULT)
    exact = fsk.fit(x, x, 48000, 4000.0)
    assert exact.label == "FSK4"
    for rate in (4000 * (1 - 1e-5), 4000 * (1 + 1e-5), 4000 * (1 - 3e-5)):
        assert fsk.fit(x, x, 48000, rate).score <= exact.score + 0.05


@pytest.mark.parametrize("seed,m", [(100600, 3), (100601, 2), (11, 3)])
def test_fsk_fit_at_a_rate_multiple_reports_the_true_rate(seed, m):
    # at m x the rate, tone changes only fall on every m-th symbol boundary
    from experiments.readiness.synth_wide import make_signal
    x, _ = make_signal("fsk", 20, 0, 48, seed, 8192)
    x = np.asarray(x, complex)
    h = FskExpert(DEFAULT).fit(x, x, 48000, 1000.0 * m)
    assert h is not None and abs(h.rate - 1000) / 1000 < 0.05, h
