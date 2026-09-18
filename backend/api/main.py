from collections import OrderedDict, defaultdict
import json
from pathlib import Path
from threading import RLock, BoundedSemaphore, Event
from time import monotonic
from uuid import uuid4
from concurrent.futures import ThreadPoolExecutor
import tempfile
import numpy as np
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Query
from fastapi.responses import Response, FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from starlette.concurrency import run_in_threadpool
from backend.pipeline.ingest import load_capture, AmbiguousCapture
from backend.pipeline.detect import analyze_capture, db
from backend.pipeline.classify import analyze_candidate, symbol_rate_diagnostic
from backend.pipeline.layers import build_layers, waveform
from backend.pipeline.sigmf_io import export_metadata
from backend.pipeline.large_capture import (open_disk_capture, analyze_disk_capture, build_disk_layers,
                                            DiskSamples, AnalysisCancelled)

app = FastAPI(title="SIH26147 · Detect", version="1.0.0", description="Offline detection with synchronous IQ estimates and coarse classification; no decoding.")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
                   allow_methods=["GET", "POST"], allow_headers=["*"])
DATA = Path(__file__).resolve().parents[1] / "data"
DEMO = DATA / "demo"
DOCS = Path(__file__).resolve().parents[2] / "docs"
MAX_BYTES = 2*1024*1024*1024
LARGE_FILE_BYTES = 1024*1024
UPLOADS = DATA / "jobs"
EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="capture-analysis")
JOBS = OrderedDict()
LOCK = RLock()
COMPUTE = BoundedSemaphore(1)
TTL_SECONDS = 1800


def discard_job(job_id):
    job = JOBS.pop(job_id, None)
    if job and job.get("path"):
        # Only remove the server-created upload, never a user-supplied path.
        path = Path(job["path"]).resolve()
        if path.parent == UPLOADS.resolve():
            path.unlink(missing_ok=True)


def prune_jobs():
    finished = [key for key, value in JOBS.items() if value.get("status", "complete") not in ("queued", "processing")]
    for key in finished:
        if monotonic()-JOBS[key]["created"] > TTL_SECONDS:
            discard_job(key)
    finished = [key for key, value in JOBS.items() if value.get("status", "complete") not in ("queued", "processing")]
    for key in finished[:-3]:
        discard_job(key)


def get_job(job_id):
    with LOCK:
        if job_id in JOBS and JOBS[job_id].get("status") in ("queued", "processing"):
            raise HTTPException(409, "Analysis is still running. Poll the job status.")
        if job_id not in JOBS or monotonic()-JOBS[job_id]["created"] > TTL_SECONDS:
            discard_job(job_id)
            raise HTTPException(404, "Job expired or missing. Analyze the capture again.")
        if JOBS[job_id].get("status") == "failed":
            raise HTTPException(422, JOBS[job_id]["error"])
        return JOBS[job_id]


def run_analysis(filename, data, sample_rate=None, datatype=None, metadata=None, wav_mode="auto",
                 margin_db=8, mode="adaptive", fixed_threshold_db=None):
    if not COMPUTE.acquire(blocking=False):
        raise HTTPException(429, "Another analysis is running. Try again when it finishes.")
    try:
        c = load_capture(filename, data, sample_rate, datatype, metadata, wav_mode)
        started = monotonic()
        r = analyze_capture(c, margin_db, mode, fixed_threshold_db)
        # Preserve the validated Capture/noise-density contract. Passing already
        # filtered samples would change bandwidth, SNR and carrier estimates.
        # Large disk-backed uploads take a separate enrichment path (see
        # large_capture.enrich_track): each finished track gets its own
        # bounded direct re-read instead of reusing this whole-capture flow.
        r.response["detections"] = [analyze_candidate(c, d, noise_floor=r.noise_floor)
                                    for d in r.response["detections"]]
        # The existing log still describes Detect. The API timer includes all
        # downstream processing so the dashboard reports its actual cost.
        r.response["elapsed_ms"] = (monotonic()-started)*1000
        job_id = uuid4().hex
        r.response["job_id"] = job_id
        r.response["expires_in_seconds"] = TTL_SECONDS
        with LOCK:
            JOBS[job_id] = {"capture": c, "result": r, "created": monotonic(), "layers": {}}
            prune_jobs()
        return r.response
    except AmbiguousCapture as exc:
        raise HTTPException(422, {"code": "input_required", "message": str(exc)}) from exc
    except (ValueError, KeyError, TypeError) as exc:
        raise HTTPException(422, {"code": "invalid_capture", "message": str(exc)}) from exc
    finally:
        COMPUTE.release()


@app.get("/api/health")
def health():
    with LOCK:
        prune_jobs()
    return {"status": "connected", "stage": "detect", "max_upload_bytes": MAX_BYTES}


async def bounded_read(file, limit):
    content = await file.read(limit+1)
    if len(content) > limit:
        raise HTTPException(413, f"Upload exceeds the {limit:,}-byte limit.")
    return content


@app.post("/api/analyze")
async def analyze(file: UploadFile = File(...), metadata: UploadFile | None = File(None),
                  sample_rate: float | None = Form(None), datatype: str | None = Form(None),
                  wav_mode: str = Form("auto"), margin_db: float = Form(8),
                  mode: str = Form("adaptive"), fixed_threshold_db: float | None = Form(None)):
    meta = await bounded_read(metadata, 1024*1024) if metadata else None
    if file.size is not None and file.size > MAX_BYTES:
        raise HTTPException(413, "Maximum capture size is 2 GiB (2,147,483,648 bytes).")
    UPLOADS.mkdir(parents=True, exist_ok=True)
    temp = tempfile.NamedTemporaryFile(dir=UPLOADS, suffix=".capture", delete=False)
    path = Path(temp.name)
    size = 0
    try:
        with temp:
            while block := await file.read(8*1024*1024):
                size += len(block)
                if size > MAX_BYTES:
                    raise HTTPException(413, "Maximum capture size is 2 GiB (2,147,483,648 bytes).")
                await run_in_threadpool(temp.write, block)
        if size <= LARGE_FILE_BYTES:
            data = await run_in_threadpool(path.read_bytes)
            return await run_in_threadpool(run_analysis, file.filename or "capture", data, sample_rate,
                                          datatype, meta, wav_mode, margin_db, mode, fixed_threshold_db)
        if not COMPUTE.acquire(blocking=False):
            raise HTTPException(429, "Another analysis is running. Try again when it finishes.")
        job_id = uuid4().hex
        cancel_event = Event()
        with LOCK:
            JOBS[job_id] = {"status":"queued", "created":monotonic(), "path":path,
                            "processed_samples":0, "total_samples":None, "progress":0,
                            "message":"Upload received. Validating capture metadata.", "layers":{},
                            "cancel_event":cancel_event}
        try:
            EXECUTOR.submit(process_large_job, job_id, path, file.filename or "capture", sample_rate,
                            datatype, meta, wav_mode, margin_db, mode, fixed_threshold_db, cancel_event)
        except Exception:
            COMPUTE.release()
            with LOCK:
                discard_job(job_id)
            raise
        path = None  # Ownership transfers to the job until expiry/eviction.
        return JSONResponse({"job_id":job_id, "status":"queued", "status_url":f"/api/jobs/{job_id}"}, status_code=202)
    finally:
        if path is not None:
            path.unlink(missing_ok=True)
        await file.close()


def process_large_job(job_id, path, filename, sample_rate, datatype, meta, wav_mode, margin_db, mode,
                      fixed_threshold_db, cancel_event):
    def progress(done, total, message):
        with LOCK:
            JOBS[job_id].update(status="processing", processed_samples=done, total_samples=total,
                                progress=done/total, message=message)
    try:
        capture = open_disk_capture(path, filename, sample_rate, datatype, meta, wav_mode)
        progress(0, len(capture.iq), "Metadata validated. Scanning the complete capture in overlapping blocks.")
        result = analyze_disk_capture(capture, margin_db, mode, fixed_threshold_db, progress,
                                      cancel_check=cancel_event.is_set)
        result.response.update(job_id=job_id, expires_in_seconds=TTL_SECONDS)
        with LOCK:
            JOBS[job_id].update(status="complete", capture=capture, result=result, created=monotonic(), progress=1,
                                message="Complete capture analyzed.")
            prune_jobs()
    except AnalysisCancelled as exc:
        with LOCK:
            JOBS[job_id].update(status="cancelled", created=monotonic(), message=str(exc))
            path.unlink(missing_ok=True)
            JOBS[job_id].pop("path", None)
    except Exception as exc:
        with LOCK:
            JOBS[job_id].update(status="failed", error=str(exc), created=monotonic(), message="Analysis failed; no partial result published.")
            path.unlink(missing_ok=True)
            JOBS[job_id].pop("path", None)
    finally:
        COMPUTE.release()


@app.get("/api/jobs/{job_id}")
def job_status(job_id: str):
    with LOCK:
        prune_jobs()
        job = JOBS.get(job_id)
        if job is None:
            raise HTTPException(404, "Job expired or missing. Analyze the capture again.")
        state = job.get("status", "complete")
        body = {"job_id":job_id, "status":state,
                **{k:job.get(k) for k in ("processed_samples", "total_samples", "progress", "message")}}
        if state == "complete":
            body["result"] = job["result"].response
        if state == "failed":
            body["error"] = job["error"]
        return body


@app.post("/api/jobs/{job_id}/cancel")
def cancel_job(job_id: str):
    """Request cancellation of a running large-capture analysis. Best-effort
    and asynchronous: analyze_disk_capture only polls cancel_check between a
    block scan and between track-enrichment steps (see large_capture.py), so
    the job may take a moment to actually stop; poll GET .../jobs/{job_id}
    for status=="cancelled" to confirm. Cancelling a job that has already
    reached a terminal state (complete/failed/cancelled) is a no-op, not an
    error -- the request is inherently racing the job's own completion.
    """
    with LOCK:
        job = JOBS.get(job_id)
        if job is None:
            raise HTTPException(404, "Job expired or missing.")
        cancel_event = job.get("cancel_event")
        if cancel_event is None:
            raise HTTPException(409, "This job has no in-progress analysis to cancel "
                                     "(it completed synchronously or was never a large-capture job).")
        already_done = job.get("status") in ("complete", "failed", "cancelled")
        cancel_event.set()
        return {"job_id": job_id, "requested": True,
                "message": "Already finished; cancellation has no effect." if already_done
                else "Cancellation requested; poll job status for confirmation."}


@app.post("/api/jobs/{job_id}/rerun")
def rerun(job_id: str, margin_db: float = Query(8, ge=3, le=30), mode: str = Query("adaptive"),
          fixed_threshold_db: float | None = Query(None)):
    """Re-run detection against the already-loaded capture with a new CFAR
    margin, without re-uploading or re-validating the file."""
    job = get_job(job_id)
    if not COMPUTE.acquire(blocking=False):
        raise HTTPException(429, "Another analysis is running. Try again when it finishes.")
    try:
        c = job["capture"]
        started = monotonic()
        if isinstance(c.iq, DiskSamples):
            # analyze_disk_capture already enriches each finished track with a
            # bounded per-track re-read (see large_capture.enrich_track); a
            # second pass here would apply analyze_candidate's whole-capture
            # assumptions directly to the disk-backed reader with each
            # track's global sample bounds, which it does not support.
            r = analyze_disk_capture(c, margin_db, mode, fixed_threshold_db)
        else:
            r = analyze_capture(c, margin_db, mode, fixed_threshold_db)
            r.response["detections"] = [analyze_candidate(c, d, noise_floor=r.noise_floor)
                                        for d in r.response["detections"]]
        r.response["elapsed_ms"] = (monotonic()-started)*1000
        r.response["job_id"] = job_id
        r.response["expires_in_seconds"] = TTL_SECONDS
        with LOCK:
            job["result"] = r
            job["layers"] = {}  # Detection indices/content changed; drop stale cache.
            job["created"] = monotonic()
        return r.response
    except (ValueError, KeyError, TypeError) as exc:
        raise HTTPException(422, {"code": "invalid_capture", "message": str(exc)}) from exc
    finally:
        COMPUTE.release()


@app.post("/api/demo")
def demo(kind: str = Query("iq", pattern="^(iq|audio)$"), margin_db: float = Query(8, ge=3, le=30)):
    if kind == "audio":
        path = DEMO/"audio_demo.wav"
        if not path.exists():
            raise HTTPException(503, "Bundled demo file is missing. Run the synthetic generator.")
        return run_analysis(path.name, path.read_bytes(), margin_db=margin_db)
    path = DEMO/"demo.sigmf-data"
    if not path.exists():
        raise HTTPException(503, "Bundled demo file is missing. Run the synthetic generator.")
    return run_analysis(path.name, path.read_bytes(), metadata=(DEMO/"demo.sigmf-meta").read_bytes(), margin_db=margin_db)


@app.get("/api/demo/files/{filename}")
def demo_file(filename: str):
    if filename not in {"demo.sigmf-data", "demo.sigmf-meta", "demo.truth.json", "audio_demo.wav"}:
        raise HTTPException(404, "Unknown demo file.")
    return FileResponse(DEMO/filename, filename=filename)


@app.get("/api/spectrogram/{job_id}")
def spectrogram(job_id: str, width: int = Query(600, ge=32, le=1024), height: int = Query(360, ge=32, le=768)):
    job = get_job(job_id)
    r, c = job["result"], job["capture"]
    # Maximum-power pooling keeps a brief signal visible when many STFT pixels
    # share one screen pixel; display color limits come from the actual capture.
    fi = np.linspace(0, len(r.frequencies), min(width, len(r.frequencies))+1, dtype=int)
    ti = np.linspace(0, len(r.times), min(height, len(r.times))+1, dtype=int)
    reduced_f = np.maximum.reduceat(r.power, fi[:-1], axis=0)
    reduced = np.maximum.reduceat(reduced_f, ti[:-1], axis=1)
    magnitude = db(reduced).T
    df = c.sample_rate/r.response["settings"]["nfft"]
    frequency_edges = np.clip(np.r_[r.frequencies[fi[:-1]]-df/2, r.frequencies[-1]+df/2],
                             0 if c.metadata["source_kind"] == "audio" else -c.sample_rate/2, c.sample_rate/2)
    hop = r.response["settings"]["hop_samples"]/c.sample_rate
    time_edges = r.time_edges[ti] if hasattr(r, "time_edges") else np.r_[r.times[ti[:-1]]-hop/2, r.times[-1]+hop/2]
    time_edges[0], time_edges[-1] = 0, len(c.iq)/c.sample_rate
    return {"magnitude_db": np.round(magnitude, 2).tolist(), "frequency_edges_hz": frequency_edges.tolist(),
            "time_edges_seconds": time_edges.tolist(), "min_db": float(np.percentile(magnitude, 5)),
            "max_db": float(np.max(magnitude)), "aggregation": "maximum power per viewport cell",
            "unit": c.metadata["power_unit"]}


def detection_and_layers(job_id, detection_id):
    job = get_job(job_id)
    ds = job["result"].response["detections"]
    if detection_id < 0 or detection_id >= len(ds):
        raise HTTPException(404, "Candidate not found.")
    with LOCK:
        if detection_id not in job["layers"]:
            builder = build_disk_layers if isinstance(job["capture"].iq, DiskSamples) else build_layers
            layers, clips = builder(job["capture"], job["result"], ds[detection_id])
            for layer in layers:
                if layer["id"] in clips:
                    layer["audio_url"] = f"/api/detections/{job_id}/{detection_id}/audio/{layer['id']}"
            job["layers"][detection_id] = (layers, clips)
            while len(job["layers"]) > 4:
                job["layers"].pop(next(iter(job["layers"])))
    return job, ds[detection_id], job["layers"][detection_id]


@app.get("/api/detections/{job_id}/{detection_id}/layers")
def layers(job_id: str, detection_id: int):
    _, _, (layers, _) = detection_and_layers(job_id, detection_id)
    return layers


@app.get("/api/detections/{job_id}/{detection_id}/audio/{layer_id}")
def audio(job_id: str, detection_id: int, layer_id: int):
    _, _, (_, clips) = detection_and_layers(job_id, detection_id)
    if layer_id not in clips:
        raise HTTPException(404, "No audio applies to this layer.")
    return Response(clips[layer_id], media_type="audio/wav")


@app.get("/api/detections/{job_id}/{detection_id}/envelope")
def envelope(job_id: str, detection_id: int):
    job = get_job(job_id)
    if detection_id < 0 or detection_id >= len(job["result"].response["detections"]):
        raise HTTPException(404, "Candidate not found.")
    d = job["result"].response["detections"][detection_id]
    env = job["result"].envelopes[detection_id]
    return {"waveform": env["waveform"] if "waveform" in env else waveform(env["values"], job["capture"].sample_rate), "threshold": env["threshold"],
            "threshold_description": "Maximum block envelope threshold (summary)" if "waveform" in env else "Envelope threshold",
            "pulse_windows": d["pulse_windows"], "pulse_width_samples": d["pulse_width_samples"], "pri_samples": d["pri_samples"]}


@app.get("/api/detections/{job_id}/{detection_id}/symbol-rate-diagnostic")
def symbol_rate_diagnostic_endpoint(job_id: str, detection_id: int):
    job = get_job(job_id)
    ds = job["result"].response["detections"]
    if detection_id < 0 or detection_id >= len(ds):
        raise HTTPException(404, "Candidate not found.")
    return symbol_rate_diagnostic(job["capture"], ds[detection_id])


@app.get("/api/export/{job_id}")
def export(job_id: str, format: str = Query("json", pattern="^(json|sigmf)$")):
    job = get_job(job_id)
    r = job["result"].response
    if format == "sigmf":
        return export_metadata(r["metadata"], r["detections"])
    return r["detections"]


@app.get("/api/validation/fine-classification-accuracy")
def fine_classification_accuracy():
    """Real measured pass/fail trials from the recorded downstream validation
    run, aggregated by modulation kind and SNR. Not derived from live capture
    data; it's the same evidence documented in ESTIMATE_CLASSIFY.md."""
    path = DOCS / "estimate-classify-validation.json"
    if not path.exists():
        raise HTTPException(503, "Validation evidence file is missing.")
    trials = json.loads(path.read_text())["fine_rule"]
    buckets = defaultdict(lambda: {"trials": 0, "passed": 0})
    for t in trials:
        b = buckets[(t["kind"], t["snr_db"])]
        b["trials"] += 1
        b["passed"] += bool(t["would_pass_requested_rule"])
    curve = [{"kind": kind, "snr_db": snr, "trials": b["trials"], "passed": b["passed"],
              "accuracy": b["passed"] / b["trials"]}
             for (kind, snr), b in sorted(buckets.items())]
    return {"source": "docs/estimate-classify-validation.json", "measure": "fine-classification phase-cluster rule pass rate",
            "curve": curve}
