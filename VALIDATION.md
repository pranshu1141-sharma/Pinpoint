# Validation ledger

This file tracks phase-by-phase acceptance evidence for the four gaps closed
after `docs/PROJECT_STATUS.md`'s original audit: symbol-timing recovery, QAM
order resolution, confidence calibration, and real-file coverage. Each phase
is reported here whether it passed, partially passed, or could not be
completed, per the instruction that a failed phase with an honest report is
still a success of the process.

None of the work below claims demodulation, decoding, or bit recovery. It is
timing/order/calibration measurement only.

## Phase 1 -- Symbol-timing recovery

**Built:** `backend/pipeline/timing_recovery.py`, a Gardner timing-error-detector
loop: a linear-interpolating resampler, a Gardner TED (`e[n] = Re{y[n-1/2]*
(y[n]-y[n-1])}`), and a standard 2nd-order proportional-integral loop filter
(gains from Rice, *Digital Communications: A Discrete-Time Approach*). Output
fields: `timing_offset_hat` (converged fractional-symbol sampling phase),
`timing_offset_trace` (per-symbol history), `lock_indicator`, `residual_error`.
It is timing recovery only -- it locates symbol centers, not decoded bits, and
does not change `classify.py`'s existing SYMBOL_RATE_LABELS boundary.

**Tested:** `backend/tests/test_timing_recovery.py`.
- Acceptance test: BPSK/QPSK, SNR in {10, 20} dB, 20 seeds each, against a
  purpose-built root-raised-cosine (beta=0.35) synthetic fixture with a known
  injected fractional sample-timing offset drawn uniformly from [-0.2, 0.2]
  symbols (this project's own `synth_gen.py` fixtures are not used here: they
  are shaped for spectral-occupancy realism, not for injecting a precisely
  known sub-sample timing offset).
- Real-capture check: for each of the three bundled real captures
  (`sigid3_full`, `sigid3_trimmed`, `grcon23_qam`), run the existing
  Detect -> Estimate -> classify pipeline, and for every candidate that
  already receives a confirmed bpsk/qpsk/8psk/ask label and `symbol_rate_hz`,
  check that `gardner_timing_recovery`'s own `lock_indicator` agrees (is
  `True`).

**Passed:**
- All 20/20 seeds at both 10 dB and 20 dB, both BPSK and QPSK, land within
  1% of a symbol period (measured max error 0.63%, well inside the 1%
  target) and report `lock_indicator=True`.
- A real, measured bug was found and fixed during validation: normalizing the
  Gardner error by each sample's own instantaneous power (the naive
  per-symbol approach) correlates the normalizer with the numerator for
  real-alphabet modulations like BPSK and biased the loop's equilibrium point
  by ~2.2% of a symbol period even at 40 dB SNR -- enough by itself to fail
  the 1% target. Normalizing by the segment's fixed average power instead
  reduced that bias to <0.04% at 40 dB. This is documented in the module's
  docstring so the fix isn't silently lost to a future refactor.
- `lock_indicator` is computed from the loop-filtered offset trace's
  internal self-consistency (its first- and second-half circular means must
  agree to within 1% of a symbol), not the raw per-symbol Gardner error
  (measured RMS 0.3-0.6 even when well converged -- too noisy to threshold
  directly). Measured false-lock rate on pure noise (no signal at all): 3/20
  seeds (15%) at the chosen threshold. This is a real, documented limitation,
  not zero -- `lock_indicator` is a diagnostic for candidates Detect/Estimate
  has already SNR-gated, not a standalone signal-presence test.

**Could not fully validate:**
- The real-capture agreement check could not be exercised: none of the three
  bundled real captures currently produce a confirmed bpsk/qpsk/8psk/ask
  label with an estimated `symbol_rate_hz` through the existing
  Detect/Estimate/classify pipeline (all three tests skip with "no confirmed
  bpsk/qpsk/8psk/ask candidate to check"). This means the second half of the
  Phase 1 acceptance criterion -- "on real captures where a symbol rate is
  already estimated, the timing lock indicator agrees with the existing
  symbol-rate confidence" -- has no real data to check against yet. This is
  the same gap Phase 4 (real-file coverage) exists to close; once Phase 4
  adds real captures that do clear classify.py's existing confirmed-label
  gate, `test_lock_indicator_agrees_with_confirmed_symbol_rate_on_real_captures`
  will exercise them automatically (it is written against exactly that
  condition already).
- The validated 1% accuracy assumes a long, slowly-tracking loop (loop
  bandwidth 0.001 of the symbol rate, needing on the order of tens of
  thousands of symbols to settle to that precision) and offsets within
  [-0.2, 0.2] symbols of the initial sampling grid. Larger offsets (tested up
  to +/-0.4 symbols) still converge correctly with this loop but were not
  swept as densely near the +/-0.5 edge, where a Gardner detector's S-curve
  is known to be more fragile. A short real capture (few thousand symbols)
  may not give this specific configuration enough time to settle to 1%; that
  tradeoff (settling time vs. steady-state accuracy) is inherent to any
  timing-recovery loop design and is documented in the module rather than
  hidden behind a single "it works" claim.

Reproduce: `cd backend && python3 -m pytest tests/test_timing_recovery.py -v`

## Phase 2 -- QAM order resolution

**Built:** `backend/pipeline/qam_order.py`, wired into `classify.analyze_candidate`
for candidates already carrying the existing `fine_modulation_label == "qam"`
flag (classify.py's prior best-effort, order-unresolved path is unchanged and
still runs first). New pieces:
- `estimate_qam_symbol_rate`: a delay-and-multiply symbol-rate estimator on
  the squared-magnitude envelope (mirrors `classify.estimate_symbol_rate`'s
  structure, generalized from the real-part nonlinearity to one that also
  responds to QAM's joint amplitude/phase transitions), gated at
  `QAM_ORDER_MIN_SNR_DB = 15` dB.
- `resolve_qam_order`: runs Phase 1's `gardner_timing_recovery` at the
  estimated symbol rate, then classifies the recovered symbols using the
  normalized fourth-order moment `kappa = E[|s|^4]/E[|s|^2]^2` (a standard
  blind-modulation-order statistic), with the known AWGN contribution
  removed from the moments using the candidate's own measured SNR
  (`denoised_kappa`). New output fields: `qam_symbol_rate_hz`, `qam_order`
  (16/64/256 or `None`), `qam_order_confidence`, `constellation_family`
  (`"square-qam"`/`"apsk"`/`None`), `qam_order_status` (always explains the
  result). `is_apsk` separately recognizes APSK constellations by checking
  whether the outermost amplitude ring's phase is close to uniformly
  distributed -- square QAM's outer ring occupies discrete, unevenly spaced
  lattice angles instead.

**Tested:** `backend/tests/test_qam_order.py`, 11 tests, all passing.
- `test_kappa_reference_values`: the module's `REFERENCE_KAPPA` table is
  checked against a 4-million-symbol noiseless Monte Carlo draw from the
  same `qam_constellation()` the tests define, not hand-copied numbers.
- Acceptance test: 16-QAM at SNR in {15, 20} dB, 20 seeds each -- order
  resolved correctly >=90% of the time (measured 100%/100% after the fix
  below).
- `test_64_vs_256_qam_stays_honestly_ambiguous`: 64-QAM and 256-QAM, 20
  seeds each at 20 dB -- asserts the classifier mostly *declines* rather than
  guessing between them (see "Could not fully meet" below).
- `test_below_validated_snr_gate_estimate_qam_symbol_rate_declines`: the
  production SNR gate (15 dB) is enforced regardless of the raw statistic's
  own capability.
- APSK: 20 seeds each at {15, 20} dB, correctly recognized >=90% of the
  time, and 20 seeds of square 16-QAM at the same SNRs confirm zero false
  APSK calls.

**Passed:**
- 16-QAM order resolution: 20/20 correct at both 15 dB and 20 dB after two
  measured fixes (below) -- meets the >=90% acceptance bar with margin.
- APSK recognition: 20/20 (both SNRs) correctly recognized, 0/20 false
  positives on square 16-QAM.
- Two real, measured bugs were found and fixed during validation:
  1. **Averaging window too short.** With only 4000 recovered symbols
     averaged into kappa, its standard deviation (~0.02-0.025) was large
     enough to occasionally push genuine 16-QAM past the 16-vs-64 decision
     margin, dropping the 20 dB acceptance run to 15/20. Widening the
     averaging tail to 8000 symbols (`QAM_ORDER_MIN_TAIL_SYMBOLS`) reduced
     that standard deviation to ~0.013-0.018 -- diagnosed and fixed with the
     same "measure the actual estimator variance, don't guess" method Phase
     1 used for its timing bias.
  2. **Missing receive-side matched filtering was 5x worse than averaging.**
     The initial synthetic test fixture used a single TX-side root-raised-
     cosine pulse only (the same style Phase 1's timing fixture used
     successfully). For kappa specifically -- far more sensitive to residual
     inter-symbol interference than a zero-crossing timing estimate is --
     this measured a 15/20 pass rate purely from data-dependent ISI on
     unlucky symbol sequences, not from AWGN. Adding a matched RX
     root-raised-cosine filter (the standard TX/RX RRC pair, whose
     combination is the zero-ISI raised-cosine response) brought this to
     20/20. **This fix could not be applied to the production pipeline**:
     `qam_order.py`'s real path (via `classify.corrected_segment`) has no
     matched filter, because the actual pulse shape/rolloff of an arbitrary
     captured signal is not known in advance. Real-file QAM order-resolution
     accuracy is therefore expected to be measurably worse than this
     synthetic, matched-filter acceptance number -- an honest, open gap, not
     a hidden one.

**Could not fully meet:**
- **64-QAM vs 256-QAM cannot be reliably distinguished**, at any SNR, with
  this estimator. Their ideal `kappa` values are only 0.0137 apart (16-QAM to
  64-QAM is 0.0618 apart, 4.5x larger), and validation measured the
  estimator's own standard deviation at realistic segment lengths (~0.013-
  0.018) to be on the same order as that gap. `QAM_ORDER_MARGIN` is
  deliberately set so the classifier declines rather than guesses in this
  regime; `test_64_vs_256_qam_stays_honestly_ambiguous` checks that a
  *confidently wrong* pick stays rare (<=8/40 across both orders' 20-seed
  runs), not that resolution succeeds. Distinguishing them reliably would
  need either far more observed symbols than any realistic capture duration
  provides, or a statistic other than this one -- out of scope for this
  pass. Per the 90%-correct acceptance bar as stated, this sub-case does not
  pass, and is reported here rather than hidden or fabricated around.
- The real-capture check analogous to Phase 1's has the same gap: none of
  the three bundled real captures produce a confirmed `"qam"` label with a
  resolvable symbol rate through the current pipeline, so `qam_order.py` has
  not been exercised on real data at all yet (only on synthetic fixtures).
  This is the same gap Phase 4 exists to close.

Reproduce: `cd backend && python3 -m pytest tests/test_qam_order.py -v`

## Phase 3 -- Confidence calibration

**Built:**
- `backend/pipeline/calibration_corpus.py`: a labeled synthetic corpus
  generator. 6 modulations (bpsk/qpsk/fm/ask/fsk/pulsed) x 6 SNRs (-5 to 20
  dB) x 2 noise colors (white, and pink/1-over-f, generated independently of
  synth_gen.py's own always-white internal noise) x 3 seeds, plus pure-noise
  captures for extra negative examples -- 484 labeled candidates in the
  train split, 485 in an independent held-out test split (different seed
  range). A candidate is labeled a true positive if its frequency window
  contains a real generated signal's center frequency, false positive
  otherwise. **Explicitly synthetic** -- ground truth comes from the
  generator, not measured real-world outcomes.
- `backend/pipeline/calibration.py`: dependency-free isotonic regression
  (a from-scratch pool-adjacent-violators implementation -- no sklearn is
  otherwise used in this project), reliability-diagram binning, ECE, and a
  minimal SVG reliability-diagram renderer (no matplotlib dependency added).
- `backend/pipeline/calibrate.py`: the script that fits and reports
  calibration, run via `cd backend && python3 -m pipeline.calibrate`. It
  fits on the train split, reports ECE on the held-out test split (the
  honest generalization number), then refits a final calibrator on the
  union of both splits for the file that ships. Outputs:
  `docs/confidence-calibration.json` (full report + both reliability
  diagrams' bin data), `docs/calibration-confidence[-evidence-based]{,-raw,
  -calibrated}.{json,svg}` (fitted calibrator + before/after SVG diagrams).
- `detect.py` wiring: every candidate now also carries
  `confidence_calibrated`, `confidence_calibration_status`,
  `confidence_evidence_based_calibrated`, and
  `confidence_evidence_based_calibration_status` (raw `confidence` and
  `confidence_evidence_based` are unchanged, so nothing that depended on
  them breaks). `confidence_calibration_status` always says either
  `"isotonic-calibrated on synthetic corpus (held-out ECE=...)"` or
  `"uncalibrated (no fitted calibrator file present)"` -- never silent.

**Tested:** `backend/tests/test_calibration.py`, 9 tests, all passing,
including a regression guard (`test_shipped_calibrator_generalizes_to_a_
fresh_held_out_corpus`) that rebuilds a *third*, independent synthetic
corpus (seeds disjoint from both calibrate.py's train and test splits) and
checks the shipped calibrator still meets a documented ECE bound -- this
catches silent drift if detect.py's underlying heuristics ever change
without rerunning `calibrate.py`.

**Passed (measured on the held-out test split, seed-disjoint from training):**

| Score | Raw ECE | Calibrated ECE |
|---|---|---|
| `confidence` | 0.372 | **0.007** |
| `confidence_evidence_based` | 0.251 | **0.100** |

- Both raw scores were substantially miscalibrated: at a nominal `confidence`
  of ~0.85, actual empirical accuracy on the labeled corpus was far lower --
  exactly the kind of gap `docs/estimate-classify-validation.json`-style
  "heuristic, not a calibrated probability" language warns about, now
  quantified rather than just asserted.
- Isotonic calibration corrected `confidence` to near-textbook calibration
  (ECE 0.007) on data it was not fit on. `confidence_evidence_based`
  improved substantially (0.251 -> 0.100) but remains the less reliable of
  the two scores -- consistent with it being a cruder, single power-CV shape
  statistic rather than `confidence`'s multi-signal (threshold-excess +
  occupancy) heuristic.
- Reliability diagrams (SVG, dependency-free) and full per-bin data are
  committed under `docs/calibration-*.svg` / `docs/confidence-calibration.json`.

**Could not fully meet / explicitly out of scope:**
- **Real-file calibration was not attempted in this pass**, per the
  instruction that it is not achievable here: no ground-truth-labeled real
  corpus exists in this project (Phase 4's real files have no verified
  per-candidate ground truth beyond a coarse expected modulation). The
  calibrators shipped are therefore synthetic-validated, not
  real-world-validated; `confidence_calibration_status`'s wording says
  "synthetic corpus" explicitly on every candidate rather than implying more.
- `confidence_evidence_based`'s calibrated ECE (0.100) is decent but not as
  strong as `confidence`'s; a single scalar shape statistic has less
  information to calibrate against than a multi-feature heuristic does, and
  improving it further (e.g. adding more shape features) is out of scope for
  this pass.
- The two scores are calibrated independently and remain published
  independently (per the existing "deliberately NOT collapsed into
  `confidence`" comment in detect.py) -- this pass did not attempt to
  combine them into one joint-calibrated score.

Reproduce: `cd backend && python3 -m pipeline.calibrate && python3 -m pytest tests/test_calibration.py -v`

## Phase 4 -- Real-file coverage

**Sourced:** 7 new real captures were added to `backend/data/real/`, on top of
the 3 already there (`sigid3_full`/`sigid3_trimmed`, `grcon23_qam`), for 10
total. All were fetched directly (not synthesized) with the user's explicit
go-ahead to source them.

- **GRCon23 CTF** (`sigid` challenge track, author Clayton Smith, same series
  the project's existing `sigid3`/`qam` files came from), via
  `github.com/argilo/grcon23`: `sigid1` (16,777,216 bytes, `cf32_le`, 240 kHz,
  RF 146.55 MHz -- metadata read directly from the file's own `.sigmf-meta`,
  not assumed) and `sigid2` (46,137,344 bytes, same rate/frequency). Both
  exceed this project's synchronous-path 2,000,000-sample cap, so a
  1,900,000-sample `*_trimmed` slice of each (matching the existing
  `sigid3_trimmed` precedent) is what `triage_real.py` actually runs; the
  full files are also kept on disk.
- **rtl_433_tests** (`github.com/merbanan/rtl_433_tests`), a public regression
  corpus of real, off-air ISM-band device recordings, a genuinely different
  source/maintainer than GRCon: `pt2262_remote_1`/`_2` (from
  `tests/PT2262/01/gfile00{1,2}.cu8`, a PIR/remote using the classic PT2262
  encoder) and `ford_tpms_1`/`_2`/`_3` (from `tests/Ford_TPMS/gfile0{59,82,
  124}.cu8`, a Ford tire-pressure sensor). Ground truth for both device
  families comes directly from rtl_433's own decoder source, not a guess:
  `src/devices/generic_remote.c` declares `.modulation = OOK_PULSE_PWM` (the
  PT2262-compatible decoder that matched these recordings' `model:
  "Generic-Remote"` JSON output) and `src/devices/tpms_ford.c` declares
  `.modulation = FSK_PULSE_PCM`, matching `tests/Ford_TPMS/README.txt`'s own
  "FSK 8 byte Manchester encoded TPMS" description word for word. Each
  device's rtl_433 JSON decode output is kept alongside its SigMF pair as
  `*.rtl433-ground-truth.json`.
- These five files were raw `cu8` (RTL-SDR native unsigned-8-bit interleaved
  I/Q), converted to `cf32_le` SigMF via `(byte-127.5)/127.5` per sample (see
  git history for the one-off conversion). **Their sample rate (250 kHz) and
  RF center frequency (433.92 MHz for the PT2262 files, 315 MHz for the Ford
  TPMS files) are *assumed*, not read from the source**: `rtl_433_tests`
  encodes non-default acquisition settings in the filename (e.g.
  `g014_868.33M_250k.cu8`), and these particular files were never renamed
  that way, meaning they were captured at rtl_433's tool default (250 kHz)
  and the device's commonly-documented ISM band. This is flagged explicitly
  here and in each file's own `.sigmf-meta` description, because it plausibly
  explains some of the "could not fully meet" findings below.

**Sources found: 2, not >=3.** GRCon (via argilo) and rtl_433_tests are
genuinely different maintainers/origins, but a third distinct source (the
"other CTFs" category) was not found within reasonable search effort --
several CTF platforms and archives were checked (`ctf-2023.gnuradio.org`
itself, `capturethesignal/cts-tools`, `psbhlw/ctfs`, MIT's RF Challenge
datasets); none offered a statically downloadable, real (not simulated),
digitally-modulated IQ file without either requiring competition-account
authentication (explicitly a prohibited action for this session) or leaving
the real-vs-simulated origin of the data unstated. This is reported here
per instruction, rather than padding the source count with something
that doesn't actually hold up.

**Modulation coverage.** Per file, what ran and what the pipeline returned
(full per-candidate detail in `backend/triage-report.json`, regenerate via
`cd backend && python3 -m triage_real` from the project's `.venv`):

| File | Source | Ground truth | Candidates | Tool output | Matched truth? |
|---|---|---|---|---|---|
| `sigid3_trimmed` / `sigid3_full` | GRCon (argilo, prior pass) | Unconfirmed (signal-ID puzzle); independently evidenced as 2-level FSK (paging-band tones, see `docs/REAL_DATA_TRIAGE.md`) | 2 | Candidate 0: `fine_modulation_label=fsk`, confidence 1.0. Candidate 1: declined. | Consistent with the prior pass's own physical-evidence conclusion (not an external answer key) |
| `grcon23_qam` | GRCon (argilo/CTF site, prior pass) | "Broken modulator" (QAM-family, degraded) | 1 | `varying-envelope`; fine classification **declined** ("envelope levels not well separated") | Correctly declined on a genuinely hard, degraded real signal -- no false label |
| `sigid1_trimmed` | GRCon (argilo) | Unconfirmed (signal-ID puzzle, part of the mystery) | 2 | One candidate at 146.58 MHz: `varying-envelope`, `fine_modulation_label=qam` (low-confidence, order-unresolved, per the existing best-effort path) | Cannot be checked -- no external ground truth exists for this file |
| `sigid2_trimmed` | GRCon (argilo) | Unconfirmed | 2 | One candidate at 146.56 MHz, SNR 36.6 dB: `varying-envelope`, `fine_modulation_label=qam`. A second, very low-SNR (-2.9 dB) candidate: declined. | Cannot be checked -- no external ground truth exists |
| `pt2262_remote_1` | rtl_433_tests | OOK/ASK (`generic_remote.c`, `OOK_PULSE_PWM`) | 8 | 6/8 candidates correctly flagged `is_pulsed=True` and **declined** fine classification ("pulsed bursts not validated"); 1 non-pulsed sidelobe got `fine_modulation_label=qam` (low confidence) | **No candidate was labeled `ask`.** The genuinely gated/bursty OOK carrier was correctly recognized as pulsed and declined rather than mislabeled -- but that also means "OOK" is never positively confirmed here, only not-wrongly-labeled |
| `pt2262_remote_2` | rtl_433_tests | OOK/ASK | 7 | All 7 candidates either declined or (3 of them) got a low-confidence `qam` label on non-pulsed sidelobes | Same pattern; no `ask` label, no wrong PSK/FSK label either |
| `ford_tpms_1` | rtl_433_tests | FSK (`tpms_ford.c`, `FSK_PULSE_PCM`; README confirms in plain text) | 22 | Most candidates `is_pulsed=True`, declined. Two non-pulsed candidates got labels: `ask` (SNR 19.6 dB, symbol_rate 4125 Hz) and `bpsk` (SNR 5.9 dB, symbol_rate ~7.6 Hz) | **Mismatch.** Neither label is `fsk`. These are very plausibly spurious continuous sidelobes/harmonics near the true burst, not the TPMS transmission itself -- a genuine, reportable finding, not swept under the rug |
| `ford_tpms_2` | rtl_433_tests | FSK | 19 | One non-pulsed candidate: `bpsk` (SNR 4.5 dB, symbol rate ungated -- below the 5 dB gate) | **Mismatch**, same pattern as `ford_tpms_1` |
| `ford_tpms_3` | rtl_433_tests | FSK | 17 | Non-pulsed candidates: `ask` (SNR 15.8 dB), `bpsk` (SNR 1.9 dB), `qam` (SNR 15.1 dB, low confidence) | **Mismatch**, same pattern |

**Passed:**
- 10 real files from 2 independent, named, reproducible sources are now in
  the repo and covered by `triage_real.py`, each with a documented source,
  ground truth (where any exists), and command to reproduce
  (`cd backend && python3 -m triage_real`, or `pytest tests/test_triage_real.py`
  for the existing regression checks on the first 3 files).
- The pipeline's pulsed-exclusion logic (from `classify.py`, unmodified by
  this pass) behaved exactly as designed on genuinely gated real OOK/FSK
  ISM-band bursts: the large majority of candidates across all 5 new
  rtl_433 files were correctly flagged `is_pulsed=True` and correctly
  declined fine classification, rather than guessing a label for a signal
  type (single unmodulated-carrier-per-burst framing) this project has
  never validated fine classification against.
- `grcon23_qam`'s prior-pass correct decline reproduced identically.

**Could not fully meet / explicit failures (including on purpose, per
instruction):**
- **Only 2 sources, not >=3** -- reported above with what was actually tried.
- **No real capture positively confirms `ask`, `8psk`, or `qam`'s order**
  against independent ground truth in this pass. `sigid1`/`sigid2`'s true
  modulation is itself an unsolved puzzle (no answer key was available
  without competing in the archived CTF, which was not attempted here);
  their `qam` labels are the pipeline's own best-effort output, not a
  verified match. **8PSK remains completely untested on real data** -- no
  source found in this pass offered a real, labeled 8PSK capture; ISM-band
  device datasets like rtl_433 essentially never use 8PSK (it doesn't suit
  simple, cheap sensor hardware), and GRCon's publicly downloadable
  `sigid`-track files carry no external answer key. This is the same 8PSK
  gap flagged (for timing recovery specifically) at the end of Phase 1.
- **A real, reportable failure mode was found, not hidden:** on 3 of the 5
  rtl_433 files (`ford_tpms_1`/`_2`/`_3`), a handful of non-pulsed candidates
  received a `bpsk` or `ask` fine label that does not match the files'
  documented FSK ground truth. The most likely explanation, based on what
  is visible in `triage-report.json`, is that these are spurious continuous
  sidelobes or harmonics near the genuinely pulsed FSK burst (which itself
  was correctly declined), not the TPMS signal being mislabeled directly --
  but this project has no way to confirm that explanation without ground
  truth for each individual candidate's frequency band, so it is reported
  as an open, unresolved false-label risk on real data, not explained away.
  This is a more concrete, real-data version of the same caution
  `docs/REAL_DATA_TRIAGE.md` already raised in the abstract.
- **The assumed sample rate/frequency for the 5 rtl_433 files were not
  independently verified** against the actual capture (see "Sourced"
  above); if either assumption is wrong, every frequency-domain number
  reported for those 5 files (baseband offsets, RF center, bandwidth) is
  proportionally wrong, though the qualitative pulsed/non-pulsed and
  family/fine-label findings would likely still hold since those are
  relative, not absolute-frequency-dependent measurements.

Reproduce: `cd backend && python3 -m triage_real` (writes `backend/triage-report.json`);
individual file provenance is in each `.sigmf-meta`'s `core:description` and,
for the rtl_433 files, the paired `*.rtl433-ground-truth.json`.

## Phase 5 -- Technical debt from prior review

**1. 2M-sample cap re-expressed as a duration limit.** `backend/pipeline/large_capture.py`'s
`DiskSamples.MAX_READ_SAMPLES` (a flat 2,000,000-sample constant regardless
of sample rate) is now `max_read_samples(sample_rate)`: `min(MAX_READ_SECONDS
* sample_rate, MAX_READ_SAMPLES_CEILING)` with `MAX_READ_SECONDS = 60.0` and
`MAX_READ_SAMPLES_CEILING = 2_000_000` (the old constant, now a ceiling, not
the only limit). Rationale: the old flat cap meant a bounded read covered
~4 s at 480 kHz but only ~0.1 s at 20 MHz -- the same memory cost (16 MiB)
bought wildly inconsistent amounts of real time depending on sample rate.
60 s was chosen to preserve existing behavior at this project's own
synthetic fixtures' typical 48 kHz rate (60*48,000 = 2,880,000, so the
2,000,000-sample ceiling still binds there, exactly matching the prior flat
cap) while giving a *smaller* budget at very low sample rates (which
previously could read up to 2,000,000 samples = tens of minutes) and the
same tight ceiling at very high SDR sample rates. `DiskSamples`,
`open_disk_capture`, and `enrich_track` all now take/derive the sample rate
from the capture itself, not a hardcoded class attribute -- confirmed by
`test_max_read_samples_is_duration_consistent_across_sample_rates`.

**2. int32 overflow audit: no bug found, but now documented and guarded.**
Every sample-index field in the pipeline (`start_sample`, `end_sample`,
`sample_start`, pulse-window bounds, `DiskSamples`'s byte-offset arithmetic)
is either a plain Python `int` (arbitrary precision -- Python ints do not
overflow) or a numpy `intp`/int64 value (from `np.flatnonzero`, always
64-bit on any 64-bit platform, max ~9.2x10^18 -- far beyond any realistic
file size). The `dtype=int` occurrences that do exist in this codebase
(`large_capture.py`'s display-row binning, `api/main.py`'s spectrogram pixel
grid, `layers.py`'s waveform-point downsampling) map to numpy's `int_` (C
`long`, 32-bit on Windows) but are exclusively small, UI-resolution-bounded
indices (at most `DISPLAY_ROWS`=768 or a requested pixel width/height in the
low thousands) -- never a raw sample offset -- so they carry no overflow
risk on any platform regardless of file size. No code change was needed;
the finding is documented inline at the one arguably-least-obvious site
(large_capture.py's `bins` computation) so a future reader does not have to
re-derive this from scratch.

**3 & 4. Boundary-straddle and fading fixtures**, both new tests in
`backend/tests/test_large_capture.py`:
- `test_continuous_signal_straddling_block_boundary_merges_to_one_track`: a
  continuous BPSK band spanning ~8.8 blocks (32,768-sample blocks) merges
  into exactly one track end-to-end, with correctly re-measured
  `bandwidth_3db_hz` and `symbol_rate_hz` (within 10% of the generator's
  truth) on the merged, re-enriched span -- confirms the merger and the
  per-track bounded re-read (Phase 1-era `enrich_track`) compose correctly
  across a boundary, not just within one block.
- `test_fading_signal_keeps_one_track_across_a_15db_drop`: a signal built by
  splicing a 20 dB-SNR first half to a 5 dB-SNR (15 dB lower) second half
  (regenerated at the target SNR, not scaled post-hoc, so the noise floor
  stays physically consistent) still merges into one track spanning the
  full file, with measurably reduced confidence relative to an unfaded
  control at the same final SNR -- the fade shows up as degraded confidence
  on the merged track, not as two separate tracks or a lost second half.

**5. Progress reporting and a cancellation hook for the async path.**
Progress reporting for the block-scan phase already existed; what was
missing was progress *during* the per-track enrichment phase that runs
after the scan reaches 100% (previously silent, which could look stalled on
a capture with many candidate tracks). `analyze_disk_capture` now calls
`progress(n, n, "Enriching candidate tracks with Estimate/Classify: i/N")`
per track. A new `cancel_check` parameter (a zero-arg callable returning
bool) is polled once per block during the scan and once per track during
enrichment; a `True` result raises `AnalysisCancelled` (a new exception,
distinct from a genuine analysis failure). `backend/api/main.py` wires this
to a per-job `threading.Event`: `POST /api/jobs/{job_id}/cancel` sets it,
and `process_large_job` catches `AnalysisCancelled` separately from other
exceptions to report `status: "cancelled"` (not `"failed"`) with a message
describing how far analysis got. Cancelling an already-finished job, an
unknown job, or a job that completed synchronously (no background analysis
to cancel) are all explicit, tested cases (409/404/no-op), not silent
failures. Tests: 3 pipeline-level tests (deterministic, no timing race --
`cancel_check` is a plain callable, not a real clock) plus 3 API-level tests
(one real timing race between cancel and completion, asserting the job
never reports `"failed"` regardless of which side wins).

**6. Metadata inheritance assertion.** `enrich_track`'s local, per-track
`Capture` was already constructed with `capture.sample_rate` and
`capture.metadata` passed through directly (the same object, not a copy),
so inheritance was already correct by construction -- but nothing asserted
it, so a future refactor could silently break it (e.g. constructing the
local `Capture` with a default/hardcoded sample rate). `test_enrich_track_
local_capture_inherits_sample_rate_and_center_frequency` now opens a disk
capture with an explicit SigMF `core:frequency` tuning offset (915 MHz) and
confirms the enriched track's `center_frequency_hz` reflects offset+baseband
(not baseband alone), which would only be true if the local re-read
genuinely inherited both `sample_rate` and the tuning-offset metadata from
its parent capture.

All 6 items are covered by tests; the full suite (`cd backend && python3 -m
pytest tests -q`) passed 223 tests, 3 skipped (the same Phase 1 real-capture
skips already explained above), after this phase's changes.

Reproduce: `cd backend && python3 -m pytest tests/test_large_capture.py tests/test_api.py -v -k "cancel or straddl or fading or duration_consistent or inherits or enrichment_phase"`
