"""Run the actual pipeline against real (non-synthetic) IQ captures and write a
reviewable triage report. Unlike backend/validate.py, this does not score
against known ground truth -- there is none for a real capture -- it only
records what Detect + Estimate + Classify actually returned, plus a handful of
diagnostic flags for common real-hardware failure modes (DC spike, non-flat
noise floor, clipping). Fixing anything this surfaces is explicitly out of
scope here; this script only documents behavior.
"""
import json
from pathlib import Path

import numpy as np

from backend.pipeline.classify import analyze_candidate
from backend.pipeline.detect import analyze_capture
from backend.pipeline.ingest import load_capture

REAL_DATA = Path(__file__).parent / "data" / "real"

# (data file, optional sigmf-meta file) pairs to triage.
FILES = [
    (REAL_DATA / "sigid3_trimmed.sigmf-data", REAL_DATA / "sigid3_trimmed.sigmf-meta"),
    (REAL_DATA / "sigid3_full.sigmf-data", REAL_DATA / "sigid3_full.sigmf-meta"),
]


def dc_spike_suspected(psd, bins=3, ratio_db=15.0):
    """Flag an outsized peak within `bins` of 0 Hz baseband vs. the rest of the PSD."""
    powers = np.array([p["power_db"] for p in psd])
    freqs = np.array([p["frequency_hz"] for p in psd])
    near_dc = np.argsort(np.abs(freqs))[:bins]
    rest = np.setdiff1d(np.arange(len(powers)), near_dc)
    if rest.size == 0:
        return False
    return bool(np.max(powers[near_dc]) - np.median(powers[rest]) > ratio_db)


def noise_floor_nonflat(psd, spread_db=12.0):
    """Simple flatness heuristic: is the PSD's spread (IQR) unusually wide?

    This measures whole-PSD dynamic range, not strictly the noise floor: a
    strong narrowband signal can trip it even when the actual noise is flat.
    """
    powers = np.array([p["power_db"] for p in psd])
    q75, q25 = np.percentile(powers, [75, 25])
    return bool(q75 - q25 > spread_db)


# Integer datatypes are normalized to a known full scale by decode_samples
# (sigmf_io.py: int16 codes divided by 32768.0, so |sample| approaches 1.0 at
# the ADC rail). Float datatypes (cf32/rf32) carry no such guarantee -- SigMF
# imposes no fixed scale on them, so "full scale" is undefined for them and
# clipping can only be judged relative to this capture's own observed peak,
# which is a weaker signal (catches rail-pinned saturation, not amplitude in
# general).
INTEGER_FULL_SCALE = {"ci16_le": 1.0, "ci16_be": 1.0}


def clipping_suspected(iq, datatype, fraction=0.001):
    """Flag if a notable fraction of samples sit at/near full scale.

    Absolute full-scale comparison for normalized integer datatypes; falls
    back to a relative-to-observed-peak heuristic for float datatypes, where
    no absolute full scale exists.
    """
    mag = np.abs(iq)
    full_scale = INTEGER_FULL_SCALE.get(datatype)
    if full_scale is None:
        peak = float(np.max(mag))
        if peak <= 0:
            return False
        full_scale = peak
    near_peak = np.mean(mag > 0.98 * full_scale)
    return bool(near_peak > fraction)


def triage_one(data_path: Path, meta_path: Path | None):
    filename = data_path.name
    row = {"file": filename, "path": str(data_path)}
    try:
        row["size_bytes"] = data_path.stat().st_size
        sigmf_meta = meta_path.read_bytes() if meta_path and meta_path.exists() else None
        capture = load_capture(filename, data_path.read_bytes(), sigmf_meta=sigmf_meta)
        detect = analyze_capture(capture)
        r = detect.response
        detections = [analyze_candidate(capture, d, noise_floor=detect.noise_floor)
                      for d in r["detections"]]
        row.update(
            error=None,
            metadata=capture.metadata,
            noise_floor_db=r["noise_floor_db"],
            elapsed_ms=r["elapsed_ms"],
            candidate_count=len(detections),
            detections=detections,
            dc_spike_suspected=dc_spike_suspected(r["psd"]),
            noise_floor_nonflat=noise_floor_nonflat(r["psd"]),
            clipping_suspected=clipping_suspected(capture.iq, capture.metadata["datatype"]),
            statuses={
                "estimate_status": [d.get("estimate_status") for d in detections],
                "modulation_status": [d.get("modulation_status") for d in detections],
                "fine_modulation_status": [d.get("fine_modulation_status") for d in detections],
                "symbol_rate_status": [d.get("symbol_rate_status") for d in detections],
            },
        )
    except Exception as exc:  # noqa: BLE001 -- one bad file must not kill the run
        row.update(error=f"{type(exc).__name__}: {exc}")
    return row


def main():
    rows = [triage_one(data, meta) for data, meta in FILES]
    report = {
        "description": "Real-capture triage: what Detect+Estimate+Classify actually returned. "
                       "Not scored against ground truth (none exists); documents behavior only.",
        "files": rows,
    }
    target = Path(__file__).parent / "triage-report.json"
    target.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(f"Wrote {target}")
    for row in rows:
        if row.get("error"):
            print(f"{row['file']}: ERROR {row['error']}")
            continue
        print(f"{row['file']}: {row['candidate_count']} candidate(s), "
              f"noise_floor={row['noise_floor_db']:.2f} dB, "
              f"dc_spike_suspected={row['dc_spike_suspected']}, "
              f"noise_floor_nonflat={row['noise_floor_nonflat']}, "
              f"clipping_suspected={row['clipping_suspected']}")
        for d in row["detections"]:
            print(f"  [{d['freq_lower_hz']:.0f}, {d['freq_upper_hz']:.0f}] Hz  "
                  f"center={d.get('center_frequency_hz')}  snr={d.get('snr_db')}  "
                  f"family={d.get('modulation_family')}  fine={d.get('fine_modulation_label')}  "
                  f"symbol_rate={d.get('symbol_rate_hz')}")


if __name__ == "__main__":
    main()
