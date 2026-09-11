"""Strict SigMF ingestion and standards-compliant annotation export."""
import json
import numpy as np
from sigmf import SigMFFile

DTYPES = {"cf32_le": ("<f4", True), "cf32_be": (">f4", True),
          "ci16_le": ("<i2", True), "ci16_be": (">i2", True),
          "rf32_le": ("<f4", False), "ri16_le": ("<i2", False)}


def decode_samples(data, datatype):
    if datatype not in DTYPES:
        raise ValueError(f"Unsupported datatype {datatype!r}. Supported: {', '.join(DTYPES)}")
    dtype, complex_data = DTYPES[datatype]
    stride = np.dtype(dtype).itemsize * (2 if complex_data else 1)
    if len(data) % stride:
        raise ValueError("Data contains an incomplete sample; check the selected datatype.")
    x = np.frombuffer(data, dtype=dtype).astype(np.float32)
    # Integer full scale is normalized explicitly; no physical power calibration
    # can be inferred from ADC codes, so outputs are never labeled dBm.
    if "i2" in dtype:
        x /= 32768.0
    if complex_data:
        x = x[::2] + 1j * x[1::2]
    return x.astype(np.complex64), "iq" if complex_data else "audio"


def parse_metadata(raw):
    try:
        meta = json.loads(raw)
        obj = SigMFFile(metadata=meta)
        obj.validate()
    except Exception as exc:
        raise ValueError(f"Invalid SigMF metadata: {exc}") from exc
    global_meta = meta["global"]
    rate = global_meta.get("core:sample_rate")
    if not isinstance(rate, (int, float)) or isinstance(rate, bool) or not np.isfinite(rate) or rate <= 0:
        raise ValueError("SigMF metadata must specify a positive core:sample_rate.")
    captures = meta.get("captures", [])
    frequencies = {c.get("core:frequency") for c in captures}
    if len(frequencies) > 1 or global_meta.get("core:num_channels", 1) != 1:
        raise ValueError("Retuned or multi-channel SigMF captures are not supported; split the capture first.")
    if global_meta.get("core:offset", 0) or any(c.get("core:header_bytes", 0) for c in captures):
        raise ValueError("Captures with byte headers or nonzero sample offsets must be converted first.")
    return meta, float(rate), global_meta["core:datatype"], next(iter(frequencies), None)


def export_metadata(metadata, detections):
    obj = SigMFFile(global_info={"core:datatype": metadata["datatype"],
                                "core:sample_rate": metadata["sample_rate"],
                                "core:version": "1.2.0"})
    capture = {}
    if metadata.get("center_frequency_hz") is not None:
        capture["core:frequency"] = metadata["center_frequency_hz"]
    obj.add_capture(0, metadata=capture)
    center = metadata.get("center_frequency_hz") or 0
    for d in detections:
        # SigMF uses sample_count (exclusive end minus start) and absolute RF
        # bounds when a tuning frequency exists. Dashboard bounds stay baseband.
        obj.add_annotation(d["start_sample"], d["end_sample"]-d["start_sample"], metadata={
            "core:freq_lower_edge": center+d["freq_lower_hz"],
            "core:freq_upper_edge": center+d["freq_upper_hz"],
            "core:label": f"Candidate {d['id']}",
            "core:comment": json.dumps({k: d[k] for k in ("confidence", "detection_method", "is_pulsed", "needs_review")})})
    obj.validate()
    return json.loads(obj.dumps())
