# Large-file processing

The backend accepts captures up to 2 GiB and has been exercised end-to-end with a real 1 GiB upload. Files larger than 1 MiB use asynchronous disk-backed analysis so memory does not scale with capture duration.

## Request lifecycle

1. FastAPI copies the multipart stream into `backend/data/jobs/` in 8 MiB pieces while enforcing the 2 GiB limit.
2. The service validates metadata and claims the single compute semaphore.
3. It returns HTTP 202 with a job ID.
4. One background executor thread opens a bounded disk reader and scans the capture.
5. `/api/jobs/{id}` reports processed and total samples.
6. The result becomes visible only after the complete scan succeeds.
7. Failed jobs remove their retained upload and expose an error; no partial result is published.

The multipart framework may spool the incoming request before application copying, so temporary disk demand can approach twice the upload size during submission. Plan free space accordingly.

## Disk reader guarantees

`DiskSamples` supports contiguous slices only. It rejects stepped/indexed access and any requested window larger than two million samples. Each slice:

- seeks to the exact byte offset;
- reads the exact required byte count;
- converts and normalizes the declared encoding;
- assembles IQ or selects the chosen audio channel;
- validates finite values and safe magnitude.

The class deliberately prevents accidental whole-file NumPy conversion. Late corruption is found when its block is read, so a valid prefix cannot hide NaN or infinite values at the end.

For WAV, SciPy maps the header and sample storage long enough to discover rate, dtype, offset, count, and channel count. The persistent analysis reader then performs bounded file reads. Packed 24-bit WAV cannot be memory-mapped by this implementation and must be converted to 32-bit PCM or float.

## Block geometry

The default core block is 524,288 samples. Blocks align to the 256-sample STFT hop. Each core is analyzed with context on both sides:

```text
guard = align_to_256(min(core_block / 2, max(4096, samples_in_1_ms)))
```

The guard prevents a file-processing boundary from becoming an artificial pulse or filter edge. Only core samples contribute to final overview cells, annotations, and progress. The final partial block is processed through the true sample count.

## Detection and display memory

Every local block receives the full in-memory detector, including full-resolution STFT, thresholding, candidate association, isolation, and envelope timing. The algorithm does not subsample before detection.

For the dashboard, block spectrogram frames are maximum-pooled into at most 768 time rows. The retained overview therefore stays bounded while capture duration grows. Maximum pooling preserves brief high-power events better than averaging for this display purpose.

The aggregate Welch PSD is a core-sample-weighted average of block PSD power. The result stores the median block noise floor and its minimum/maximum range. Its displayed threshold is a summary; each block's local threshold drives its own detections.

## Candidate merge rules

A candidate can merge with a track from the immediately previous core block when frequency overlap is at least 50% of the narrower candidate bandwidth. On merge:

- sample extent expands to include both pieces;
- frequency bounds expand to their union;
- confidence keeps the lower constituent score;
- `needs_review` is true if any piece needs review;
- pulsed state is true if any piece is pulsed;
- overlapping pulse windows are joined.

After all blocks finish, pulse width and PRI are recomputed from the complete merged window list. Candidates absent for a full intervening block do not merge. This is boundary continuity logic, not frequency-hopping tracking.

The scan fails explicitly if it would exceed 4,096 candidates or 200,000 pulse windows. It does not truncate these lists silently; the operator must split a pathologically complex capture for review.

## Progress and recovery

Progress is based on `core_end / total_samples`. Messages identify the current block and exact samples scanned. The browser stores the active job ID in same-tab `sessionStorage`, allowing polling to resume after a page refresh.

Job state itself is in backend memory. A process restart loses the registry, so old browser IDs return 404 even if a temporary file remains. This prototype has no durable queue, restart recovery, multi-user scheduling, or distributed worker.

## Retention and cleanup

- Completed and failed job records expire 1,800 seconds after completion.
- The newest three finished jobs are retained; older finished jobs are evicted.
- At most four candidates' layer caches are retained per job.
- Server-created uploads are deleted on failure, expiry, or eviction.
- Running/queued jobs are not removed by normal expiry pruning.
- A hard server interruption can leave files in `backend/data/jobs/`; remove them while the backend is stopped after confirming no live job needs them.

The backend permits one analysis at a time and returns 429 for another request. Run one Uvicorn worker; separate worker processes would have separate in-memory registries and semaphores.

## Bounded Signal Breakdown

Layer generation never isolates an entire gigabyte capture. It reads at most one million samples and no more than eight seconds, starting slightly before the candidate. The response labels the exact preview sample/time interval. Full-file detection and the pooled full-capture envelope remain available independently of this preview.

## Measured 1 GiB integration run

`backend/large-file-validation.json` records the checked run:

| Measurement | Recorded value |
|---|---:|
| File bytes | 1,073,741,824 |
| Complex `cf32_le` samples scanned | 134,217,728 |
| Ground-truth bursts | 3 |
| Candidate count | 3 |
| All bursts found | yes |
| Burst locations | near a core boundary, near the middle, and near the tail |
| Peak backend working set | 263.90 MiB |
| Wall time | 80.34 s |
| Analysis time | 67,953.04 ms |
| Spectrogram endpoint verified | yes |
| Tail candidate layers verified | yes |

The exact burst sample ranges are stored in the JSON artifact. This measurement demonstrates bounded processing on the tested Windows machine and fixture. It is not a general throughput or hardware guarantee.

## Running the optional check

With the backend and frontend running, identify the backend Python process and run:

```powershell
.\.venv\Scripts\python.exe -m backend.tests.run_gib_check --backend-pid <running-python-process-id>
```

The script creates a real 1 GiB temporary capture, uploads it through Vite/FastAPI, waits for complete sample coverage, checks all three burst locations, fetches the bounded spectrogram and tail layers, measures process memory, and removes its source fixture on exit. The server-side copy follows ordinary retention rules.

This test is intentionally opt-in because it needs more than 1 GiB of temporary disk space and roughly a minute or more of exclusive compute time.
