"""G3: real recordings (WP7). Each manifest entry records, by hand, what is known about a file;
`check(entry, result)` compares the pipeline output with it. Results land in
artifacts/readiness/real_results.json; the criterion reads that file."""
import json
from pathlib import Path

from .config import THRESHOLDS as TH

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = Path(__file__).with_name("real_manifest.json")
RESULTS = ROOT / "artifacts" / "readiness" / "real_results.json"


def criterion():
    results = json.loads(RESULTS.read_text()) if RESULTS.exists() else []
    ran = [r for r in results if r.get("crashed") is False]
    sane = [r for r in ran if r.get("sanity_ok")]
    n = len(results)
    ok = n >= TH.real_min_recordings and len(sane) == n
    return dict(id="RD1", desc=f">= {TH.real_min_recordings} public recordings end to end, no crash, sanity check on each",
                passed=bool(ok), gens={"G3": dict(value=f"{len(sane)}/{n} sane" if n else None,
                                                  passed=bool(ok) if n else None, n=n)},
                files=[dict(file=r["file"], crashed=r.get("crashed"), sanity_ok=r.get("sanity_ok"),
                            note=r.get("note")) for r in results])
