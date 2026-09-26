"""Readiness scoreboard (experiments/readiness): generators, scoring rules and bar rendering."""
import numpy as np
import pytest

from experiments.readiness import config, generators, metrics
from experiments.readiness.render import render_bar


def test_bar_matches_the_specified_format():
    line = render_bar("Modulation label", 2, 5, {"G1": True, "G2": False, "G3": None}, width=19)
    assert line == "Modulation label   ████░░░░░░  40%  (2/5 criteria)  [G1 ✓ G2 ✗ G3 –]"


def test_bar_rounds_down_partial_blocks_and_handles_zero_criteria():
    assert render_bar("Speed", 1, 3, {"G1": None}, width=8).startswith("Speed   ███░░░░░░░  33%")
    assert "  0%  (0/0 criteria)" in render_bar("Docs", 0, 0, {}, width=6)


def test_thresholds_are_frozen_constants():
    th = config.THRESHOLDS
    assert th.detect_recall_min == 0.95 and th.detect_noise_false_max == 0.05
    assert th.detect_fragmentation_max == 0.05 and th.cf_err_frac_bw == 0.10
    assert th.bw3_tol == 0.25 and th.snr_err_db == 2.0 and th.label_wrong_max == 0.03
    assert th.label_correct_min == 0.60 and th.rate_wrong_max == 0.03 and th.rate_correct_min == 0.50
    assert th.ool_wrong_max == 0.10 and th.speed_s == 0.5 and th.min_snr_db == 5.0
    with pytest.raises(Exception):
        th.speed_s = 1.0


@pytest.mark.parametrize("pred,truth,ok", [
    ("BPSK", "BPSK", True), ("QPSK", "BPSK", False), ("QAM", "QAM16", True), ("QAM16", "QAM16", True),
    ("FSK", "FSK4", True), ("FSK2", "FSK4", False), ("FSK2", "FSK2", True), ("ASK", "ASK2", True),
    ("FM", "FM", True), ("BPSK", "noise", False), ("QAM64", "QAM16", False), ("8PSK", "8PSK", True),
])
def test_label_matching(pred, truth, ok):
    assert metrics.label_matches(pred, truth) is ok


def test_rate_matching_uses_five_percent_and_flags_harmonics():
    assert metrics.rate_matches(1040.0, 1000.0) and not metrics.rate_matches(1060.0, 1000.0)
    assert metrics.harmonic_error(2010.0, 1000.0) and metrics.harmonic_error(2990.0, 1000.0)
    assert not metrics.harmonic_error(1000.0, 1000.0) and not metrics.harmonic_error(1500.0, 1000.0)


def test_g2_capture_truth_is_consistent_with_the_samples():
    cap = generators.g2_capture("qpsk", snr_db=20, carrier_hz=8000, sps=24, seed=11)
    t = cap.truth
    assert cap.fs == 48000 and t["label"] == "QPSK" and t["rate"] == pytest.approx(2000.0)
    assert t["fc"] == 8000 and t["digital"] and t["linear"]
    # measured full-band SNR equals the request (signal power / complex-noise power)
    assert 10 * np.log10(np.mean(np.abs(cap.clean) ** 2) / np.mean(np.abs(cap.x - cap.clean) ** 2)) == \
        pytest.approx(20, abs=0.3)
    spec = np.abs(np.fft.fftshift(np.fft.fft(cap.clean))) ** 2
    f = np.fft.fftshift(np.fft.fftfreq(len(cap.clean), 1 / cap.fs))
    assert abs(np.sum(f * spec) / np.sum(spec) - 8000) < 100
    # NRZ smoothed by a 1.8*Rs lowpass keeps the sinc^2 main lobe: -3 dB width ~0.886 Rs
    assert t["bw3"] == pytest.approx(0.886 * 2000, rel=0.05)
    again = generators.g2_capture("qpsk", snr_db=20, carrier_hz=8000, sps=24, seed=11)
    assert np.array_equal(cap.x, again.x)


def test_g2_grid_covers_the_widened_family_with_distinct_test_seeds():
    specs = generators.g2_specs()
    digital = [s for s in specs if s["kind"] in ("bpsk", "qpsk", "8psk", "qam", "fsk", "ask")]
    assert {s["carrier_hz"] for s in digital} == {0, 3000, 8000, 15000}
    assert {s["sps"] for s in digital} == {12, 24, 48, 96}
    assert {s["snr_db"] for s in digital} == {5, 10, 20}
    assert len(digital) == 6 * 4 * 4 * 3 * 3
    assert len({s["seed"] for s in specs}) == len(specs)
    assert not {s["seed"] for s in specs} & set(generators.G2_CALIBRATION_SEEDS)


def test_g1_truth_replay_recovers_carrier_and_clean_signal():
    caps = list(generators.g1_captures(12, seed=7))
    assert len(caps) == 12
    for cap in caps:
        t = cap.truth
        noise = cap.x - cap.clean
        if t["label"] == "noise":
            assert np.allclose(cap.clean, 0)
            continue
        assert np.mean(np.abs(cap.clean) ** 2) == pytest.approx(1.0, rel=1e-6)
        assert 10 * np.log10(1 / np.mean(np.abs(noise) ** 2)) == pytest.approx(t["snr_db"], abs=0.6)
        assert abs(t["fc"]) <= 1e5
    assert [c.truth["label"] for c in caps] == [c.truth["label"] for c in generators.g1_captures(12, seed=7)]


def _row(label, pred=None, rate=None, pred_rate=None, snr=10.0, gen="G1"):
    return dict(gen=gen, truth=dict(label=label, rate=rate, snr_db=snr,
                                    digital=rate is not None, in_library=label in config.IN_LIBRARY,
                                    out_of_library=label in config.OUT_OF_LIBRARY),
                out=dict(label=pred, rate=pred_rate))


def test_label_criteria_count_published_wrong_over_all_captures():
    rows = [_row("BPSK", "BPSK", 1e3), _row("BPSK", "QPSK", 1e3), _row("noise", None),
            _row("QPSK", None, 1e3)]
    s = metrics.label_stats(rows)
    assert s["published_wrong"] == pytest.approx(1 / 4)
    assert s["published_correct_in_library"] == pytest.approx(1 / 3)


def test_rate_criteria_and_noise_labels():
    rows = [_row("BPSK", "BPSK", 1e3, 1e3), _row("QPSK", "QPSK", 1e3, 2e3), _row("noise", "BPSK"),
            _row("FSK8", "BPSK", 1e3, None)]
    r = metrics.rate_stats(rows)
    assert r["published_wrong"] == pytest.approx(1 / 4) and r["published_correct_digital"] == pytest.approx(1 / 3)
    assert r["harmonic_errors"] == pytest.approx(1 / 3)
    c = metrics.confidence_stats(rows)
    assert c["noise_labelled"] == pytest.approx(1.0) and c["ool_wrong"] == pytest.approx(1.0)


def test_calibrated_wording_detector():
    assert metrics.claims_calibration({"x": "isotonic-calibrated on synthetic corpus"})
    assert not metrics.claims_calibration({"x": "heuristic, not a calibrated probability",
                                           "y": "uncalibrated (no fitted calibrator file present)"})


def test_docs_check_flags_missing_claims_stale_markers_and_contradictions(tmp_path):
    from experiments.readiness import docs_check
    (tmp_path / "docs").mkdir()
    (tmp_path / "backend/pipeline").mkdir(parents=True)
    (tmp_path / "backend/pipeline/classify.py").write_text("")
    readiness = {"bars": "```\nDetect ███\n```", "stats": {"shipped": {"G1": {"label": {"published_wrong": 0.25}}}}}
    ok, problems = docs_check.check(readiness, tmp_path)
    assert not ok and "docs/CLAIMS.md is missing" in problems
    (tmp_path / "docs/CLAIMS.md").write_text("wrong rate <!--rj:stats.shipped.G1.label.published_wrong--> 10.0%\n")
    (tmp_path / "docs/PROJECT_STATUS.md").write_text(
        "status\n<!-- readiness:start -->\n```\nDetect ███\n```\n<!-- readiness:end -->\n")
    (tmp_path / "README.md").write_text("PinPoint does not classify modulation.\nvalidated 30/30 within 5%\n")
    ok, problems = docs_check.check(readiness, tmp_path)
    assert any("says 10.0%, readiness.json has 25.0%" in p for p in problems)
    assert any("does not classify modulation" in p for p in problems)
    assert any("unconditional claim" in p for p in problems)
    (tmp_path / "docs/CLAIMS.md").write_text("wrong rate <!--rj:stats.shipped.G1.label.published_wrong--> 25.0%\n")
    (tmp_path / "README.md").write_text("Classifies on synthetic fixtures: 30/30 at >= 4.5 dB on synth_gen fixtures.\n")
    assert docs_check.check(readiness, tmp_path) == (True, [])


def test_criterion_passes_only_when_every_applicable_generator_passes():
    from experiments.readiness.scoreboard import _crit, gen_marks
    c = _crit("L1", "x", {"G1": (0.01, True, 10), "G2": (0.2, False, 10), "G3": (None, None, 0)})
    assert not c["passed"]
    assert gen_marks([c]) == {"G1": True, "G2": False, "G3": None}
    assert _crit("L1", "x", {"G1": (0.01, True, 10), "G3": (None, None, 0)})["passed"]
    assert not _crit("L1", "x", {"G3": (None, None, 0)})["passed"]


def test_library_after_wp3_and_held_out_block():
    assert {"8PSK", "FSK4"} <= config.IN_LIBRARY and not {"8PSK", "FSK4"} & config.OUT_OF_LIBRARY
    assert config.OUT_OF_LIBRARY == {"FSK8", "QAM8"}
    specs = generators.g2_specs()
    held = [s for s in specs if s["kind"] in ("fsk8", "qam8")]
    assert len(held) == 2 * 4 * 4 * 3
    # the held-out block is appended: the original grid keeps its seeds
    assert [s["seed"] for s in specs[:len(specs) - len(held)]] == \
        list(range(generators.G2_TEST_SEED_BASE, generators.G2_TEST_SEED_BASE + len(specs) - len(held)))
    cap = generators.g2_capture("qam8", 20, 3000, 24, held[0]["seed"])
    assert cap.truth["label"] == "QAM8" and cap.truth["out_of_library"] and cap.truth["rate"] == 2000
    cap = generators.g2_capture("fsk8", 20, 0, 24, held[1]["seed"])
    assert cap.truth["label"] == "FSK8" and not cap.truth["linear"]


def test_docs_sync_rewrites_bars_and_claim_values_and_check_ignores_the_docs_line(tmp_path):
    from experiments.readiness import docs_check
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs/PROJECT_STATUS.md").write_text(
        "intro\n<!-- readiness:start -->\nold\n<!-- readiness:end -->\nrest\n")
    (tmp_path / "docs/CLAIMS.md").write_text("wrong <!--rj:stats.verify.G1.label.published_wrong--> 9.9% (G1)\n")
    bars = "```\nDetect ██\nDocs ░░\n--\nOverall ██\n```"
    readiness = {"bars": bars, "stats": {"verify": {"G1": {"label": {"published_wrong": 0.0033}}}}}
    docs_check.sync(readiness, tmp_path)
    status = (tmp_path / "docs/PROJECT_STATUS.md").read_text()
    assert bars in status and "old" not in status and status.endswith("rest\n")
    assert "--> 0.3% (G1)" in (tmp_path / "docs/CLAIMS.md").read_text()
    # the Docs and Overall lines may differ (the docs criterion itself changes them)
    readiness["bars"] = "```\nDetect ██\nDocs ██\n--\nOverall ███\n```"
    assert docs_check.check(readiness, tmp_path) == (True, [])
