"""decode_disk_track: on-demand decode for disk-backed (large-upload) tracks
from one bounded re-read, never a whole-file read."""
import numpy as np
import pytest

from backend.pipeline import large_capture
from backend.pipeline.large_capture import decode_disk_track, open_disk_capture

FS = 48000.0


def disk_capture(tmp_path, n=200_000):
    path = tmp_path / "c.iq"
    (np.random.default_rng(0).standard_normal(2*n).astype("<f4")*.01).tofile(path)
    return open_disk_capture(path, "c.iq", FS, "cf32_le")


def track(start, end, label="BPSK", spans=()):
    return {"start_sample": start, "end_sample": end, "pulse_windows": [], "is_pulsed": False,
            "freq_lower_hz": -1000.0, "freq_upper_hz": 1000.0, "center_frequency_hz": 0.0,
            "modulation_label": label, "verify_status": "estimated (label margin passed)",
            "snr_db": 20.0, "symbol_rate_hz": 500.0, "analysis_spans": list(spans)}


def spy(monkeypatch):
    calls = []

    def fake(capture, candidate):
        calls.append((len(capture.iq), candidate["start_sample"], candidate["end_sample"]))
        return {"decoded_symbol_indices": [1, 0], "decode_status": "decoded (fake)"}

    monkeypatch.setattr(large_capture, "decode_published", fake)
    return calls


def test_a_track_within_the_budget_is_decoded_from_one_whole_track_read(tmp_path, monkeypatch):
    calls = spy(monkeypatch)
    out = decode_disk_track(disk_capture(tmp_path), track(10_000, 150_000))
    assert calls == [(140_000, 0, 140_000)]          # local coordinates, exactly the track
    assert out["decode_span"] == {"start_sample": 10_000, "end_sample": 150_000}
    assert out["decode_status"] == "decoded (fake)"


def test_a_long_track_is_decoded_from_a_full_budget_window_at_the_first_span_with_the_label(tmp_path, monkeypatch):
    calls = spy(monkeypatch)
    capture = disk_capture(tmp_path)
    capture.iq.max_read_samples = 50_000
    spans = [{"start_sample": 0, "end_sample": 6_000, "modulation_label": None},
             {"start_sample": 60_000, "end_sample": 66_000, "modulation_label": "BPSK"},
             {"start_sample": 120_000, "end_sample": 126_000, "modulation_label": "BPSK"}]
    out = decode_disk_track(capture, track(0, 200_000, spans=spans))
    assert calls == [(50_000, 0, 50_000)]
    assert out["decode_span"] == {"start_sample": 60_000, "end_sample": 110_000}


def test_the_window_is_clamped_to_the_track_end(tmp_path, monkeypatch):
    calls = spy(monkeypatch)
    capture = disk_capture(tmp_path)
    capture.iq.max_read_samples = 50_000
    spans = [{"start_sample": 180_000, "end_sample": 186_000, "modulation_label": "BPSK"}]
    out = decode_disk_track(capture, track(0, 200_000, spans=spans))
    assert out["decode_span"] == {"start_sample": 150_000, "end_sample": 200_000}
    assert len(calls) == 1


def test_a_long_track_without_a_span_carrying_the_label_is_declined_without_reading(tmp_path, monkeypatch):
    calls = spy(monkeypatch)
    capture = disk_capture(tmp_path)
    capture.iq.max_read_samples = 50_000
    spans = [{"start_sample": 0, "end_sample": 6_000, "modulation_label": "QPSK"}]
    out = decode_disk_track(capture, track(0, 200_000, spans=spans))
    assert calls == []
    assert out["decoded_symbol_indices"] is None
    assert out["decode_span"] is None
    assert out["decode_status"] == "not attempted (no sampled span of this long track published BPSK)"


def test_an_unpublished_label_is_declined_by_decode_published_without_reading(tmp_path):
    capture = disk_capture(tmp_path)
    capture.iq.max_read_samples = 50_000
    out = decode_disk_track(capture, track(0, 200_000, label=None))
    assert out["decoded_symbol_indices"] is None
    assert out["decode_status"].startswith("not attempted (no published modulation label")
    assert out["decode_span"] is None


def test_a_failed_re_read_is_declined_with_the_reason(tmp_path):
    capture = disk_capture(tmp_path)
    out = decode_disk_track(capture, track(150_000, 250_000))   # past the file's end
    assert out["decoded_symbol_indices"] is None
    assert out["decode_status"].startswith("not attempted (the bounded re-read failed")
