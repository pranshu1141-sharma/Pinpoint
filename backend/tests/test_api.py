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
                    data={"sample_rate": FS, "datatype": "cf32_le"})
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
            assert d[key] == pytest.approx(want, rel=1e-9, abs=1e-7), key
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
    r = client.post(f"/api/demo?kind={kind}")
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
    })
    assert r.status_code == 200, r.text
    d = next(d for d in r.json()["detections"] if d["freq_lower_hz"] < 8000 < d["freq_upper_hz"])
    assert d["center_frequency_hz"]-100000000 == pytest.approx(8000, rel=.02)
    assert d["center_frequency_refined_hz"]-100000000 == pytest.approx(8000, abs=30)
    assert len(d["pulse_windows"]) == 8
    assert d["snr_db"] == pytest.approx(10, abs=3)


def test_real_large_upload_keeps_estimates_absent_after_block_merge(tmp_path, monkeypatch):
    """A real >1 MiB, multi-block request must not publish first-block estimates as full-capture values."""
    monkeypatch.setattr(main, "UPLOADS", tmp_path)
    x, _ = make_signal("bpsk", 10, duration=14)
    assert x.nbytes > main.LARGE_FILE_BYTES
    r = client.post("/api/analyze", files={"file": ("blocks.iq", x.tobytes())},
                    data={"sample_rate": FS, "datatype": "cf32_le"})
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
            assert not (ESTIMATE_FIELDS & d.keys())
        assert client.get(f"/api/export/{job}?format=json").json() == body["detections"]
    finally:
        main.discard_job(job)
