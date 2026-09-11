# Estimate and Classify implementation plan

**Goal:** Add plain downstream Python functions without changing Detect, API schemas/routes, or frontend behavior.

**Architecture:** `estimate.py` consumes `Capture` and a Detect candidate and returns an enriched copy. `classify.py` builds on its output. Reuse Detect's Welch/noise and band-isolation helpers. Keep the direct noise-subtracted centroid separate from the interpolated peak used for raised tones. Missing evidence produces nulls with status, never a fabricated measurement.

**Tech stack:** Existing NumPy, SciPy, pytest; no new dependencies.

**Spec:** User's attached SIH26147 request and approved centroid/band-isolation amendment. Frequency tolerance remains 2%; coarse family must be correct at >=0 dB.

- [ ] Stage 1: test all 12 generated continuous captures, metadata offset, pulse averaging/union, bandwidth definitions, scale invariance and unknown cases; implement Estimate; run full suite and commit.
- [ ] Stage 2: test isolated-envelope family and heuristic confidence across all 12 captures, varying-envelope and invalid cases; implement coarse classification; record every measured row; run full suite and commit.
- [ ] Stage 3: retain separate Welch peak/log-parabolic interpolation; test M=2/4 refinement including independent BPSK 150 kHz offset at 10 dB across seeds, absolute-frequency handling and nulls; run full suite and commit only if validated.
- [ ] Stage 4: test circular-spread labels on BPSK/QPSK at >=10 dB and FM rejection. If reliability fails, ship null fine outputs and explicitly stop at fallback rung 2.
- [ ] Stage 5 (only if Stage 4 validates): test 500 Hz symbol truth at 10/5 dB and null behavior at 0/-5 dB, use lowest significant harmonic and bandwidth/SNR gates; run full suite and commit.
- [ ] Re-run `backend.validate`; update status/limitations with measured evidence, public function usage, limitations and exact fallback rung; verify scope and commit documentation.

The current checkout is clean and already a Git repository. Work proceeds inline here with explicitly scoped commits. The original 42-test suite passed before implementation.
