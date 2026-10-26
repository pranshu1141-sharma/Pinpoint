from io import BytesIO
import json
from pathlib import Path
import time
import numpy as np
from scipy.io import wavfile
from fastapi.testclient import TestClient
from sigmf import SigMFFile
from backend.api import main
from backend.api.main import app
from backend.pipeline.ingest import load_capture, AmbiguousCapture
from backend.pipeline.synth_gen import make_signal, FS
import pytest

client = TestClient(app)

ESTIMATE_FIELDS = {
    "center_frequency_hz", "bandwidth_3db_hz", "bandwidth_99pct_hz",
    "bandwidth_99pct_caveat", "snr_db", "estimate_status", "modulation_family",
    "modulation_confidence", "modulation_confidence_kind", "modulation_status",
    "envelope_variation", "center_frequency_refined_hz", "refinement_order",
    "refinement_sharpness", "refinement_status", "fine_modulation_label",
    "fine_modulation_confidence", "fine_modulation_status", "phase_cluster_spread_rad",
    "envelope_level_count", "frequency_level_count",
    "symbol_rate_hz", "symbol_rate_status",
}


def wav_bytes(x, rate=16000):
    buf = BytesIO()
    wavfile.write(buf, rate, x.astype(np.float32))
    return buf.getvalue()


def test_real_upload_contract_spectrogram_layers_and_export():
    x, _ = make_signal("pulsed")
    r = client.post("/api/analyze", files={"file": ("pulse.iq", x.astype("<c8").tobytes())},
                    data={"sample_rate": FS, "datatype": "cf32_le"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert {"job_id", "detections", "noise_floor_db", "pipeline_log"} <= body.keys()
    job = body["job_id"]
    s = client.get(f"/api/spectrogram/{job}?width=64&height=32").json()
    assert np.shape(s["magnitude_db"]) == (32, 64)
    assert len(s["frequency_edges_hz"]) == 65
    assert len(s["time_edges_seconds"]) == 33
    layers = client.get(f"/api/detections/{job}/0/layers").json()
    assert len(layers) == 4
    assert all(layer["audio_url"] is None for layer in layers)
    assert layers[1]["sample_rate"] < FS
    assert client.get(f"/api/detections/{job}/0/envelope").json()["pri_samples"] == pytest.approx(12000, abs=100)
    sigmf = client.get(f"/api/export/{job}?format=sigmf").json()
    SigMFFile(metadata=sigmf).validate()
    assert sigmf["annotations"][0]["core:sample_count"] > 0
    assert client.get(f"/api/detections/{job}/-1/layers").status_code == 404


def test_rerun_recomputes_detections_with_a_new_margin_without_reupload():
    x, _ = make_signal("pulsed")
    r = client.post("/api/analyze", files={"file": ("pulse.iq", x.astype("<c8").tobytes())},
                    data={"sample_rate": FS, "datatype": "cf32_le", "margin_db": 8})
    assert r.status_code == 200, r.text
    job = r.json()["job_id"]
    loose = client.post(f"/api/jobs/{job}/rerun?margin_db=3")
    assert loose.status_code == 200, loose.text
    assert loose.json()["job_id"] == job
    assert loose.json()["settings"]["margin_db"] == 3
    strict = client.post(f"/api/jobs/{job}/rerun?margin_db=30")
    assert strict.status_code == 200, strict.text
    # A much higher margin can only keep or shrink the candidate set.
    assert len(strict.json()["detections"]) <= len(loose.json()["detections"])
    # Re-running invalidates cached layers for the old detection set.
    assert client.get(f"/api/detections/{job}/0/layers").status_code in (200, 404)
    assert client.post(f"/api/jobs/{job}/rerun?margin_db=2").status_code == 422


def test_audio_layers_are_actual_different_wav_clips():
    t = np.arange(32000)/16000
    x = .4*np.sin(2*np.pi*1200*t)+np.random.default_rng(5).normal(0, .025, len(t))
    r = client.post("/api/analyze", files={"file": ("audio.wav", wav_bytes(x))})
    assert r.status_code == 200, r.text
    job = r.json()["job_id"]
    layers = client.get(f"/api/detections/{job}/0/layers").json()
    assert len(layers) == 5 and not layers[3]["enabled"]
    raw = client.get(layers[0]["audio_url"])
    filtered = client.get(layers[1]["audio_url"])
    assert raw.content[:4] == b"RIFF" and raw.content != filtered.content
    assert wavfile.read(BytesIO(raw.content))[0] == 48000


def test_wav_quadrature_ambiguity_and_override():
    t = np.arange(16000)/16000
    paired = np.column_stack([np.cos(2*np.pi*1000*t), np.sin(2*np.pi*1000*t)])
    iq = load_capture("pair.wav", wav_bytes(paired))
    assert iq.metadata["source_kind"] == "iq"
    stereo = np.random.default_rng(4).normal(0, .1, (16000, 2))
    with pytest.raises(AmbiguousCapture):
        load_capture("stereo.wav", wav_bytes(stereo))
    audio = load_capture("stereo.wav", wav_bytes(stereo), wav_mode="audio_right")
    assert audio.metadata["source_kind"] == "audio"
    r = client.post("/api/analyze", files={"file": ("stereo.wav", wav_bytes(stereo))})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "input_required"


def test_missing_malformed_and_invalid_config():
    assert client.get("/api/spectrogram/missing").status_code == 404
    assert client.post("/api/analyze", files={"file": ("bad.wav", b"bad")}).status_code == 422
    x, _ = make_signal("noise")
    assert client.post("/api/analyze", files={"file": ("bad.iq", x.tobytes())}).status_code == 422
    assert client.post("/api/analyze", files={"file": ("bad.iq", x.tobytes())}, data={"sample_rate": FS, "datatype": "cf32_le", "mode": "fixed_debug"}).status_code == 422


@pytest.mark.parametrize("kind", ["bpsk", "qpsk", "fm"])
@pytest.mark.parametrize("snr", [20, 10, 0, -5])
def test_sync_api_preserves_validated_measurements_and_json_export(kind, snr):
    """Wrong input samples, noise units or lost fields must fail at the HTTP boundary."""
    x, _ = make_signal(kind, snr)
    r = client.post("/api/analyze", files={"file": (f"{kind}.iq", x.tobytes())},
                    data={"sample_rate": FS, "datatype": "cf32_le", "estimator": "legacy"})
    assert r.status_code == 200, r.text
    body = r.json()
    d = next(d for d in body["detections"] if d["freq_lower_hz"] < 8000 < d["freq_upper_hz"])
    assert ESTIMATE_FIELDS <= d.keys()
    assert d["center_frequency_hz"] == pytest.approx(8000, rel=.02)
    assert d["snr_db"] == pytest.approx(snr, abs=3)
    if snr >= 0:
        assert d["modulation_family"] == "constant-envelope"
    # Independent, committed measurements from before API integration: wiring
    # must preserve every stage value, not merely pass broad accuracy limits.
    evidence = json.loads((Path(__file__).resolve().parents[2]/"docs"/"estimate-classify-validation.json").read_text())
    previous = next(row["result"] for row in evidence["continuous"]
                    if row["kind"] == kind and row["truth_snr_db"] == snr)
    for key in ESTIMATE_FIELDS:
        want = previous[key]
        if isinstance(want, (float, int)):
            assert d[key] == pytest.approx(want, rel=1e-3, abs=1e-4), key
        else:
            assert d[key] == want, key
    exported = client.get(f"/api/export/{body['job_id']}?format=json")
    assert exported.status_code == 200
    assert exported.json() == body["detections"]


@pytest.mark.parametrize("kind", ["iq", "audio"])
def test_demo_preserves_detect_layers_and_downstream_fields(kind):
    """The bundled demo mixes a 10 dB BPSK source (now within the validated fine
    classification and symbol-rate range) with FM and a pulsed source, which
    must both stay unlabeled/null."""
    r = client.post(f"/api/demo?kind={kind}&estimator=legacy")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["detections"]
    for d in body["detections"]:
        assert ESTIMATE_FIELDS <= d.keys()
        if kind == "audio":
            assert d["center_frequency_hz"] is None
            assert d["modulation_family"] is None
            assert d["fine_modulation_label"] is None
            assert d["symbol_rate_hz"] is None
            assert "requires complex IQ" in d["estimate_status"]
        elif -12000 < d["freq_lower_hz"] < -10000:
            assert d["fine_modulation_label"] == "bpsk"
            assert d["symbol_rate_hz"] == pytest.approx(500, rel=.05)
        else:
            assert d["fine_modulation_label"] is None
            assert d["symbol_rate_hz"] is None
    assert client.get(f"/api/detections/{body['job_id']}/0/layers").status_code == 200


def test_sync_pulses_and_sigmf_absolute_frequency():
    x, _ = make_signal("pulsed", 10)
    metadata = {"global": {"core:datatype": "cf32_le", "core:sample_rate": FS, "core:version": "1.2.0"},
                "captures": [{"core:sample_start": 0, "core:frequency": 100000000}], "annotations": []}
    r = client.post("/api/analyze", files={
        "file": ("pulse.sigmf-data", x.tobytes()),
        "metadata": ("pulse.sigmf-meta", json.dumps(metadata).encode()),
    }, data={"estimator": "legacy"})   # the refined centre of a gated carrier is a legacy measurement
    assert r.status_code == 200, r.text
    d = next(d for d in r.json()["detections"] if d["freq_lower_hz"] < 8000 < d["freq_upper_hz"])
    assert d["center_frequency_hz"]-100000000 == pytest.approx(8000, rel=.02)
    assert d["center_frequency_refined_hz"]-100000000 == pytest.approx(8000, abs=30)
    assert len(d["pulse_windows"]) == 8
    assert d["snr_db"] == pytest.approx(10, abs=3)


def test_real_large_upload_gets_per_track_downstream_enrichment(tmp_path, monkeypatch):
    """A real >1 MiB, multi-block request now gets the same downstream fields a
    small synchronous upload gets, per finished track (bounded re-read), not
    stale first-block estimates and not the old Detect-only contract."""
    monkeypatch.setattr(main, "UPLOADS", tmp_path)
    x, _ = make_signal("bpsk", 10, duration=14)
    assert x.nbytes > main.LARGE_FILE_BYTES
    r = client.post("/api/analyze", files={"file": ("blocks.iq", x.tobytes())},
                    data={"sample_rate": FS, "datatype": "cf32_le", "estimator": "legacy"})
    assert r.status_code == 202, r.text
    job = r.json()["job_id"]
    deadline = time.monotonic()+30
    while time.monotonic() < deadline:
        state = client.get(f"/api/jobs/{job}").json()
        if state["status"] in ("complete", "failed"):
            break
        time.sleep(.02)
    assert state["status"] == "complete", state
    try:
        body = state["result"]
        assert body["settings"]["processing"] == "overlapping_blocks"
        assert state["processed_samples"] == len(x)
        assert body["detections"]
        for d in body["detections"]:
            assert ESTIMATE_FIELDS <= d.keys()
        d = next(dd for dd in body["detections"] if dd["freq_lower_hz"] < 8000 < dd["freq_upper_hz"])
        assert d["center_frequency_hz"] == pytest.approx(8000, rel=.02)
        assert d["modulation_family"] == "constant-envelope"
        assert client.get(f"/api/export/{job}?format=json").json() == body["detections"]
    finally:
        main.discard_job(job)


def test_cancel_endpoint_stops_an_in_progress_async_job(tmp_path, monkeypatch):
    """POST .../jobs/{id}/cancel on a running large-capture job must lead to
    status "cancelled" (or, if the race loses and the job finished first,
    "complete") -- never "failed", which would misreport a cancellation as
    an analysis error."""
    monkeypatch.setattr(main, "UPLOADS", tmp_path)
    x, _ = make_signal("bpsk", 10, duration=14)
    r = client.post("/api/analyze", files={"file": ("blocks.iq", x.tobytes())},
                    data={"sample_rate": FS, "datatype": "cf32_le"})
    assert r.status_code == 202, r.text
    job = r.json()["job_id"]
    try:
        cancel_response = client.post(f"/api/jobs/{job}/cancel")
        assert cancel_response.status_code == 200
        assert cancel_response.json()["requested"] is True
        deadline = time.monotonic()+30
        while time.monotonic() < deadline:
            state = client.get(f"/api/jobs/{job}").json()
            if state["status"] in ("complete", "failed", "cancelled"):
                break
            time.sleep(.02)
        assert state["status"] in ("complete", "cancelled"), state
    finally:
        main.discard_job(job)


def test_cancel_endpoint_unknown_job_404():
    r = client.post("/api/jobs/does-not-exist/cancel")
    assert r.status_code == 404


def test_cancel_endpoint_on_synchronous_job_is_409(tmp_path, monkeypatch):
    """A small (<1 MiB) upload never goes through process_large_job, so it
    never gets a cancel_event -- cancelling it is a client error, not a
    silent no-op that would falsely suggest cancellation is meaningful here."""
    monkeypatch.setattr(main, "UPLOADS", tmp_path)
    x, _ = make_signal("bpsk", 10, duration=2)
    r = client.post("/api/analyze", files={"file": ("small.iq", x.tobytes())},
                    data={"sample_rate": FS, "datatype": "cf32_le"})
    assert r.status_code == 200
    job = r.json()["job_id"]
    try:
        cancel_response = client.post(f"/api/jobs/{job}/cancel")
        assert cancel_response.status_code == 409
    finally:
        main.discard_job(job)


def test_large_upload_rerun_keeps_downstream_enrichment(tmp_path, monkeypatch):
    """/rerun dispatches on the disk-backed capture the same way /api/analyze's
    async path does, so it must inherit per-track enrichment with no extra
    wiring -- this only re-runs Detect's threshold, not a re-upload."""
    monkeypatch.setattr(main, "UPLOADS", tmp_path)
    x, _ = make_signal("bpsk", 10, duration=14)
    r = client.post("/api/analyze", files={"file": ("blocks.iq", x.tobytes())},
                    data={"sample_rate": FS, "datatype": "cf32_le", "estimator": "legacy", "margin_db": 8})
    job = r.json()["job_id"]
    deadline = time.monotonic()+30
    while time.monotonic() < deadline:
        state = client.get(f"/api/jobs/{job}").json()
        if state["status"] in ("complete", "failed"):
            break
        time.sleep(.02)
    assert state["status"] == "complete", state
    try:
        rerun = client.post(f"/api/jobs/{job}/rerun?margin_db=3&estimator=legacy")
        assert rerun.status_code == 200, rerun.text
        detections = rerun.json()["detections"]
        assert detections
        for d in detections:
            assert ESTIMATE_FIELDS <= d.keys()
        d = next(dd for dd in detections if dd["freq_lower_hz"] < 8000 < dd["freq_upper_hz"])
        assert d["center_frequency_hz"] == pytest.approx(8000, rel=.02)
    finally:
        main.discard_job(job)


def test_fine_classification_accuracy_curve_reflects_recorded_validation_evidence():
    r = client.get("/api/validation/fine-classification-accuracy")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["curve"], "expected at least one aggregated bucket"
    kinds = {row["kind"] for row in body["curve"]}
    assert kinds <= {"bpsk", "qpsk"}
    for row in body["curve"]:
        assert row["trials"] > 0
        assert 0 <= row["passed"] <= row["trials"]
        assert row["accuracy"] == pytest.approx(row["passed"] / row["trials"])


def test_symbol_rate_diagnostic_marks_the_published_harmonic():
    x, _ = make_signal("bpsk", 20)
    r = client.post("/api/analyze", files={"file": ("bpsk.iq", x.tobytes())},
                    data={"sample_rate": FS, "datatype": "cf32_le", "estimator": "legacy"})
    assert r.status_code == 200, r.text
    body = r.json()
    d = next(d for d in body["detections"] if d["freq_lower_hz"] < 8000 < d["freq_upper_hz"])
    idx = body["detections"].index(d)
    diag = client.get(f"/api/detections/{body['job_id']}/{idx}/symbol-rate-diagnostic").json()
    assert d["symbol_rate_hz"] is not None
    assert diag["applicable"] is True
    assert diag["selected_frequency_hz"] == pytest.approx(d["symbol_rate_hz"])
    assert len(diag["frequencies_hz"]) == len(diag["power_db"]) > 10
    assert diag["peak_power_db"] > diag["threshold_power_db"]


def test_symbol_rate_diagnostic_not_applicable_when_unestimated():
    x, _ = make_signal("fm", 10)
    r = client.post("/api/analyze", files={"file": ("fm.iq", x.tobytes())},
                    data={"sample_rate": FS, "datatype": "cf32_le", "estimator": "legacy"})
    assert r.status_code == 200, r.text
    body = r.json()
    d = next(d for d in body["detections"] if d["freq_lower_hz"] < 8000 < d["freq_upper_hz"])
    idx = body["detections"].index(d)
    assert d["symbol_rate_hz"] is None
    diag = client.get(f"/api/detections/{body['job_id']}/{idx}/symbol-rate-diagnostic").json()
    assert diag == {"applicable": False, "reason": d["symbol_rate_status"]}


def test_demo_defaults_to_the_verify_estimator_and_keeps_legacy_under_the_flag():
    body = client.post("/api/demo?kind=iq").json()
    assert body["estimator"] == "verify"
    for d in body["detections"]:
        assert d["estimator"] == "verify" and d["fine_modulation_label"] is None
        assert d["estimate_tier"] in ("labelled", "unknown_family", "abstain")
        if d["estimate_tier"] != "labelled":
            assert d["modulation_label"] is None
    legacy = client.post("/api/demo?kind=iq&estimator=legacy").json()
    assert legacy["estimator"] == "legacy"
    assert all(d["label_provenance"] == "legacy (fixture-validated only)" for d in legacy["detections"])
    assert client.post("/api/demo?kind=iq&estimator=bogus").status_code == 422


def _upload(kind, snr_db=20, duration=2.0):
    x, _ = make_signal(kind, snr_db=snr_db, duration=duration, seed=3)
    r = client.post("/api/analyze", files={"file": (f"{kind}.iq", x.astype("<c8").tobytes())},
                    data={"sample_rate": FS, "datatype": "cf32_le"})
    assert r.status_code == 200, r.text
    return r.json()


def test_decode_endpoint_decodes_a_published_ask2_candidate():
    body = _upload("ask")
    idx = next(i for i, d in enumerate(body["detections"]) if d["modulation_label"] == "ASK2")
    out = client.post(f"/api/detections/{body['job_id']}/{idx}/decode").json()
    assert out["decode_label"] == "ask2"
    assert out["decode_status"].startswith("decoded")
    assert "unknown polarity" in out["decode_status"]
    assert out["decoded_symbol_count"] == len(out["decoded_symbol_indices"]) > 400
    assert set(out["decoded_symbol_indices"]) <= {0, 1}
    assert out["decode_rotation_ambiguity_modulus"] == 2
    assert out["decoded_symbols_truncated"] is False
    assert out["decode_span"] == {"start_sample": body["detections"][idx]["start_sample"],
                                  "end_sample": body["detections"][idx]["end_sample"]}
    # deterministic, and served from the job's cache the second time
    assert client.post(f"/api/detections/{body['job_id']}/{idx}/decode").json() == out


def test_decode_endpoint_declines_an_unpublished_label_and_404s_a_missing_candidate():
    body = _upload("pulsed")  # pulsed bursts are still refused, so verify publishes no label
    d = body["detections"][0]
    assert d["modulation_label"] is None
    out = client.post(f"/api/detections/{body['job_id']}/0/decode").json()
    assert out["decoded_symbol_indices"] is None
    assert out["decode_status"] == f"not attempted (no published modulation label: {d['verify_status']})"
    assert client.post(f"/api/detections/{body['job_id']}/99/decode").status_code == 404
    assert client.post("/api/detections/nope/0/decode").status_code == 404



def test_shipped_4fsk_fixture_is_labelled_fsk4():
    # FM must also beat the keyed two-level fits, so the fixture's true 4-FSK fit wins (it abstained before)
    assert _upload("fsk")["detections"][0]["modulation_label"] == "FSK4"

def test_decode_endpoint_truncates_long_streams(monkeypatch):
    body = _upload("ask")
    monkeypatch.setattr(main, "DECODE_MAX_SYMBOLS", 100)
    idx = next(i for i, d in enumerate(body["detections"]) if d["modulation_label"] == "ASK2")
    out = client.post(f"/api/detections/{body['job_id']}/{idx}/decode").json()
    assert len(out["decoded_symbol_indices"]) == 100
    assert out["decoded_symbol_count"] > 100
    assert out["decoded_symbols_truncated"] is True


def test_decode_endpoint_decodes_a_track_of_a_large_disk_backed_upload(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "UPLOADS", tmp_path)
    x, _ = make_signal("bpsk", 20, duration=10, seed=3)
    assert x.nbytes > main.LARGE_FILE_BYTES
    r = client.post("/api/analyze", files={"file": ("big.iq", x.astype("<c8").tobytes())},
                    data={"sample_rate": FS, "datatype": "cf32_le"})
    assert r.status_code == 202, r.text
    job = r.json()["job_id"]
    deadline = time.monotonic()+60
    while time.monotonic() < deadline:
        state = client.get(f"/api/jobs/{job}").json()
        if state["status"] in ("complete", "failed"):
            break
        time.sleep(.05)
    assert state["status"] == "complete", state
    try:
        idx, d = next((i, d) for i, d in enumerate(state["result"]["detections"]) if d["modulation_label"] == "BPSK")
        out = client.post(f"/api/detections/{job}/{idx}/decode").json()
        assert out["decode_status"].startswith("decoded"), out["decode_status"]
        assert out["decode_label"] == "bpsk"
        assert out["decoded_symbol_count"] == 2000
        assert out["decode_span"] == {"start_sample": d["start_sample"], "end_sample": d["end_sample"]}
    finally:
        main.discard_job(job)


def test_readiness_evidence_projects_the_measured_scoreboard():
    raw = json.loads((main.DOCS / "readiness.json").read_text())
    ev = client.get("/api/readiness").json()
    assert ev["estimator"] == raw["product"] == "verify"
    assert ev["measured"] == {"commit": raw["meta"]["commit"], "date": raw["meta"]["date"]}
    s = raw["stats"]["verify"]
    assert ev["label"]["G2"] == {"correct": s["G2"]["label"]["published_correct_in_library"],
                                 "wrong": s["G2"]["label"]["published_wrong"],
                                 "n": s["G2"]["label"]["n"], "n_correct": s["G2"]["label"]["n_in_library"]}
    assert ev["rate"]["G4"]["wrong"] == s["G4"]["rate"]["published_wrong"]
    g5 = raw["meta"]["g5"]
    assert ev["label"]["G5"] == {"correct": g5["correct"], "wrong": g5["wrong"],
                                 "n": g5["n_test"], "n_correct": g5["n_with_label"]}
    assert ev["rate"]["G5"] == {"correct": g5["rate_correct"], "wrong": g5["rate_wrong"],
                                "n": g5["n_rate_scored"], "n_correct": g5["n_rate_scored"]}
    assert set(ev["label"]) == set(ev["rate"]) == {"G1", "G2", "G4", "G5"}


def test_readiness_evidence_is_503_when_the_scoreboard_is_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "DOCS", tmp_path)
    r = client.get("/api/readiness")
    assert r.status_code == 503
    assert "readiness" in r.json()["detail"]
