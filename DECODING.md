# Decoding

This document tracks the phased addition of symbol/bit decoding on top of
the existing Detect → Estimate → Classify pipeline. Every phase below has
an explicit, stated acceptance criterion. **No phase is marked complete
unless its criterion was actually measured to pass**, and no phase is
attempted past the point where its own criterion fails — a failed or
partially-met criterion is recorded honestly here, with the measured
numbers, rather than worked around.

Everything on this page describes **new, additive capability**. It does
not retract or weaken the project's existing "no decoding" claims in
`README.md`, `docs/PROJECT_STATUS.md`, `docs/JUDGE_DEFENSE_GUIDE.md`,
`docs/GLOSSARY.md`, `docs/SIGNAL_BREAKDOWN.md`, or the frontend copy —
those documents have not yet been updated to reflect Phase 1 (that update
is explicitly scoped as Phase 3 below, not done in this pass) and should
be read as describing the pre-decoding state of the project until they are.

## Why "decoding" needs a scope boundary before any code

This pipeline has no absolute carrier-phase reference and no frame
synchronization:

- `backend/pipeline/timing_recovery.py`'s Gardner recovery locks **symbol
  timing** (where the symbol centers are), not carrier phase.
- `backend/pipeline/classify.py`'s `refine_frequency` removes carrier
  **frequency** offset via an Mth-power peak search, which by construction
  leaves an M-fold **phase** ambiguity (rotating the whole constellation
  by any multiple of `2*pi/M` fits the same Mth-power peak equally well).
- Matched filtering and frame/preamble synchronization are both
  deliberately out of scope elsewhere in this project
  (`docs/LIMITATIONS_AND_ROADMAP.md`), so there is no mechanism to lock
  onto a known reference sequence and resolve that ambiguity, or to know
  which recovered symbol corresponds to the transmitter's first symbol.

Consequence: any symbol/bit stream this pipeline recovers from a single,
previously-unseen capture is only ever meaningful **relative to itself**
— correct up to an unknown constant rotation (mod the constellation order)
and an unknown start offset. It is never an absolute decoded message. Every
phase below states this plainly in its own output (`decode_status`,
`decode_rotation_ambiguity_modulus`) rather than implying otherwise.

## Phase 1 — Symbol recovery for confirmed M-PSK candidates

**Status: complete, acceptance criterion met, on synthetic fixtures.**

**Scope.** `backend/pipeline/decode.py`. For a candidate that already has a
confirmed `bpsk`/`qpsk`/`8psk` fine label (`classify.py`) and a locked
Gardner symbol-timing recovery (`timing_recovery.py`), estimate the
residual constant carrier-phase offset with a blind Mth-power estimate
(`estimate_phase_offset`) and map each recovered symbol to the nearest
ideal constellation point, producing an integer symbol-index stream
(`demap_psk_symbols`, orchestrated end-to-end by `decode_candidate`).
`ask`, `fsk`, and `qam` are explicitly out of scope for Phase 1 — see
"Not attempted" below.

**Acceptance criterion, stated before implementation.** Symbol error rate
(SER), measured after a best-fit global rotation/start-offset alignment
against known truth symbols (a validation-only step — the production code
in `decode.py` never sees truth symbols and does not resolve this
alignment itself), must be ≤2% averaged over 10 seeds at each
modulation's gated SNR.

**Method.** Own synthetic fixtures in `backend/tests/test_decode.py`
(`make_psk_fixture`): TX-side root-raised-cosine pulse shaping, **no RX
matched filter** — this deliberately mirrors `classify.corrected_segment`,
the real production path, which also applies no RX matched filtering
(the real pulse shape isn't known a priori for an arbitrary captured
signal). This is a stricter, more representative fixture than
`qam_order.py`'s own tests use (which do apply an RX matched filter, a
documented gap there — see that module's tests). `synth_gen.py`, the
project's main synthetic-capture generator, was **not** modified or used
here: it records no per-symbol ground truth (only aggregate metadata like
SNR and frequency bounds), so it cannot support an SER measurement. Adding
that would be its own scoped change; Phase 1 used an independent
truth-tracking fixture instead, matching the precedent already set by
`test_timing_recovery.py`'s and `test_qam_order.py`'s own independent
fixtures.

**Measured results** (mean SER over 10 seeds, `decode.DECODE_MIN_TAIL_SYMBOLS`
= 2000 symbols per trial, sample fixture: `n_symbols=40000`, `sps=8`,
`beta=0.35` RRC, random fractional timing delay in ±0.15 symbols per seed):

| Modulation | SNR (dB) | Mean SER | Locked (of 10) |
|---|---|---|---|
| bpsk | 0 | 3.56% | 5 |
| bpsk | 2 | 1.36% | 7 |
| bpsk | 3 | 0.70% | 9 |
| bpsk | 8 | 0.00% | 9 |
| bpsk | **10 (gate)** | **0.00%** | **10** |
| bpsk | 20 | 0.00% | 10 |
| qpsk | 4 | 4.94% | 9 |
| qpsk | 6 | 1.66% | 10 |
| qpsk | 8 | 0.39% | 10 |
| qpsk | **10 (gate)** | **0.07%** | **10** |
| qpsk | 20 | 0.00% | 10 |
| 8psk | 10 | 5.64% | 10 |
| 8psk | 12 | 2.44% | 10 |
| 8psk | 13 | 1.50% | 10 |
| 8psk | **15 (gate)** | **0.49%** | **10** |
| 8psk | 20 | 0.01% | 10 |

**Why the gates are set where they are, not just "SER ≤ 2%".** SER alone
clears 2% well below 10 dB for bpsk/qpsk (bpsk at ~2 dB, qpsk at ~6 dB).
But `gardner_timing_recovery` is itself only validated to lock reliably at
SNR ≥10 dB (its own module docstring's stated acceptance range); measured
directly here, bpsk's lock reliability specifically drops to 9/10 seeds
below 10 dB even though the symbols that *do* lock decode almost
perfectly. Gating decode at 10 dB for bpsk/qpsk uses the already-validated
timing-recovery floor rather than a looser, SER-only floor that would rest
on lock behavior nobody has validated. 8psk's much tighter decision
boundaries (π/8 apart vs. π/2 for bpsk or π/4 for qpsk) push its own SER
cliff to ~13 dB, so its gate is 15 dB, mirroring `qam_order.py`'s existing
15 dB gate.

**Tests:** `backend/tests/test_decode.py` — 7 tests, all passing:
per-modulation SER-at-gate (3), the below-gate-SER-exceeds-2%
counter-evidence (3, documents the gate isn't arbitrary), and one
structural end-to-end gating/status test for `decode_candidate`.

**Not attempted in Phase 1 (explicitly, not silently):**
- **ask**: different demapper (amplitude-level clustering, already
  computed for classification in `classify.classify_fine_ask`'s
  `_cluster_levels`), not built or validated here.
- **fsk, qam**: `SYMBOL_RATE_LABELS` in `classify.py` already excludes fsk
  from symbol-rate estimation (~99% measured error on the delay-and-multiply
  nonlinearity), and qam has no confirmed order path feeding a symbol
  demapper the way `qam_order.py` currently works. Both need their own
  scoped design, not a copy-paste of the PSK demapper.
- **Real captures**: Phase 1 is validated only on synthetic fixtures, same
  caveat as every other downstream stage in this project
  (`docs/PROJECT_STATUS.md`'s existing posture). No real IQ capture with
  known transmitted bits has been run through `decode.py`.
- **Bit-level output / Gray coding**: Phase 1 stops at integer symbol
  indices. Mapping those to bits is Phase 2.
- **API/frontend/doc integration**: `decode_candidate` is not wired into
  `classify.analyze_candidate` or any API response yet, and the project's
  existing "no decoding" documentation has not been updated. Both are
  Phase 3, tracked below, not done in this pass.

## Phase 2 — Bit-level output (not started)

**Planned scope.** Gray-code bit mapping from Phase 1's symbol indices,
published with the same explicit ambiguity fields Phase 1 already carries
(rotation mod order, unknown start offset) rather than resolving them.

**Planned acceptance criterion.** Bit error rate consistent with Phase 1's
measured SER under a Gray-code mapping (adjacent-symbol errors should
flip close to one bit per symbol error at the SNRs Phase 1 validated).

**Status.** Not started. No code exists for this phase yet.

## Phase 3 — Wire into API/pipeline/docs (not started)

**Planned scope.** Add `decode_candidate`'s output fields to
`classify.analyze_candidate`, expose them through the relevant API
response and JSON/SigMF export, and update every place in this repo that
currently states "no decoding" (`README.md`, `docs/PROJECT_STATUS.md`,
`docs/JUDGE_DEFENSE_GUIDE.md`, `docs/GLOSSARY.md`,
`docs/SIGNAL_BREAKDOWN.md`, `docs/BACKEND_PIPELINE.md`,
`docs/API_REFERENCE.md`, `docs/FRONTEND_DASHBOARD.md`,
`backend/api/main.py`'s FastAPI description, `frontend/src/App.tsx`,
`frontend/src/components/Breakdown.tsx`,
`frontend/src/bolt/SignalBreakdown.tsx`) to describe exactly what Phase 1
validated (symbol recovery up to rotation/offset ambiguity, gated SNR,
synthetic-only) and what remains unvalidated or unbuilt, the same way
this project already qualifies every other capability.

**Planned acceptance criterion.** Full existing backend test suite still
passes with the new fields added (no downstream field silently changes
shape); every touched doc's decoding-related claim matches what Phase 1/2
actually measured, with no broader claim than the evidence supports.

**Status.** Not started. No code or doc changes for this phase exist yet.

## Phase 4 — QAM symbol decode / analog AM-FM demod to audio (not started, stretch)

Only after Phases 1–3 are solid. QAM decode needs its own demapper (the
constellation isn't a simple phase ring); analog AM/FM-to-audio was
originally sketched as `docs/master context.md`'s "Stage 6 (optional, zero
allocated hours)" and never built. Both are separate, independently
gated efforts — not started, no acceptance criterion measured yet.

---

# SIH26147 decode track (D0–D4)

A separate, later effort layered on top of Phase 1 above: a stage-gated
DECODE chain (demodulate → frame/sync → de-interleave → FEC-decode →
verify) that publishes a decode **only when an algebraic check passes**
(FEC syndrome, CRC, or bit-exact match to a public reference decode), aimed
first at real AIS and rtl_433 recordings, not only synthetic signals. Full
design: `docs/DECODE_DESIGN.md`. This section records D1's measured
acceptance evidence, the same way Phase 1 above does for PSK.

## D1 — 2-FSK/GMSK (discriminator) and OOK/ASK2 bit decoding

**Status: complete, acceptance criteria met, on synthetic fixtures.**

**Scope.** `backend/pipeline/decode.py`'s `demap_fsk_bits` (binary
CPFSK/GMSK, non-coherent discriminator) and `demap_ask_bits` (unipolar
2-level ASK/OOK, envelope), each built on a new shared timing primitive,
`oerder_meyer_symbol_epoch`, and wired into `decode_candidate` alongside
the existing PSK path via `DECODE_FAMILY_METHOD`. `decode_candidate` now
accepts `fine_modulation_label` values `fsk2`/`ask2` in addition to
`bpsk`/`qpsk`/`8psk`.

### Timing-recovery bake-off (Oerder-Meyer vs Mueller-Mueller)

`backend/pipeline/timing_recovery.py`'s Gardner recovery — already
validated for the existing PSK path — is a decision-directed loop tuned for
long, continuous streams (`DECODE_MIN_TAIL_SYMBOLS` = 2,000 symbols to
converge). AIS/rtl_433 bursts are far shorter, so D0 registered a bake-off
between a non-data-aided feedforward estimator (Oerder & Meyer, 1988) and a
Mueller-Mueller (1976) decision-directed loop, both against the same
short-burst CPFSK fixture with random start delay (independent
implementation in `experiments/decode_bakeoff/timing_bakeoff.py`; not
imported by production code).

Mean bit error rate, 100 seeds per point, 300-bit bursts, h=0.5, sps=8,
random start delay in [0, sps) per seed (so neither method's initial state
gets a lucky exact alignment):

| SNR (dB) | Oerder-Meyer BER | Mueller-Mueller BER |
|---|---|---|
| -2 | 29.78% | 29.90% |
| 0 | 22.04% | 22.44% |
| 3 | 12.37% | 12.49% |
| 6 | 6.12% | 6.55% |
| **10** | **2.05%** | **3.45%** |
| **15** | **0.32%** | **1.38%** |

**Winner: Oerder-Meyer**, at every SNR from 10 dB up (the range these
gates actually target) — a decision-directed loop's early hard decisions
are wrong more often at these SNRs, and that error feeds back into its own
timing estimate, which a block estimate with no feedback cannot do. Its
simplicity (one closed-form DFT-bin computation, no loop-gain parameters to
tune or risk destabilizing on a short burst) was the secondary reason it
was chosen for production; `decode.py` implements only Oerder-Meyer.
Mueller-Mueller's numbers above are kept as the bake-off record, not
deleted, per the task's stated rule.

**A DSP result worth flagging explicitly (uncertain point, validated
before wiring in):** the initial design assumed a signal's own raw
`lock_fraction` (the Oerder-Meyer DFT bin's magnitude as a fraction of the
squared-signal's total AC power) would separate a real signal from noise,
the way `gardner_timing_recovery`'s loop-error std does for PSK. Measured,
it does not: an unshaped CPFSK/OOK signal's squared nonlinearity is
dominated by its DC term (the symbol amplitude itself), and the genuine
periodic component at the symbol rate — which for a *rectangular* pulse
comes only from the discriminator/envelope's transition-edge artifacts, not
from the symbol values themselves (a perfectly rectangular random telegraph
signal, squared, is mathematically flat) — is a small fraction of that,
regardless of SNR (measured 0.01–0.04 at 10–15 dB, vs. pure noise's
0.001–0.013: overlapping, not usable as a gate). What **does** separate
cleanly, measured the same way, is the post-integrate-and-dump decision
`confidence` each demapper already computes and returns (see next
section) — that became the actual false-decode gate, not the raw lock
fraction. `FSK_ASK_MIN_SNR_DB`'s and `FSK_MIN_CONFIDENCE`/
`ASK_MIN_CONFIDENCE`'s docstrings in `decode.py` carry this derivation.

### Acceptance criterion, stated before implementation

Mean bit error rate ≤2% over 10 seeds at each family's gated SNR (same
target and seed count as Phase 1's PSK criterion); false-decode rate must
be 0% on pure noise and on a wrong-hypothesis input (a clean, high-SNR
BPSK segment fed to the FSK/ASK demapper).

### Measured results

Mean BER over 10 seeds, `n_bits=2000` per trial, `sps=8`, random start
delay per seed (`backend/tests/test_decode_fsk_ask.py`):

| Modulation | SNR (dB) | Mean BER | Locked (of 10) |
|---|---|---|---|
| fsk2 | 2 | 8.44% | 5 |
| fsk2 | 4 | 4.32% | 7 |
| fsk2 | 6 | 1.49% | 7 |
| fsk2 | 8 | 1.03% | 9 |
| fsk2 | **10 (gate)** | **0.12%** | **10** |
| fsk2 | 12 | 0.02% | 10 |
| fsk2 | 15 | 0.00% | 10 |
| fsk2 | 20 | 0.00% | 10 |
| ask2 | 0 | 7.74% | 7 |
| ask2 | 2 | 2.74% | 9 |
| ask2 | 4 | 0.69% | 10 |
| ask2 | 6 | 0.13% | 10 |
| **ask2** | **8 (gate)** | **0.01%** | **10** |
| ask2 | 10 | 0.00% | 10 |
| ask2 | 15 | 0.00% | 10 |
| ask2 | 20 | 0.00% | 10 |

"Locked" means `decode_candidate`/the demapper published a bit stream at
all (confidence cleared its family's gate); below the SNR gate, some seeds
correctly decline rather than publish a high-BER guess — consistent with
this project's existing "decline rather than guess" posture.

**Why the gates sit where they do.** fsk2's gate (10 dB) matches the
existing PSK bpsk/qpsk gate — both are set by their own measured BER cliff
here (2% cleared by 6-8 dB, gated 2 dB higher for full 10/10 lock
reliability), not copied from the PSK number. ask2's gate (8 dB) sits
lower, matching ASK's generally easier detection problem (envelope-only,
no discriminator noise-enhancement) already reflected in this project's
existing `SYMBOL_RATE_MIN_SNR_DB = 4.5` dB for ASK/PSK symbol-rate
estimation in `classify.py`, though this gate is set independently from a
direct BER measurement, not inherited from that number.

**False-decode rate (measured, not by construction):**

| Test | Trials | False decodes |
|---|---|---|
| Pure complex AWGN → `demap_fsk_bits` | 500 | 0 |
| Pure complex AWGN → `demap_ask_bits` | 500 | 0 |
| Clean BPSK (5–30 dB) → `demap_fsk_bits` | 250 | 0 |
| Clean BPSK (5–30 dB) → `demap_ask_bits` | 250 | 0 |

0/1,500 across both false-decode categories and both families, meeting the
task's 0% requirement. `FSK_MIN_CONFIDENCE = 0.46` and
`ASK_MIN_CONFIDENCE = 0.55` were chosen with margin above the measured
worst-case noise confidence (0.434 over 1,000 seeds for FSK, 0.453 over 500
for ASK) and below the measured signal-confidence floor at each family's
SNR gate (fsk2 ≥0.50 at 10 dB across 50 seeds sampled; ask2 ≥0.79 at 8 dB
across 10 seeds) — not tuned against the test seeds used to report the BER
table above (a disjoint, larger seed range: 20,000+ and 30,000+ bases vs.
the BER table's 0–9).

### Tests

`backend/tests/test_decode_fsk_ask.py` — 12 tests, all passing: the shared
`oerder_meyer_symbol_epoch` primitive against an independent grid-search
reference (2), per-family at-gate and below-gate BER (4), per-family
false-decode-on-noise (2), FSK false-decode-on-wrong-hypothesis (1), and
`decode_candidate` end-to-end dispatch/gating for both families (3). Full
existing suite (`backend/tests`, excluding two files requiring an
unavailable `fastapi` install in this environment) still passes: 352
passed, 3 skipped, no regressions.

### Not attempted in D1 (explicitly, not silently)

- **GMSK pulse shaping (BT=0.4):** this sweep uses unshaped (rectangular)
  CPFSK. AIS's real BT=0.4 Gaussian shaping is D2's problem, validated
  there directly against the real AIS recordings rather than a synthetic
  proxy.
- **4-FSK/8-FSK, higher-order ASK:** `demap_fsk_bits`/`demap_ask_bits` are
  binary only; `FSK_ASK_MIN_SNR_DB` has no `fsk4`/`fsk8` entry, matching
  `classify.py`'s existing `SYMBOL_RATE_LABELS` exclusion of FSK generally
  from rate estimation, now narrowed specifically to "binary only" for
  decode.
- **G4 impairment sweep:** this section's fixtures are clean AWGN only (own
  independent generator, like Phase 1's PSK fixture, not
  `experiments/readiness/impaired.py`, which tracks no per-bit truth). A
  G4-style impaired bit-level sweep (carrier drift, phase noise, IQ
  imbalance) is unstarted; flagged here rather than silently assumed by the
  clean-AWGN numbers above.
- **Real captures:** D1 is synthetic only. D2 is the real-recording proof.
