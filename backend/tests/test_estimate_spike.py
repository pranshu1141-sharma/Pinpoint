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
    pytest.param("AM", dict(), "analog", "AM", marks=pytest.mark.xfail(strict=True, reason=(
        "Known weak spot: the analog expert takes the carrier from the FFT-bin argmax (up to ~120 Hz "
        "off at 4096 samples), so the fixed-phase AM model cannot absorb the residual rotation."))),
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
    assert fsk.fit(x, xc, FS, 80e3).score < fsk.fit(x, xc, FS, 160e3).score


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
    for sub in ("pipeline", "api"):
        for f in (BACKEND / sub).rglob("*.py"):
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
