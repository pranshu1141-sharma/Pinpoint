"""Write a reviewable measurement report by running the actual detector."""
import json
from pathlib import Path
import numpy as np
from backend.pipeline.synth_gen import make_signal, FS
from backend.pipeline.ingest import load_capture
from backend.pipeline.detect import analyze_capture


def main():
    rows = []
    for kind in ("bpsk", "qpsk", "fm", "pulsed", "noise"):
        for snr in ((20, 10, 0, -5) if kind in ("bpsk", "qpsk", "fm") else (10,)):
            x, truth = make_signal(kind, snr)
            capture = load_capture(f"{kind}.iq", x.astype("<c8").tobytes(), FS, "cf32_le")
            r = analyze_capture(capture).response
            rows.append({"fixture": kind, "snr_db": snr if kind != "noise" else None,
                         "ground_truth": truth, "candidate_count": len(r["detections"]),
                         "detections": r["detections"], "noise_floor_db": r["noise_floor_db"], "elapsed_ms": r["elapsed_ms"]})
    signals = [r for r in rows if r["fixture"] in ("bpsk", "qpsk", "fm")]
    matches = sum(any(d["freq_lower_hz"] < 8000 < d["freq_upper_hz"] for d in r["detections"]) for r in signals)
    report = {"description": "Measured synthetic validation; no field-performance or probability guarantee.",
              "sample_rate_hz": FS, "recall_continuous_fixtures": matches/len(signals),
              "continuous_fixture_count": len(signals), "captures": rows}
    target = Path(__file__).parent / "validation-report.json"
    target.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Wrote {target}; continuous-fixture recall {matches}/{len(signals)}")


if __name__ == "__main__":
    main()
