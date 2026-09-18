from io import BytesIO
import time
import numpy as np
import pytest
from scipy.io import wavfile
from fastapi.testclient import TestClient
from backend.api import main
from backend.pipeline.large_capture import (open_disk_capture, analyze_disk_capture, build_disk_layers,
                                             DiskSamples, enrich_track, TRACK_ENRICHMENT_MAX_SAMPLES)
from backend.pipeline.synth_gen import make_signal, FS
from backend.tests.test_api import ESTIMATE_FIELDS


def test_disk_backed_track_gets_downstream_enrichment(tmp_path):
    """A >1 MiB async upload's tracks are no longer Detect-only: each finished
    track gets a bounded direct re-read of its own span and the same
    Estimate/Classify fields a small synchronous upload gets."""
    x, truth = make_signal("bpsk", 10, duration=14)
    path = tmp_path/"big.iq"
    x.astype("<c8").tofile(path)
    c = open_disk_capture(path, path.name, FS, "cf32_le")
    result = analyze_disk_capture(c, block_samples=32768)
    d = next(dd for dd in result.response["detections"] if dd["freq_lower_hz"] < 8000 < dd["freq_upper_hz"])
    assert ESTIMATE_FIELDS <= d.keys()
    assert d["center_frequency_hz"] == pytest.approx(8000, rel=.02)
    assert d["snr_db"] == pytest.approx(10, abs=3)
    assert d["estimate_status"] == "estimated"
    assert d["modulation_family"] == "constant-envelope"
    # Global (Detect-stage) coordinates must survive untouched, not the local
    # re-read's translated 0-based coordinates.
    assert d["start_sample"] == 0
    assert d["end_sample"] == len(x)


def test_track_exceeding_bounded_reread_limit_is_explicit_unknown(tmp_path):
    """A track longer than DiskSamples' own bounded-read limit must report an
    explicit unresolved status on every downstream field, never a wrong or
    partial number, and must never attempt to read past the file's own length."""
    x, _ = make_signal("bpsk", 10, duration=14)
    path = tmp_path/"big.iq"
    x.astype("<c8").tofile(path)
    c = open_disk_capture(path, path.name, FS, "cf32_le")
    track = {"id": 0, "start_sample": 0, "end_sample": TRACK_ENRICHMENT_MAX_SAMPLES+1,
             "freq_lower_hz": -1000., "freq_upper_hz": 1000., "confidence": .9,
             "detection_method": "adaptive_threshold", "is_pulsed": False,
             "pulse_width_samples": None, "pri_samples": None, "pulse_windows": [],
             "needs_review": False, "threshold_excess_db": 10.}
    out = enrich_track(c, track)
    assert ESTIMATE_FIELDS <= out.keys()
    assert out["center_frequency_hz"] is None
    assert out["modulation_family"] is None
    assert out["fine_modulation_label"] is None
    assert out["symbol_rate_hz"] is None
    assert "bounded re-analysis" in out["estimate_status"]
    # Detect-stage fields must be preserved exactly, not overwritten with nulls.
    assert out["start_sample"] == 0 and out["end_sample"] == TRACK_ENRICHMENT_MAX_SAMPLES+1
    assert out["confidence"] == .9


def test_block_boundary_pulse_and_tail_are_not_lost(tmp_path):
    block = 32768
    x, _ = make_signal("noise", duration=3)
    intervals = [(block-1200, block+1200), (len(x)-4800, len(x)-2400)]
    for a,b in intervals:
        x[a:b] += 5*np.exp(2j*np.pi*8000*np.arange(b-a)/FS)
    path = tmp_path/"boundary.iq"
    x.astype("<c8").tofile(path)
    c = open_disk_capture(path, path.name, FS, "cf32_le")
    updates=[]
    result = analyze_disk_capture(c, block_samples=block, progress=lambda done,total,msg:updates.append(done))
    assert updates[-1] == len(x)
    assert result.power.shape[1] <= 768
    ds=result.response["detections"]
    for a,b in intervals:
        match=[d for d in ds if d["start_sample"] <= a+150 and d["end_sample"] >= b-150]
        assert match, (a,b,ds)
        windows=match[0]["pulse_windows"]
        assert any(abs(w["start_sample"]-a)<150 and abs(w["end_sample"]-b)<150 for w in windows)
    tail=next(d for d in ds if d["end_sample"]>len(x)-5000)
    layers,_=build_disk_layers(c,result,tail)
    assert layers[0]["preview_start_sample"]>0
    assert layers[0]["sample_count"]<=1_000_000
    assert layers[0]["waveform"][0]["time_seconds"]>0
    assert "Preview interval" in layers[0]["description"]


def test_disk_reader_rejects_invalid_samples_at_end(tmp_path):
    path=tmp_path/"invalid.iq"
    x=np.zeros(300000,dtype="<c8");x[-1]=np.nan;x.tofile(path)
    c=open_disk_capture(path,path.name,FS,"cf32_le")
    with pytest.raises(ValueError,match="NaN"):
        analyze_disk_capture(c,block_samples=32768)
    with pytest.raises(ValueError,match="two million"):
        DiskSamples(path,3_000_000,"<f4",2)[:]


@pytest.mark.parametrize("audio",[False,True])
def test_async_upload_status_full_coverage_and_cleanup(tmp_path,monkeypatch,audio):
    monkeypatch.setattr(main,"UPLOADS",tmp_path)
    monkeypatch.setattr(main,"LARGE_FILE_BYTES",1000)
    client=TestClient(main.app)
    if audio:
        t=np.arange(160000)/16000
        payload=BytesIO();wavfile.write(payload,16000,(.4*np.sin(2*np.pi*1200*t)).astype(np.float32))
        name="long.wav";data=payload.getvalue();fields={}
    else:
        x,_=make_signal("pulsed",duration=3)
        name="long.iq";data=x.tobytes();fields={"sample_rate":FS,"datatype":"cf32_le"}
    response=client.post("/api/analyze",files={"file":(name,data)},data=fields)
    assert response.status_code==202,response.text
    job=response.json()["job_id"]
    for _ in range(200):
        state=client.get(f"/api/jobs/{job}").json()
        if state["status"] in ("complete","failed"):
            break
        time.sleep(.02)
    assert state["status"]=="complete",state
    assert state["processed_samples"]==state["total_samples"]
    result=state["result"]
    assert result["metadata"]["sample_count"]==state["total_samples"]
    spec=client.get(f"/api/spectrogram/{job}?width=64&height=32").json()
    assert np.shape(spec["magnitude_db"])==(32,64)
    assert spec["time_edges_seconds"][-1]==result["metadata"]["duration_seconds"]
    layers=client.get(f"/api/detections/{job}/0/layers").json()
    assert layers[0]["enabled"]
    if audio:
        assert client.get(layers[0]["audio_url"]).content[:4]==b"RIFF"
    path=main.JOBS[job]["path"]
    main.discard_job(job)
    assert not path.exists()


def test_failed_async_job_is_explicit_and_removes_upload(tmp_path,monkeypatch):
    monkeypatch.setattr(main,"UPLOADS",tmp_path)
    monkeypatch.setattr(main,"LARGE_FILE_BYTES",1000)
    client=TestClient(main.app)
    r=client.post("/api/analyze",files={"file":("x.iq",b"\0"*16384)})
    job=r.json()["job_id"]
    for _ in range(100):
        state=client.get(f"/api/jobs/{job}").json()
        if state["status"]=="failed":break
        time.sleep(.02)
    assert state["status"]=="failed"
    assert "sample rate" in state["error"]
    assert list(tmp_path.iterdir())==[]
    assert client.get(f"/api/export/{job}").status_code==422
    main.discard_job(job)
