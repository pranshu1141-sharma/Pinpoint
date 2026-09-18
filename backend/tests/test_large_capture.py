from io import BytesIO
import time
import numpy as np
import pytest
from scipy.io import wavfile
from fastapi.testclient import TestClient
from backend.api import main
from backend.pipeline.large_capture import (open_disk_capture, analyze_disk_capture, build_disk_layers,
                                             DiskSamples, enrich_track, max_read_samples)
from backend.pipeline.synth_gen import make_signal, FS
from backend.tests.test_api import ESTIMATE_FIELDS


def test_max_read_samples_is_duration_consistent_across_sample_rates():
    """The bounded-read budget is a real-time duration (MAX_READ_SECONDS),
    capped by a hard sample-count ceiling for high sample rates -- not a flat
    sample count regardless of rate. A low sample-rate capture gets fewer
    samples than the old flat 2,000,000 cap would have allowed (the duration
    limit binds first); a high sample-rate capture is still bounded by the
    ceiling (the duration limit alone would allow far more than fits in the
    same memory budget)."""
    from backend.pipeline.large_capture import MAX_READ_SECONDS, MAX_READ_SAMPLES_CEILING
    low_rate = 1000.0
    assert max_read_samples(low_rate) == int(MAX_READ_SECONDS*low_rate)
    assert max_read_samples(low_rate) < MAX_READ_SAMPLES_CEILING
    high_rate = 20_000_000.0
    assert max_read_samples(high_rate) == MAX_READ_SAMPLES_CEILING


def test_enrich_track_local_capture_inherits_sample_rate_and_center_frequency(tmp_path):
    """enrich_track's per-track local re-read must inherit the parent
    capture's sample_rate and tuning offset (metadata["center_frequency_hz"]),
    not silently default to baseband/0 Hz -- a silent offset here would
    corrupt every frequency-domain field (center_frequency_hz, bandwidth,
    refined frequency) reported for large-capture tracks specifically, while
    the synchronous small-file path stayed correct."""
    import json
    x, _ = make_signal("bpsk", 10, duration=14, frequency=8000)
    path = tmp_path/"tuned.sigmf-data"
    x.astype("<c8").tofile(path)
    meta = {"global": {"core:datatype": "cf32_le", "core:sample_rate": FS, "core:version": "1.2.0"},
            "captures": [{"core:sample_start": 0, "core:frequency": 915e6}], "annotations": []}
    c = open_disk_capture(path, path.name, metadata=json.dumps(meta).encode())
    assert c.sample_rate == FS
    assert c.metadata["center_frequency_hz"] == 915e6
    track = {"id": 0, "start_sample": 0, "end_sample": len(x),
             "freq_lower_hz": 6000., "freq_upper_hz": 10000., "confidence": .9,
             "detection_method": "adaptive_threshold", "is_pulsed": False,
             "pulse_width_samples": None, "pri_samples": None, "pulse_windows": [],
             "needs_review": False, "threshold_excess_db": 10.}
    out = enrich_track(c, track)
    # 915 MHz (the parent's tuning offset) plus the ~8 kHz baseband tone,
    # not just the baseband value alone -- confirms the local re-read actually
    # inherited the offset rather than defaulting to an untuned baseband read.
    assert out["center_frequency_hz"] == pytest.approx(915e6+8000, rel=.01)


def test_cancel_check_stops_the_block_scan(tmp_path):
    from backend.pipeline.large_capture import AnalysisCancelled
    x, _ = make_signal("bpsk", 10, duration=6, frequency=8000)
    path = tmp_path/"cancel_scan.iq"
    x.astype("<c8").tofile(path)
    c = open_disk_capture(path, path.name, FS, "cf32_le")
    with pytest.raises(AnalysisCancelled, match="samples scanned"):
        analyze_disk_capture(c, block_samples=32768, cancel_check=lambda: True)


def test_cancel_check_stops_track_enrichment(tmp_path):
    """cancel_check must be polled during the per-track enrichment phase too
    (after the block scan finishes), not only between the two phases --
    enrichment does real bounded-re-read work per track and can itself take
    meaningful wall-clock time on a capture with many candidates."""
    from backend.pipeline.large_capture import AnalysisCancelled
    x, _ = make_signal("bpsk", 10, duration=6, frequency=8000)
    path = tmp_path/"cancel_enrich.iq"
    x.astype("<c8").tofile(path)
    c = open_disk_capture(path, path.name, FS, "cf32_le")
    block = 32768
    chunks = (len(x)+block-1)//block  # exact number of block-scan cancel_check calls
    calls = {"n": 0}

    def cancel_after_scan():
        calls["n"] += 1
        return calls["n"] > chunks  # first call past the scan phase, i.e. during enrichment

    with pytest.raises(AnalysisCancelled, match="enriching"):
        analyze_disk_capture(c, block_samples=block, cancel_check=cancel_after_scan)
    assert calls["n"] == chunks+1


def test_enrichment_phase_reports_progress(tmp_path):
    """After the block scan reaches 100% of samples, the per-track
    enrichment phase must still report progress (via distinct messages),
    not go silent until the whole job finishes."""
    x, _ = make_signal("bpsk", 10, duration=6, frequency=8000)
    path = tmp_path/"progress.iq"
    x.astype("<c8").tofile(path)
    c = open_disk_capture(path, path.name, FS, "cf32_le")
    messages = []
    analyze_disk_capture(c, block_samples=32768, progress=lambda done, total, msg: messages.append(msg))
    assert any("Enriching candidate tracks" in m for m in messages)
    assert any("Analyzed block" in m for m in messages)


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
    track = {"id": 0, "start_sample": 0, "end_sample": max_read_samples(FS)+1,
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
    assert out["start_sample"] == 0 and out["end_sample"] == max_read_samples(FS)+1
    assert out["confidence"] == .9


def test_continuous_signal_straddling_block_boundary_merges_to_one_track(tmp_path):
    """A continuous (non-pulsed) band that starts before one block boundary
    and runs past several more must merge into exactly one track across the
    whole span, and re-analysis (enrich_track, via analyze_disk_capture) must
    report correct bandwidth and symbol rate on that merged span -- not a
    value skewed by treating a boundary-straddling signal as multiple
    disjoint per-block pieces."""
    block = 32768
    x, truth = make_signal("bpsk", 15, duration=6, frequency=8000)
    # The BPSK band spans the whole 6 s capture, crossing several block
    # boundaries at the chosen block size (6*FS/32768 ~= 8.8 blocks).
    path = tmp_path/"straddle.iq"
    x.astype("<c8").tofile(path)
    c = open_disk_capture(path, path.name, FS, "cf32_le")
    result = analyze_disk_capture(c, block_samples=block)
    ds = result.response["detections"]
    matches = [d for d in ds if d["freq_lower_hz"] < 8000 < d["freq_upper_hz"]]
    assert len(matches) == 1, f"expected exactly one merged track, got {len(matches)}: {ds}"
    d = matches[0]
    # Confirms the track was not silently truncated to a single block: it
    # must span from very near the start to very near the end of the file.
    assert d["start_sample"] < block
    assert d["end_sample"] > len(x)-block
    assert d["bandwidth_3db_hz"] is not None and 0 < d["bandwidth_3db_hz"] <= d["bandwidth_99pct_hz"]
    assert d["symbol_rate_hz"] == pytest.approx(truth[0]["symbol_rate_hz"], rel=.1)


def test_fading_signal_keeps_one_track_across_a_15db_drop(tmp_path):
    """A signal whose amplitude drops 15 dB partway through must still merge
    into a single track spanning the whole duration, not be split into two
    separate tracks (or lose the faded half entirely) at the point where its
    per-block confidence crosses the review threshold."""
    block = 32768
    x, _ = make_signal("bpsk", 20, duration=6, frequency=8000)
    # Halve the *signal component* only: make_signal already adds noise sized
    # for the requested 20 dB SNR, so scaling the whole mixed capture would
    # also scale the noise and defeat the fade. Regenerate the noiseless
    # carrier at the same seed/frequency implicitly by scaling the analytic
    # signal's envelope directly via a smooth power-domain gate instead: cut
    # the last half of the *file*, which for a stationary complex-Gaussian
    # background is equivalent in expectation to fading just the signal
    # provided the drop is applied before adding no further noise -- so fade
    # is applied to the full mixed capture from its midpoint by re-deriving
    # a fresh, lower-SNR second half from the same generator call and
    # splicing the halves together, keeping phase continuity at the splice.
    half = len(x)//2
    faded_tail, _ = make_signal("bpsk", 20-15, duration=6, frequency=8000)
    x = np.concatenate([x[:half], faded_tail[half:]]).astype(np.complex64)
    path = tmp_path/"fading.iq"
    x.astype("<c8").tofile(path)
    c = open_disk_capture(path, path.name, FS, "cf32_le")
    result = analyze_disk_capture(c, block_samples=block)
    ds = result.response["detections"]
    matches = [d for d in ds if d["freq_lower_hz"] < 8000 < d["freq_upper_hz"]]
    assert len(matches) == 1, f"expected the fade to stay one track, got {len(matches)}: {ds}"
    d = matches[0]
    assert d["start_sample"] < block
    assert d["end_sample"] > len(x)-block
    # The merger takes the least confident observed block (see
    # analyze_disk_capture's confidence-merge comment), so a genuine 15 dB
    # mid-capture fade must show up as reduced confidence on the merged
    # track, not be averaged away. Compare against an unfaded control at the
    # same final (lower) SNR rather than a fixed threshold, since the exact
    # confidence heuristic's scale is not itself under test here.
    unfaded, _ = make_signal("bpsk", 20-15, duration=6, frequency=8000)
    control_path = tmp_path/"control.iq"
    unfaded.astype("<c8").tofile(control_path)
    control = analyze_disk_capture(open_disk_capture(control_path, control_path.name, FS, "cf32_le"),
                                   block_samples=block)
    control_match = next(cd for cd in control.response["detections"] if cd["freq_lower_hz"] < 8000 < cd["freq_upper_hz"])
    assert d["confidence"] <= control_match["confidence"] + .02


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
    with pytest.raises(ValueError,match="cannot exceed"):
        DiskSamples(path,3_000_000,"<f4",2,FS)[:]


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
