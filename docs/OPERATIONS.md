# Local operation and maintenance

This project runs as two local processes: a FastAPI analysis service and a Vite React dashboard. The documented configuration is intended for one operator on one machine.

## Prerequisites

- Python 3.11–3.13
- Node.js 20.19+ or 22.12+
- npm
- Enough free disk for dependencies, generated fixtures, and approximately twice the largest upload during multipart handling

The current development environment used Python 3.13 and Node.js 24.

## First-time setup

From the project root:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend/requirements.txt
npm --prefix frontend ci
```

On macOS or Linux, replace `.\.venv\Scripts\python.exe` with `.venv/bin/python`.

`requirements.txt` defines supported direct ranges. `requirements-lock.txt` records the exact Python environment used for repeatable installation. `npm ci` uses the checked-in npm lock file.

## Start the application

Backend terminal:

```powershell
.\.venv\Scripts\python.exe -m uvicorn backend.api.main:app --host 127.0.0.1 --port 8000
```

Frontend terminal:

```powershell
npm --prefix frontend run dev
```

Open:

- dashboard: `http://127.0.0.1:5173/`
- OpenAPI UI: `http://127.0.0.1:8000/docs`
- health check: `http://127.0.0.1:8000/api/health`

Use one Uvicorn worker. Jobs, retention, and the compute semaphore are process-local; multiple workers would give inconsistent job visibility.

## Expected startup behavior

The dashboard initially checks backend health. When connected, it loads the bundled IQ demo unless the browser tab is already tracking a large job. A healthy backend returns `status: connected`, `stage: detect`, and the 2 GiB upload limit.

If the UI says **Not connected**:

1. confirm the FastAPI process is still running;
2. open the health URL directly;
3. confirm ports 5173 and 8000 are not occupied by another program;
4. read the backend terminal for import, dependency, or file errors;
5. restart Vite if its proxy was started before configuration changed.

## Routine quality checks

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests -q
.\.venv\Scripts\python.exe -m backend.validate
npm --prefix frontend run build
```

Generate fixtures again when changing detector assumptions or the demo:

```powershell
.\.venv\Scripts\python.exe -m backend.pipeline.synth_gen
```

Build output in `frontend/dist/` and Python/npm caches are generated artifacts. Do not review them as authored source.

## Capture workflow

1. Select one capture and optional matching SigMF metadata.
2. For raw `.iq`, enter the exact sample rate and datatype.
3. For ambiguous stereo WAV, choose its known interpretation.
4. Set the adaptive margin; keep 8 dB for the baseline unless the capture justifies a change.
5. Start analysis and wait for upload and scan phases to finish.
6. Inspect candidate bounds, confidence/review status, waterfall, PSD, pipeline log, and Signal Breakdown.
7. Export candidate JSON or annotated SigMF metadata.

An analysis with zero candidates is a valid completed result. It means no region passed the implemented rules at the selected margin.

## Large jobs

Uploads above 1 MiB run asynchronously. The service allows one active analysis. A second analysis receives HTTP 429 and should be retried after the first finishes.

The page can resume polling a known job after refresh in the same tab. A backend restart clears that job registry. In that case, submit the capture again.

Finished jobs expire after 30 minutes and only the newest three are retained. Export or record needed results before expiry.

## Temporary storage

Server copies live under `backend/data/jobs/`. Normal failure, expiry, and eviction remove them. A forced process termination can leave an orphan.

To clean orphaned files:

1. stop the FastAPI process;
2. confirm no analysis is running;
3. inspect `backend/data/jobs/`;
4. remove only server-created temporary captures in that directory;
5. restart the backend.

Never point cleanup at capture source folders. The application itself checks that a file belongs to the jobs directory before deleting it.

## Common operational problems

| Symptom | Likely cause | Action |
|---|---|---|
| Raw IQ asks for more input | Rate/datatype cannot be inferred | Enter both fields or select matching SigMF metadata. |
| Stereo WAV asks for a choice | Quadrature evidence is inconclusive | Use known provenance to select IQ, left audio, or right audio. |
| Upload rejected at 2 GiB | Hard request-size limit | Split the capture. |
| Large 24-bit WAV rejected | Packed encoding cannot be memory-mapped | Convert to 32-bit PCM or float WAV. |
| 429 busy response | Single compute slot is occupied | Wait for the active job to finish. |
| Job missing after refresh | Job expired, was evicted, or backend restarted | Analyze again. |
| No audio control on IQ | IQ is complex baseband | Inspect visual layers; demodulation is not implemented. |
| Very complex scan fails | Candidate/window safety limit reached | Split the capture by time or frequency for review. |
| Frontend build fails | TypeScript/schema or dependency mismatch | Run `npm ci`, then inspect the first build error. |

## Updating dependencies

For Python, change supported direct ranges deliberately in `backend/requirements.txt`, install and test, then refresh `backend/requirements-lock.txt` from the verified environment. For the frontend, update `package.json` with npm so `package-lock.json` changes with it. Review major-version migration notes before accepting generated lock changes.

After any dependency update, run the backend suite, validation script, and frontend build. Numerical library updates deserve comparison against `backend/validation-report.json` rather than only a pass/fail check.

## Deployment boundary

The present service has no authentication, encrypted transport, durable database, malware sandbox, multi-tenant isolation, or distributed queue. Bind it to loopback for local demonstrations. Production deployment would need those controls plus configurable storage, logging, monitoring, quotas, and job persistence.
