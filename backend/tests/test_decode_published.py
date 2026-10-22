"""decode_published: gates decode_candidate on the verify estimator's
*published* label (modulation_label), never on a guessed or legacy one."""
import numpy as np

from backend.pipeline import decode
from backend.pipeline.ingest import Capture

BASE = {"modulation_label": None, "verify_status": "not reliably estimated (margins below thresholds)",
        "snr_db": 20.0, "symbol_rate_hz": 500.0, "center_frequency_hz": 0.0,
        "freq_lower_hz": -1000.0, "freq_upper_hz": 1000.0, "start_sample": 0, "end_sample": 1000,
        "is_pulsed": False, "fine_modulation_label": None}
CAPTURE = Capture(np.zeros(1000, dtype=np.complex64), 48000.0, {"source_kind": "iq"})


def test_unpublished_label_declines_with_the_verify_reason():
    out = decode.decode_published(CAPTURE, BASE)
    assert out["decoded_symbol_indices"] is None
    assert out["decode_label"] is None
    assert out["decode_status"] == ("not attempted (no published modulation label: "
                                    "not reliably estimated (margins below thresholds))")


def test_published_label_without_a_validated_decoder_declines():
    out = decode.decode_published(CAPTURE, {**BASE, "modulation_label": "QAM16"})
    assert out["decoded_symbol_indices"] is None
    assert out["decode_status"] == "not attempted (no validated decoder for QAM16)"


def test_legacy_fine_label_is_never_used():
    out = decode.decode_published(CAPTURE, {**BASE, "fine_modulation_label": "bpsk"})
    assert out["decode_label"] is None
    assert "no published modulation label" in out["decode_status"]


def test_published_label_maps_to_the_decoder_and_returns_only_decode_fields(monkeypatch):
    seen = {}

    def fake(capture, candidate):
        seen.update(candidate)
        return {**candidate, "decoded_symbol_indices": [0, 1], "decode_status": "decoded (fake)"}

    monkeypatch.setattr(decode, "decode_candidate", fake)
    for published, internal in decode.VERIFY_DECODE_LABELS.items():
        out = decode.decode_published(CAPTURE, {**BASE, "modulation_label": published})
        assert seen["fine_modulation_label"] == internal
        assert out["decode_label"] == internal
        assert out["decoded_symbol_indices"] == [0, 1]
        assert "freq_lower_hz" not in out
