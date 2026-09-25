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
