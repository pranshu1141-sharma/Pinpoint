# Real-data triage (Phase 1 of the field-validation roadmap item)

This is the project's first run against a capture it did not generate itself. Every prior accuracy claim in this repo (`docs/ESTIMATE_CLASSIFY.md`, `docs/PROJECT_STATUS.md`, `backend/validation-report.json`) comes exclusively from `backend/pipeline/synth_gen.py`'s synthetic generator. This document is evidence only — nothing here was fixed, and nothing here should be read as a broader accuracy claim than the one file it describes.

## Source

**GRCon24 CTF "sigid3"**, one of the signal-identification challenge recordings from the 2024 GNU Radio Conference, obtained via [IQEngine](https://iqengine.org/browser)'s public example-recordings browser (backed by the GNU Radio project's community SigMF repository). Author: Clayton Smith, per the recording's own SigMF metadata.

- Format: SigMF (`.sigmf-data` + `.sigmf-meta`), `cf32_le`, real hardware capture (not stated to be synthetic; GRCon CTF signal-ID challenges are built from off-air or hardware-sourced signals by design).
- Full recording: 346,648 samples, 250 kHz sample rate, RF center 929.25 MHz (US ISM/paging band), 2,773,184 bytes.
- A trimmed 131,072-sample slice (first 0.524 s, 1,048,576 bytes exactly) was cut to fit this project's synchronous ≤1 MiB upload path (the >1 MiB async path is a separate, already-known gap — see `docs/LIMITATIONS_AND_ROADMAP.md`).
- Both files are stored under `backend/data/real/` (`sigid3_full.*`, `sigid3_trimmed.*`); regenerate via `python -m backend.triage_real`.

## What ran, and how it was cross-checked

The full recording and the trimmed slice were each run through Detect + Estimate + Classify three independent ways, and all three agreed exactly:

1. `python -m backend.triage_real` (direct pipeline function calls; writes `backend/triage-report.json`).
2. `curl` against a live `uvicorn` instance's real `POST /api/analyze` endpoint (the same code path a real upload hits).
3. The actual frontend dashboard's "Open File" flow (not the bundled demo buttons), visually inspected.

## What it found

Two candidates were detected in the trimmed slice, both also present (with consistent bounds) in the full recording:

| | Candidate 0 | Candidate 1 |
|---|---|---|
| Baseband range | 22.34–49.19 kHz | 49.93–51.64 kHz |
| RF center (declared 929.25 MHz + offset) | ~929.287 MHz | ~929.301 MHz |
| SNR | 13.93 dB | 13.93 dB |
| `estimate_status` | `estimated` | `partial (half-power lobe truncated by candidate band)` |
| `modulation_family` | `constant-envelope` (env. variation 0.051) | `varying-envelope` (env. variation 0.53) |
| Refinement | tried, order 2 selected | not attempted (requires constant-envelope) |
| `fine_modulation_status` | `not reliably classified (phase spread above threshold)`, spread 1.18 rad | `not reliably classified (no phase refinement)` |
| `symbol_rate_status` | `not reliably estimated (requires a confirmed PSK fine label)` | same |
| Confidence / review | 90%, not flagged | 54%, **flagged for review** |

*(Table shows the trimmed slice's numbers; the full recording's values are the same to the precision shown here except where the "new finding" below discusses them separately.)*

None of the six known failure modes from the original investigation (DC spike/IQ imbalance, non-flat noise floor, sample-rate mismatch, clipping, multi-emitter interference, frequency drift/multipath) were flagged by `triage_real.py`'s heuristic checks on this file — `dc_spike_suspected`, `noise_floor_nonflat`, and `clipping_suspected` were all `False` for both the trimmed and full versions. This one recording happens to be clean of the most common real-hardware artifacts; that is a property of this specific file, not a general claim about real captures. (`noise_floor_nonflat` actually measures whole-PSD dynamic range, not the noise floor specifically — it would trip on a strong narrowband signal too, so "not flagged" here is a weaker claim than "the noise floor is provably flat.")

**What actually worked:** the pipeline found real energy, at real frequencies, with a real (Detect-stage) confidence split that correctly flagged the weaker candidate for review. Fine PSK classification correctly declined to guess on a real signal it wasn't confident about — refinement selected an M=2 (BPSK) hypothesis, but the phase-cluster spread (1.18 rad) sat well above the 0.8 rad acceptance threshold, and the pipeline reported "not reliably classified" rather than a false "bpsk" label. This is exactly the intended honest-degradation behavior, and it held on the first unseen real file tried.

**A new finding not in the original six:** the refined center frequency was **not stable** between the trimmed and full versions of the same recording — 929,292,300 Hz (trimmed, 0.524 s) vs. 929,282,700 Hz (full, 1.387 s), a ~9.6 kHz difference. The synthetic validation in `docs/ESTIMATE_CLASSIFY.md` reports sub-Hz refinement error on its BPSK fixtures; nothing in this repo has previously tested whether that refinement is stable as more real, non-BPSK-shaped data is included. Candidate 0 is not confidently classified as any specific digital modulation (the fine-classification step explicitly declined), so this instability may simply reflect refinement locking onto different transient structure in a signal that isn't actually constant-modulus PSK — but it's a genuine, previously undocumented observation that only surfaced from real data, and it is not explained or investigated further here.

## What this phase does and does not establish

This is one file, from one real source, at one SNR, with (per the heuristic checks) no severe hardware artifacts present. It does not establish field performance, a false-alarm rate, or that the pipeline is robust to DC offset/colored noise/clipping/drift in general — those failure modes simply didn't happen to appear in this particular recording. Establishing that requires the multi-source, multi-condition dataset described in `docs/LIMITATIONS_AND_ROADMAP.md`'s roadmap item 1, which remains open.

## Reproduce

```
source .venv/bin/activate
python -m backend.triage_real
```

Writes `backend/triage-report.json` (per-file, per-candidate detail) and prints a console summary.
