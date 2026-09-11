from io import BytesIO
import numpy as np
from scipy.io import wavfile
from fastapi.testclient import TestClient
from sigmf import SigMFFile
from backend.api.main import app
from backend.pipeline.ingest import load_capture, AmbiguousCapture
from backend.pipeline.synth_gen import make_signal, FS
import pytest

client = TestClient(app)


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
