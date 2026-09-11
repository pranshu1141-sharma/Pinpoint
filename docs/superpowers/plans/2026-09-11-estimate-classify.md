# Estimate and Classify implementation plan

**Goal:** Add plain downstream Python functions without changing Detect, API schemas/routes, or frontend behavior.

**Architecture:** `estimate.py` consumes `Capture` and a Detect candidate and returns an enriched copy. `classify.py` builds on its output. Reuse Detect's Welch/noise and band-isolation helpers. Keep the direct noise-subtracted centroid separate from the interpolated peak used for raised tones. Missing evidence produces nulls with status, never a fabricated measurement.

**Tech stack:** Existing NumPy, SciPy, pytest; no new dependencies.

**Spec:** User's attached SIH26147 request and approved centroid/band-isolation amendment. Frequency tolerance remains 2%; coarse family must be correct at >=0 dB.

- [x] Stage 1: all 12 center/SNR checks pass; bandwidth, pulse/union, offset, scale and unknown checks pass. Full suite 61 passed; commit `5b2ed83`.
- [x] Stage 2: all nine >=0 dB coarse family checks pass; measured all 12 rows. Full suite 76 passed; commit `fb14f1f`.
- [x] Stage 3: separate peak/log-parabolic path validated; ten-seed 150 kHz BPSK mean absolute error 0.4041 Hz. Full suite 80 passed; commit `4304f09`.
- [x] Stage 4 explored: BPSK 5/5, QPSK 2/5 at each 20/10 dB. Stop at fallback rung 2, emit null fine labels with measured spread. Preserve failing QPSK majority targets as strict expected failures.
- [x] Stage 5 decision: not attempted because Stage 4 did not validate. Null/status behavior tested at 20/10/5/0/-5 dB. Generator truth records 500 Hz; no symbol-rate accuracy claim.
- [x] Re-run `backend.validate` (12/12 continuous recall); author reproducible measurement report, usage, limitations and status updates. Final review, scope verification and documentation commit follow.

The current checkout is clean and already a Git repository. Work proceeds inline here with explicitly scoped commits. The original 42-test suite passed before implementation.
