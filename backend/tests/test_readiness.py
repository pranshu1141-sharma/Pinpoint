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
    # WP2 criteria (registered before first measured)
    assert th.g4_label_wrong_max == 0.03 and th.g4_label_correct_min == 0.60
    assert th.g4_ool_wrong_max == 0.10 and th.g4_rate_wrong_max == 0.03
    assert th.real_correct_min == 0.50 and th.real_wrong_max == 0.05 and th.real_rate_wrong_max == 0.05
    assert th.throughput_rtf_max == 1.0
    # WP4a bounds criteria (registered 2026-09-29, before first measured on test data)
    assert th.bounds_ratio_lo == 0.5 and th.bounds_ratio_hi == 2.0
    assert th.bounds_ok_min_g4 == 0.85 and th.g4_fragmentation_max == 0.05 and th.bounds_ok_min_g5 == 0.60


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
    assert gen_marks([c]) == {"G1": True, "G2": False, "G3": None, "G4": None, "G5": None}
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


def test_real_recording_checks_apply_the_manifest_rules():
    from experiments.readiness.real import sanity
    entry = {"allowed_labels": ["BPSK"], "expected_rate_hz": 50000, "min_detections": 1,
             "overlap_band_hz": [-1000, 1000], "require_pulsed": True,
             "bandwidth_99pct_range_hz": [100, 5000], "min_wide_detections": {"count": 1, "bandwidth_99pct_hz": 200}}
    good = [{"modulation_label": "BPSK", "symbol_rate_hz": 50500, "freq_lower_hz": -800, "freq_upper_hz": 900,
             "is_pulsed": True, "bandwidth_99pct_hz": 1500}]
    ok, notes = sanity(entry, good)
    assert ok, notes
    bad = [dict(good[0], modulation_label="QPSK"), dict(good[0], symbol_rate_hz=100000)]
    ok, notes = sanity(entry, bad)
    assert not ok and any("QPSK" in n for n in notes) and any("rate" in n for n in notes)
    assert not sanity(entry, [])[0]
    assert not sanity(entry, [dict(good[0], is_pulsed=False)])[0]


def test_docs_check_flags_stale_status_prose_and_a_wrong_window_cap(tmp_path):
    from experiments.readiness import docs_check
    (tmp_path / "docs").mkdir()
    (tmp_path / "backend/pipeline").mkdir(parents=True)
    (tmp_path / "backend/pipeline/verify_estimator.py").write_text("MAX_SAMPLES = 4096      # cap\\n")
    (tmp_path / "docs/CLAIMS.md").write_text("x\\n")
    (tmp_path / "docs/PROJECT_STATUS.md").write_text("<!-- readiness:start -->\\n```\\n```\\n<!-- readiness:end -->\\n")
    (tmp_path / "docs/LIMITATIONS_AND_ROADMAP.md").write_text("An experimental alternative is under test in `backend/experimental/`.\\n")
    (tmp_path / "README.md").write_text("It caps the window at 8,192 samples.\\n")
    ok, problems = docs_check.check({"bars": "```\\n```"}, tmp_path)
    assert any("LIMITATIONS" in p and "under test" in p for p in problems)
    assert any("8,192" in p and "4,096" in p for p in problems)


def test_docs_check_covers_the_docs_index_and_judge_guide(tmp_path):
    """X1 (WP1): docs/README.md and JUDGE_DEFENSE_GUIDE.md may not deny that the product names
    modulation, and no checked doc may say long tracks stay null once sampled spans exist."""
    from experiments.readiness import docs_check
    (tmp_path / "docs").mkdir()
    (tmp_path / "backend/pipeline").mkdir(parents=True)
    (tmp_path / "backend/pipeline/verify_estimator.py").write_text("")
    (tmp_path / "backend/pipeline/large_capture.py").write_text("")
    (tmp_path / "docs/CLAIMS.md").write_text("x\n")
    (tmp_path / "docs/PROJECT_STATUS.md").write_text("<!-- readiness:start -->\n```\n```\n<!-- readiness:end -->\n")
    (tmp_path / "docs/README.md").write_text("Non-purpose: this version does not identify modulation.\n")
    (tmp_path / "docs/JUDGE_DEFENSE_GUIDE.md").write_text(
        "## Claims to avoid\n- \u201cIt identifies BPSK/QPSK/FM.\u201d\n")
    (tmp_path / "docs/LIMITATIONS_AND_ROADMAP.md").write_text("Long tracks keep unresolved downstream fields.\n")
    ok, problems = docs_check.check({"bars": "```\n```"}, tmp_path)
    assert any("docs/README.md" in p and "does not identify modulation" in p for p in problems)
    assert any("JUDGE_DEFENSE_GUIDE" in p and "it identifies bpsk/qpsk/fm" in p for p in problems)
    # the long-track phrase is only false once sampled spans exist in the code
    assert not any("unresolved downstream" in p for p in problems)
    (tmp_path / "backend/pipeline/large_capture.py").write_text("def sampled_spans(track, budget):\n")
    ok, problems = docs_check.check({"bars": "```\n```"}, tmp_path)
    assert any("LIMITATIONS" in p and "keep unresolved downstream fields" in p for p in problems)


def test_fm_label_share_is_reported():
    from experiments.readiness import metrics
    rows = [_row("FM", "FM"), _row("FM", None), _row("FM", "BPSK"), _row("BPSK", "BPSK", 1e3)]
    assert metrics.confidence_stats(rows)["fm_labelled"] == pytest.approx(1 / 3)


def test_g5_split_is_frozen_and_by_protocol():
    """WP2: the G5 calibration/test split may not change, and no protocol is on both sides."""
    import json
    from pathlib import Path
    from experiments.readiness import g5_build
    m = json.loads((Path(config.__file__).with_name(config.G5_MANIFEST)).read_text())
    rec = m["recordings"]
    assert g5_build.split_digest(rec) == m["split_sha256"] == config.G5_SPLIT_SHA256
    sides = {}
    for e in rec:
        sides.setdefault(e["protocol"], set()).add(e["split"])
        assert e["allowed_labels"] == ([e["truth"]["label"]] if e["truth"]["label"] else [])
    assert all(len(s) == 1 for s in sides.values())
    assert sides["ais"] == {"test"}


def _claims_dir(tmp_path, marker_line):
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs/CLAIMS.md").write_text(marker_line + "\n")
    (tmp_path / "docs/PROJECT_STATUS.md").write_text(
        "status\n<!-- readiness:start -->\n```\nDetect ███\n```\n<!-- readiness:end -->\n")


_TIMED = {"bars": "```\nDetect ███\n```", "stats": {"verify": {"G2": {"speed": {"within": 0.888},
                                                                        "label": {"published_wrong": 0.005}}}}}


def test_docs_check_gives_timing_markers_a_tolerance_but_not_accuracy_markers(tmp_path):
    """X1 (WP3b): a wall-clock figure may drift by 5 points between runs; an accuracy figure must match exactly."""
    from experiments.readiness import docs_check
    _claims_dir(tmp_path, "speed <!--rj:stats.verify.G2.speed.within--> 90.4%")
    assert docs_check.check(_TIMED, tmp_path) == (True, [])                       # 1.6 points off: noise
    (tmp_path / "docs/CLAIMS.md").write_text("speed <!--rj:stats.verify.G2.speed.within--> 93.0%\n")
    assert docs_check.check(_TIMED, tmp_path) == (True, [])                       # 4.2 points: inside the measured run-to-run spread
    (tmp_path / "docs/CLAIMS.md").write_text("speed <!--rj:stats.verify.G2.speed.within--> 80.0%\n")
    ok, problems = docs_check.check(_TIMED, tmp_path)
    assert not ok and any("speed.within" in p for p in problems)                  # 8.8 points off: stale
    (tmp_path / "docs/CLAIMS.md").write_text("wrong <!--rj:stats.verify.G2.label.published_wrong--> 0.6%\n")
    ok, problems = docs_check.check(_TIMED, tmp_path)
    assert not ok and any("published_wrong" in p for p in problems)               # 0.1 points off: still exact-match


def test_unknown_family_text_names_impairment_not_a_new_family():
    """WP3b: the tier fires on impaired in-library signals, so its text may not claim the structure is outside the library."""
    from backend.pipeline import verify_estimator as ve
    status = ve.tier_status("unknown_family")
    family = ve.tier_family("unknown_family", "PSK")
    for text in (status, family):
        assert "impairment" in text and "outside the library" not in text
    assert ve.tier_family("unknown_family", ve.UNKNOWN_CE) == "unknown constant-envelope family"
    assert ve.tier_family("labelled", "PSK") == "PSK" and ve.tier_family("abstain", "PSK") is None
    assert ve.tier_status("abstain").startswith("not reliably estimated")


# --- G4 per-impairment ablation (WP3b): switches must not change any RNG draw --------------------------------------
_G4_CASES = (("qpsk", 16, 10, 500001, "c3381df6dada04c5", "53448dab22efa58a"),
             ("fsk2", 32, 5, 500002, "f8d114627fa92e29", "2644e4b7d205d18b"),
             ("noise", 16, 0, 500003, "0de0468dd87f19eb", "2daeb1f36095b44b"))


@pytest.mark.parametrize("kind,sps,snr,seed,y_hash,clean_hash", _G4_CASES)
def test_g4_default_output_is_bit_identical_to_the_frozen_generator(kind, sps, snr, seed, y_hash, clean_hash):
    import hashlib
    from experiments.readiness import impaired
    y, clean, _ = impaired.make_capture(kind, snr, sps, seed)
    assert hashlib.sha256(y.tobytes()).hexdigest()[:16] == y_hash
    assert hashlib.sha256(np.asarray(clean).tobytes()).hexdigest()[:16] == clean_hash


def _g4(impairments, kind="qpsk", sps=16, snr=10, seed=500001):
    from experiments.readiness import impaired
    y, clean, info = impaired.make_capture(kind, snr, sps, seed, impairments=frozenset(impairments))
    return y.astype(np.complex128), np.asarray(clean), info


def test_g4_impairment_names_are_the_documented_eight():
    from experiments.readiness import impaired
    assert set(impaired.IMPAIRMENTS) == {"multipath", "drift", "phase_noise", "interferer", "colour", "iq", "dc", "clip"}


def test_g4_dc_switch_adds_exactly_a_constant():
    y0, _, _ = _g4(())
    y1, _, info = _g4({"dc"})
    d = y1 - y0
    assert np.ptp(d.real) < 1e-4 and np.ptp(d.imag) < 1e-4 and abs(d.mean()) > 0


def test_g4_iq_switch_applies_the_stated_imbalance_to_the_unimpaired_capture():
    y0, _, _ = _g4(())
    y1, _, info = _g4({"iq"})
    g, phi = 10 ** (info["iq_gain_db"] / 20), np.deg2rad(info["iq_phase_deg"])
    mu, nu = (1 + g * np.exp(-1j * phi)) / 2, (1 - g * np.exp(1j * phi)) / 2
    assert np.allclose(y1, mu * y0 + nu * np.conj(y0), atol=1e-4)


@pytest.mark.parametrize("only", ["multipath", "drift", "phase_noise"])
def test_g4_emitter_impairments_change_the_signal_but_not_the_noise(only):
    y0, c0, _ = _g4(())
    y1, c1, _ = _g4({only})
    assert not np.allclose(c0, c1)                                   # the emitter changed
    assert np.allclose(y0 - c0, y1 - c1, atol=1e-4)                   # same noise draw, so runs are paired
    assert np.mean(np.abs(c1) ** 2) == pytest.approx(np.mean(np.abs(c0) ** 2), rel=0.5)


def test_g4_interferer_switch_adds_power_only_when_on_and_leaves_the_target_alone():
    y0, c0, _ = _g4(())
    y1, c1, info = _g4({"interferer"})
    assert np.allclose(c0, c1)
    assert info["interferer"] is not None and np.mean(np.abs(y1 - y0) ** 2) > 0


def test_g4_clip_switch_clips_only_when_on():
    _, _, i0 = _g4((), seed=500005)          # a seed where clipping actually occurs (about 0.03% of samples)
    _, _, i1 = _g4({"clip"}, seed=500005)
    assert i0["clipped_fraction"] == 0 and i1["clipped_fraction"] > 0


def test_g4_colour_switch_adds_noise_correlation():
    y0, c0, _ = _g4(())
    y2, c2, _ = _g4({"colour"})
    n0, n2 = y0 - c0, y2 - c2
    assert abs(np.mean(n0[1:] * np.conj(n0[:-1]))) < abs(np.mean(n2[1:] * np.conj(n2[:-1])))


def test_ablation_summary_counts_abstentions_wrong_labels_and_unknown_tier():
    from experiments.readiness import ablation

    def row(truth, label, tier, hit=True, n_overlap=1):
        return dict(truth=dict(label=truth, in_library=True), out=dict(label=label, tier=tier),
                    detect=dict(hit=hit, n_overlap=n_overlap))
    rows = [row("QPSK", "QPSK", "labelled"), row("QPSK", "QAM16", "labelled"), row("BPSK", None, "unknown_family"),
            row("BPSK", None, "abstain", n_overlap=3), row("8PSK", None, "abstain", hit=False)]
    s = ablation.summarize(rows)
    assert s["n"] == 5 and s["correct"] == pytest.approx(1 / 5) and s["wrong"] == pytest.approx(1 / 5)
    assert s["abstain"] == pytest.approx(3 / 5) and s["unknown_tier"] == pytest.approx(1 / 5)
    assert s["fragmented"] == pytest.approx(1 / 5) and s["detect_miss"] == pytest.approx(1 / 5)


def test_ablation_refuses_test_seeds_and_names_every_condition_once():
    from experiments.readiness import ablation, generators
    with pytest.raises(SystemExit):
        ablation.main(["--seed-base", str(generators.G4_TEST_SEED_BASE)])
    names = [name for name, _ in ablation.conditions()]
    assert len(names) == len(set(names)) and "none" in names and "all" in names
    assert {"only:drift", "only:iq", "only:multipath", "without:iq"} <= set(names)


def test_ablation_summary_reports_how_often_detect_bounds_are_too_wide():
    from experiments.readiness import ablation

    def row(width, bands):
        return dict(truth=dict(label="QPSK", in_library=True, band=[0.0, width]),
                    out=dict(label=None, tier="abstain"), detect=dict(hit=True, n_overlap=1, bands=bands))
    rows = [row(10e3, [[0.0, 12e3]]),            # 1.2x: fine
            row(10e3, [[0.0, 30e3]]),            # 3x: too wide
            row(10e3, [[-5e3, 2e3], [1e3, 9e3]]),  # best overlap 8 kHz band: 0.8x
            row(10e3, [[0.0, 4e3]])]             # 0.4x: too narrow
    s = ablation.summarize(rows)
    assert s["too_wide"] == pytest.approx(1 / 4) and s["too_narrow"] == pytest.approx(1 / 4)


def test_ablation_summary_separates_bad_bounds_from_bad_estimates():
    from experiments.readiness import ablation

    def row(width, label):
        return dict(truth=dict(label="QPSK", in_library=True, band=[0.0, 10e3]),
                    out=dict(label=label, tier="labelled" if label else "abstain"),
                    detect=dict(hit=True, n_overlap=1, bands=[[0.0, width]]))
    rows = [row(11e3, "QPSK"), row(11e3, None), row(12e3, None), row(40e3, "QPSK")]   # 3 good bounds (1 correct), 1 too wide
    s = ablation.summarize(rows)
    assert s["correct_given_ok_bounds"] == pytest.approx(1 / 3) and s["ok_bounds"] == pytest.approx(3 / 4)
    assert ablation.compact(rows[0]) == dict(truth="QPSK", label="QPSK", tier="labelled", width_ratio=1.1, n_overlap=1)


def test_bounds_stats_use_the_registered_ratio_window_and_count_splits():
    from experiments.readiness.metrics import bounds_stats

    def row(bands, n_overlap=1, label="BPSK"):
        return {"truth": {"label": label, "band": (0.0, 100.0)}, "detect": {"bands": bands, "n_overlap": n_overlap}}
    rows = [row([(0, 100)]), row([(0, 250)]), row([(40, 80)]), row([(0, 49)]), row([(0, 100), (120, 130)], n_overlap=2),
            row([(500, 600)]), {"truth": {"label": "noise", "band": None}, "detect": {"bands": [], "n_overlap": 0}}]
    s = bounds_stats(rows)
    assert s["n"] == 6                                   # noise excluded
    assert s["ok_bounds"] == 2 / 6                       # the two 1.0x bands; a band missing the truth is not ok
    assert s["too_wide"] == 1 / 6 and s["too_narrow"] == 2 / 6
    assert s["fragmented"] == 1 / 6


def test_b3_criterion_scores_the_count_and_is_not_applicable_without_data(tmp_path, monkeypatch):
    from experiments.readiness import fsk_split_probe, scoreboard
    c = scoreboard.b3_criterion((15, 25))
    assert c["id"] == "B3" and c["passed"] and c["gens"]["G5"] == {"value": 0.6, "passed": True, "n": 25}
    assert not scoreboard.b3_criterion((14, 25))["passed"]
    monkeypatch.setattr(fsk_split_probe, "OUT", tmp_path / "missing.json")
    missing = scoreboard.b3_criterion(None)
    assert missing["passed"] is False and missing["gens"]["G5"]["passed"] is None
