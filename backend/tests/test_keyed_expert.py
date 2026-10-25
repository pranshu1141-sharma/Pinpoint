"""Rate-free keyed two-level expert: wins on keyed bursts with irregular widths, never on analog, carrier or noise."""
import numpy as np
import pytest

from backend.experimental.estimate_spike import analyze_segment
from backend.experimental.estimate_spike.config import DEFAULT
from backend.experimental.estimate_spike.expert_keyed import KeyedExpert, _runs
from backend.pipeline import verify_estimator as ve

FS, N = 100e3, 4096
T = np.arange(N) / FS


def _noise(rng, sigma):
    return sigma * (rng.standard_normal(N) + 1j * rng.standard_normal(N))


def _ook(seed):
    """On pulses and gaps of random, non-commensurate widths (no single symbol rate fits)."""
    rng = np.random.default_rng(seed)
    s, i = np.zeros(N), 100
    while i < N - 200:
        w = int(rng.integers(11, 53))
        s[i:i + w] = 1
        i += w + int(rng.integers(17, 41))
    return s * np.exp(2j * np.pi * 3e3 * T + 1j) + _noise(rng, 0.1)


def _fsk(seed):
    rng = np.random.default_rng(seed)
    st, i, v = np.zeros(N, bool), 0, False
    while i < N:
        w = int(rng.integers(13, 57))
        st[i:i + w] = v
        v, i = not v, i + w
    return np.exp(1j * np.cumsum(2 * np.pi * np.where(st, 8e3, -8e3) / FS)) + _noise(rng, 0.1)


def _best(x):
    return min(analyze_segment(x, FS, carrier_hint=0.0).hypotheses, key=lambda h: h.score)


@pytest.mark.parametrize("seed", [0, 1, 2])
def test_irregular_keyed_bursts_are_explained_by_the_keyed_expert(seed):
    ook, fsk = _best(_ook(seed)), _best(_fsk(seed))
    assert (ook.expert, ook.label, ook.rate) == ("keyed", "ASK2", None)
    assert (fsk.expert, fsk.label, fsk.rate) == ("keyed", "FSK2", None)


def test_keyed_expert_never_wins_on_analog_carrier_or_noise():
    rng = np.random.default_rng(5)
    msg = np.convolve(rng.standard_normal(N), np.ones(60) / 60, "same") * 40
    cases = [(1 + 0.6 * np.sin(2 * np.pi * 500 * T)) * np.exp(2j * np.pi * 2e3 * T) + _noise(rng, 0.07),
             np.exp(1j * np.cumsum(2 * np.pi * 3e3 * msg / FS)) + _noise(rng, 0.07),
             np.exp(2j * np.pi * 1e3 * T) + _noise(rng, 0.07),
             _noise(rng, 1.0)]
    for x in cases:
        assert _best(x).expert != "keyed"


def test_fm_must_beat_keyed_hypotheses_too():
    r = analyze_segment(_fsk(0), FS, carrier_hint=0.0)
    keyed = min(h.score for h in r.hypotheses if h.expert == "keyed")
    fm = next(h for h in r.hypotheses if h.label == "FM")
    assert ve.fm_digital_margin(r.hypotheses, fm.score) <= keyed - fm.score


def test_short_runs_merge_into_their_neighbours():
    state = np.array([0, 0, 0, 1, 0, 0, 1, 1, 1, 1, 0, 0, 0], bool)
    assert _runs(state, 2) == [(0, 6, False), (6, 10, True), (10, 13, False)]


def test_pure_carrier_offers_no_keyed_ook_hypothesis():
    hyps = KeyedExpert(DEFAULT).fit(np.exp(2j * np.pi * 1e3 * T) + _noise(np.random.default_rng(9), 0.01), FS)
    assert all(h.label != "ASK2" for h in hyps)
