# Decode track design (D0)

SIH26147: a stage-gated DECODE track on top of the existing Detect → Estimate →
Classify pipeline, plus `backend/pipeline/decode.py`'s Phase 1 PSK symbol
recovery. This document is design and scope only — **no product code changes
in this pass**. It is written against `origin/main` at `f0e6a15`.

## 0. What already exists, and where this track picks up

Read against the code, not assumed from `DECODING.md`'s prose, because the
project's own convention (`DECODING.md`'s own opening line) is that the code
is truth:

- **Detect** (`backend/pipeline/detect.py`) gives time/frequency bounds per
  candidate. WP3 (`docs/reports/WP3.md`) measured these bounds are frequently
  wrong on real FSK signals (narrower than half, or wider than double, the
  true tone split on 25/28 FSK2 files) and that 60% of real-file primaries are
  refused outright as pulsed. **This track does not touch Detect.** Where a
  decode needs a better burst boundary than Detect currently hands it (AIS
  bursts, rtl_433 OOK/FSK packets), it re-derives that boundary itself from
  the recovered bit/frame stream (HDLC flags, OOK pulse edges) inside
  `decode.py`'s own code path, and never edits `detect.py` or the pulsed-burst
  handling in `verify_estimator.py`. If a real Detect bound is unusably wrong
  for a specific G3/G5 file, that is reported as a blocking question, not
  patched here.
- **Estimate/Classify** (`classify.py`) gives a coarse envelope family, a fine
  PSK/ASK/FSK/QAM label, and (gated ≥4.5 dB SNR, PSK/ASK only) a symbol rate.
  FSK is explicitly excluded from symbol-rate estimation (`SYMBOL_RATE_LABELS`
  in `classify.py`; ~99% measured error on the delay-and-multiply
  nonlinearity) — this track's GMSK/FSK bit recovery therefore needs its own
  rate/timing path, not a reuse of `classify.py`'s PSK-only symbol rate.
- **`verify_estimator.py`** is a second, independent estimator: a propose
  (`backend/experimental/estimate_spike`) → verify (margin-gated) MDL
  labeller with its own thresholds (`docs/verify-thresholds.json`) and its
  own real-file criteria (`experiments/readiness/config.py`'s `real_*`,
  scored on `g5_manifest.json`). It currently **excludes pulsed candidates**
  (`"not reliably estimated (pulsed bursts not validated)"`) — which is most
  of AIS and all of rtl_433's OOK/FSK packets. WP3's oracle experiment (run
  on each candidate's longest burst, bypassing the pulsed refusal) is exactly
  the situation this decode track's D2 targets: it showed GMSK/AIS gets `FM`
  with 0.00 unexplained power (the FSK h=0.5 expert does not explain GMSK),
  and ASK2/OOK gets 8/14 correct with 0 wrong when Detect's band and the
  file's real symbol rate are both known.
- **`decode.py`** (Phase 1, complete, synthetic-only) does blind Mth-power
  phase alignment + nearest-point demapping for a confirmed
  `bpsk`/`qpsk`/`8psk` label from `classify.py`, gated at 10/10/15 dB SNR.
  It produces an **integer symbol-index stream that is only self-consistent**
  — correct up to an unknown rotation (mod the constellation order) and an
  unknown start offset — because nothing upstream provides an absolute phase
  or frame-start reference (`docs/LIMITATIONS_AND_ROADMAP.md`: matched
  filtering and frame/preamble sync are "deliberately out of Phase 1").
  Phase 2 (bit mapping) and Phase 3 (wiring/docs) in `DECODING.md` are **not
  started**. This decode track is those phases, generalized and reframed
  around an algebraic verifier instead of a bare SER/BER target, plus a new
  D2/D3 scope (real protocols, catalogue FEC) that `DECODING.md` never
  planned.

**Relationship to `decode.py`'s ambiguity problem.** Phase 1's rotation/offset
ambiguity is a structural fact about a single capture with no known preamble
— it does not go away for PSK. What changes in this track is that some
*families* carry their own resolvable reference inside the payload itself:
AIS's HDLC flag (`0x7E`) is an absolute bit-position anchor, and NRZI/HDLC
bit-stuffing plus a CRC-16 are strong enough that a wrong rotation/offset
overwhelmingly fails the CRC rather than silently producing a plausible
wrong message (this is the algebraic argument for why decode.py's ambiguity
is a design constraint, and why the verifier below, not a heuristic
confidence score, is what makes publishing safe). Bare PSK **without** a
framed protocol on top (Phase 1's exact scope) still cannot resolve absolute
rotation, and this track does not claim otherwise — see §6.

## 1. The chain

```
IQ segment (Detect bounds, corrected_segment)
        |
   [Stage A] Demodulate to soft/hard bits
        |         (per-family: PSK phase+symbol demap [existing decode.py],
        |          GMSK/FSK discriminator or matched filter, OOK/ASK2 threshold)
        v
   [Stage B] Frame / sync search
        |         (family-specific: AIS = NRZI-decode + HDLC 0x7E flag search;
        |          rtl_433 = pulse-width/edge framing per protocol;
        |          catalogue codes = block/codeword boundary from D3's
        |          rank-deficiency length estimate)
        v
   [Stage C] De-interleave
        |         (block or convolutional de-interleaver, catalogue-bounded,
        |          identity/no-op for protocols with none, e.g. AIS)
        v
   [Stage D] FEC-decode
        |         (per catalogue entry: AIS = de-stuffing only, no ECC beyond
        |          CRC-16 detection; CCSDS conv. K=7 r=1/2 = Viterbi;
        |          RS(255,223) = Berlekamp-Massey/Euclid + Chien search)
        v
   [Stage E] Verify (algebraic)
        |         (FEC syndrome == 0, AND/OR CRC pass, AND/OR re-encode match
        |          — see §2 for which check(s) apply per family)
        v
   decode_status: "decoded" (verified) | "not decoded" (+ reason)
```

Every arrow can fail closed. A candidate that fails at Stage A produces
`decode_status: "not attempted (<Stage A reason>)"`; a candidate that reaches
Stage E and fails verification produces `decode_status: "not decoded
(<algebraic check> failed)"`, **never** a payload. There is no stage that
publishes on a soft/heuristic score — that is the one hard rule this whole
design exists to enforce, and it is what differentiates this track from
"demodulate the bits and hope the CRC happens to be embedded in what you
already trust to be right."

## 2. Which families decode first, and the verification rule at each stage

Ordered by how directly each maps to a public, citable standard and to
evidence the project already has:

| Order | Family | Stage A method | Stage B/C | Stage D | Stage E verifier | Evidence available |
|---|---|---|---|---|---|---|
| 1 | AIS (GMSK, 9600 bit/s) | GMSK discriminator (freq-domain, non-coherent) or Viterbi/BCJR over the CPM trellis (bake-off, D1) | NRZI decode, HDLC flag (`0x7E`) search + bit de-stuffing | none (AIS has no block/conv. interleaver) | none beyond de-stuffing | **CRC-16/X-25** (ITU-R M.1371-5 Annex 8) over the de-stuffed frame; AND payload length/type matches the standard (§3) | G3 `AIS-...-161M975...`, G5 `iqe_AIS_...-162M025...` — real, public, both already in the readiness manifests |
| 2 | rtl_433 OOK/ASK2 (pulse-width/Manchester coding) | Envelope threshold → pulse-width bins (existing `classify_fine_ask`'s level clustering informs the threshold, reused as *input*, not modified) | Per-device framing from the `rtl_433_tests` sidecar `.json`'s `r_device` spec (short/long width, sync/preamble pattern) | none (OOK devices in this catalogue are uncoded) | none, or device-specific parity/checksum where the device defines one | **Bit-exact match against the `.json` sidecar's decoded fields** (rtl_433's own reference decode) | `rtl_433_tests` captures named in `g5_manifest.json`'s `recordings[].source == "rtl_433_tests"` entries |
| 3 | rtl_433 FSK2 (PCM/Manchester) | 2-FSK discriminator | per-device framing, as above | none | device checksum where defined | same as above | any FSK2-labeled `rtl_433_tests` entries in the manifest |
| 4 | Catalogue FEC/interleaver on confirmed PSK/QAM candidates (D3) | existing `decode.py` PSK demapper (or its D1 GMSK/OOK/ASK2 extensions) | blind block-length estimate (GF(2) rank deficiency, D3) locates codeword boundaries; catalogue interleaver de-permutation only if the rank-deficiency search identifies one | catalogue lookup: CCSDS conv. K=7 r=1/2 (Viterbi) or RS(255,223) (Berlekamp–Massey + Chien) | **FEC syndrome == 0** (convolutional: Viterbi path metric / re-encode-and-compare; RS: syndrome vector == 0) AND, where the catalogue entry also specifies one, CRC pass over the decoded payload | synthetic only — no known real recording in G3/G5 uses these catalogue codes; D3 is explicitly synthetic + impairments, not claimed on real data |

**The verification rule, stated once:** a decode is published only when its
family's designated algebraic check(s) in the table above evaluate to pass,
computed from the recovered bits/frame with **no reference to truth data** —
the same posture `verify_estimator.py` already uses (margins fit on
calibration, never on test files). If the check fails, or cannot be computed
(e.g. no CRC field recoverable because framing itself failed), the output is
`decode_status: "not decoded"` with the specific reason from the stage that
stopped. There is no confidence-scored middle tier for a decode the way
`verify_estimator.py` has an "unknown family" tier for labels — decoding is
binary: verified or not decoded.

## 3. Output schema

Extends, does not replace, `decode.py`'s existing per-candidate dict.
Fields marked **new** are added by this track; fields marked **existing**
are the Phase 1 fields already shipped.

```jsonc
{
  // --- existing (Phase 1, decode.py) ---
  "decoded_symbol_indices": [...] | null,
  "decoded_symbol_count": int | null,
  "decode_phase_offset_rad": float | null,
  "decode_confidence": float | null,
  "decode_rotation_ambiguity_modulus": int | null,
  "decode_status": str,   // Phase 1's free-text status; this track keeps the
                          // field name but standardizes its value set — see below

  // --- new: chain identity ---
  "decode_family": "ais" | "rtl433_ook" | "rtl433_fsk" | "catalogue_fec" | null,
  "decode_stage_reached": "A" | "B" | "C" | "D" | "E" | null,
    // the last stage that ran, regardless of outcome; lets a report distinguish
    // "framing never found a flag" (stage B) from "CRC failed" (stage E)

  // --- new: standardized status (decode_status becomes one of these, plus
  //     a free-text reason string in decode_reason; the two together replace
  //     Phase 1's single free-text field without discarding its information) ---
  "decode_status": "decoded" | "not_decoded" | "not_attempted",
  "decode_reason": str,
    // always populated. Examples: "CRC-16 mismatch after HDLC de-stuffing",
    // "no HDLC flag found in segment", "FEC syndrome nonzero (RS(255,223))",
    // "code not in catalogue", "SNR below validated gate (10.0 dB)"

  // --- new: verification evidence (only populated when decode_status=="decoded") ---
  "verified_by": ["crc16_x25"] | ["fec_syndrome_zero", "reencode_match"] | [...],
    // list, not a single value: a decode can pass more than one independent
    // check (e.g. RS syndrome==0 AND an outer CRC), and every check that
    // actually ran and passed is named so a report never implies a check
    // happened when it did not
  "decode_bits": str | null,           // recovered payload bits, post-FEC, as "0101..."
  "decode_bytes_hex": str | null,      // same, as hex, when byte-aligned
  "decode_frame_count": int | null,    // frames/packets verified in this segment
  "decode_frames": [                   // new: one entry per verified frame/packet
    {
      "offset_samples": int,           // start of this frame within the segment
      "payload_bits": str,
      "payload_hex": str | null,
      "fields": {...} | null,          // family-specific decode, e.g. AIS message
                                        // type + MMSI (decoded per ITU-R M.1371-5,
                                        // never speculative — only fields the
                                        // standard defines for that message type)
      "verified_by": [...]
    }
  ],

  // --- new: ambiguity notes (generalizes decode_rotation_ambiguity_modulus) ---
  "decode_ambiguity_notes": [str, ...],
    // e.g. "symbol rotation ambiguous mod 4 before frame sync; resolved by
    // HDLC flag alignment" for a family whose framing resolves what Phase 1's
    // bare PSK case cannot — see §6. Empty list, not null, when a decode
    // fully resolves ambiguity (the common case once framing succeeds,
    // since a correctly found flag sequence fixes both rotation and offset).

  // --- new: feedback into label/rate (see §4) ---
  "decode_confirms_label": str | null,   // e.g. "FSK2" — the label decode
                                          // implies, independent of what
                                          // verify_estimator published
  "decode_confirms_rate_hz": float | null,
  "decode_feedback_status": "confirms" | "contradicts" | "no_prior_label" | null
    // "contradicts" is reported, never silently dropped — see §4's honesty note
}
```

`decode_status` at top level intentionally collapses to three values (not
`decode.py`'s current free-text-only field) so downstream JSON/SigMF/CSV
consumers can filter mechanically; `decode_reason` keeps the specific,
human-readable explanation every existing status string in `decode.py` and
`verify_estimator.py` already provides. This is additive: nothing currently
reading `decode.py`'s free-text `decode_status` breaks, because D4 (not this
pass) is where the field is actually changed in code, and D4's acceptance
criterion (per the task's stage list) is that the existing test suite still
passes with the new shape — i.e. D4 must audit every current caller of
`decode_status` before narrowing its value set, or add the new fields
alongside it if narrowing turns out to be breaking. Flagged here as a D4
open question, not resolved in D0.

## 4. How a verified decode feeds back into the label and rate verdict

`verify_estimator.py` publishes `modulation_label` / `symbol_rate_hz` only
when its margin gates pass (`gate()` in that module). A verified decode is
strictly stronger evidence than any margin: an algebraic check over the
actual recovered bits is proof the hypothesis explains the signal, not a
likelihood-ratio estimate that it probably does.

**Feedback rule:** when `decode_status == "decoded"`, the candidate's report
gets an additional field pair (`decode_confirms_label`,
`decode_confirms_rate_hz`) stating what the verified decode implies, and
`decode_feedback_status` records the relationship to whatever
`verify_estimator.py` (or `classify.py`) already published:

- **`confirms`**: decode's implied label/rate matches the existing published
  one. The report may say "label and rate verified by decode (CRC pass)" —
  exactly the task's requested phrase — attached to that candidate.
- **`contradicts`**: decode's implied label/rate *disagrees* with what was
  published (e.g. `verify_estimator` abstained or published something else,
  but a CRC-verified AIS frame says FSK2 @ 9600 Bd). This is reported
  honestly as a **new, separate criterion** (a WP3-style "here is where the
  two independent methods disagree" table), not resolved by silently
  overwriting one with the other — doing that would let a downstream bug in
  the decode chain corrupt a criterion that isn't about decoding at all.
- **`no_prior_label`**: `verify_estimator.py` abstained and decode is the
  only evidence. This is the WP3 "abstention this would correct" case the
  task asks to measure: count these on G5, report as a new criterion
  (§ D2 below), and do **not** change `real_correct_min`/`real_wrong_max`/
  etc. themselves — those stay exactly as registered in
  `experiments/readiness/config.py` today. Decode's correction is additive
  evidence for the report, not a retroactive edit to an existing scored
  outcome, so the existing scoreboard's history stays comparable across WPs
  the way `docs/reports/WP3.md`'s own "worse first" convention already
  requires.

This keeps the two verifiers (margin-based `verify_estimator`, algebraic
decode) independent and auditable, per the task's stated differentiator:
propose→verify for labels, and now decode→verify for content, cross-checked
rather than merged into one opaque number.

## 5. Method survey and bake-off candidates (D1)

Only listing genuine competitions — a family with one obvious, standard
method for this project's constraints gets that method directly, no
bake-off theater.

### Symbol timing
- **Gardner** — already implemented and validated (`timing_recovery.py`,
  locks ≥10 dB). Reused as-is for PSK/ASK; **not** re-litigated.
- **Mueller–Müller** — decision-directed, lower self-noise at high SNR but
  needs early bit decisions (chicken-and-egg at first lock) and is more
  sensitive to timing-offset transients than Gardner. Candidate for
  **GMSK/FSK timing** specifically, where Gardner's error term (derived for
  linear PSK/ASK constellations) is not directly applicable to a
  continuous-phase signal — bake off against Oerder–Meyer for this case only.
- **Oerder–Meyer** (non-data-aided, feedforward spectral-line timing
  estimator) — already effectively present in `expert_fsk.py`'s
  `spectral_line_timing`/Kay-tone-estimate machinery for the propose side;
  reusing that *technique* (not that code — this track writes its own
  implementation in `decode.py`, crediting the source paper) as the GMSK/FSK
  timing candidate is lower-risk than importing Mueller–Müller fresh, since
  the frequency-domain approach is already proven numerically stable on this
  project's FSK segments.
- **Bake-off criterion:** timing MSE (samples²) vs SNR on a synthetic
  GMSK/2-FSK fixture with known symbol instants, at G4's impairment levels.
  Winner carries into AIS Stage A.

### Carrier/phase
- **Mth-power** — already implemented (`decode.py`'s
  `estimate_phase_offset`, `classify.py`'s `refine_frequency`). Kept for PSK.
- **Costas loop** — decision-directed, tracks *drifting* phase (a loop, not
  a block estimate); relevant if D1's impaired fixtures include phase noise
  or slow drift that a single blind block estimate undersamples.
- **Decision-directed (post-timing-lock)** — refines the Mth-power estimate
  using provisional symbol decisions; cheap add-on, not a full competing
  architecture.
- GMSK/FSK do not need a phase bake-off: `discriminator` demodulation (below)
  sidesteps carrier phase entirely by construction (FM discrimination is
  differentially non-coherent), which is *why* GMSK/FSK is a good stage-1
  target — one less ambiguity source than PSK.
- **Bake-off criterion:** phase MSE (rad²) vs SNR, and — separately —
  whether a Costas loop or decision-directed refinement measurably lowers
  Stage A bit error rate over bare Mth-power under G4 phase-noise impairment
  specifically (if G4 has no phase-noise impairment today, this bake-off is
  registered as blocked on that generator existing, not skipped silently).

### GMSK/FSK bit decisions
- **Discriminator (frequency-domain, non-coherent)** — differentiate phase,
  threshold/cluster the instantaneous frequency (extends
  `expert_fsk.py`'s existing `_tone_clusters`/Kay-estimate machinery,
  reimplemented independently for the decode path since `decode.py` and
  `estimate_spike` are architecturally separate modules by this project's own
  convention). Simple, no channel-matched-filter assumption, degrades
  gracefully.
- **Matched filter** (correlate against the known GMSK/FSK pulse shape) —
  needs the actual TX pulse shape (BT product for GMSK), which is knowable
  for AIS specifically (ITU-R M.1371-5 fixes BT=0.4) but not in general for
  an unknown FSK signal — this project's own stated constraint
  (`docs/LIMITATIONS_AND_ROADMAP.md`: "the real pulse shape isn't known a
  priori for an arbitrary captured signal", quoted from `decode.py`'s own
  Phase 1 docstring). Matched filter is therefore only a fair bake-off entry
  for AIS specifically (protocol-known BT), not for generic rtl_433 FSK.
- **Bake-off criterion:** BER vs SNR on synthetic GMSK (BT=0.4, matching
  AIS) both with and without the matched filter, to quantify what the known
  pulse shape actually buys before deciding whether AIS Stage A pays the
  extra complexity of pulse-shape-aware filtering, or the simpler
  discriminator already clears the gate at AIS's real recorded SNR.

### Interleaver / code length identification (D3 only)
- **GF(2) rank-deficiency over candidate lengths** — for each candidate
  block length n, build the bit matrix and test whether it's consistent with
  a linear block code of some rate (rank deficiency reveals redundancy); the
  true length is the smallest n where deficiency stabilizes. This is the
  only method the task names, and no clearly competing alternative is
  registered for D0 (syndrome-trellis length estimation and
  cross-correlation-of-interleaved-error-patterns exist in the literature
  but need a chosen code family to already be assumed, which is circular for
  a *blind* length search) — so D3 proceeds with rank-deficiency as the sole
  method, not a bake-off, and this is stated plainly rather than manufacturing
  a competition where the task's own phrasing didn't describe one.

## 6. Catalogue of standard codes (cite-or-cut)

Every entry below has a citable public standard. Nothing without one is
attempted (per the task's rule and this project's existing evidence-first
convention).

| Code / framing | Standard | Used by |
|---|---|---|
| NRZI line coding | ITU-R M.1371-5 §3.3 (AIS physical layer, referencing HDLC NRZI convention, itself from ISO/IEC 13239) | AIS |
| HDLC framing + bit-stuffing (`0x7E` flag, stuff after five consecutive 1s) | ISO/IEC 13239 (HDLC), as invoked by ITU-R M.1371-5 §3.3.3 | AIS |
| CRC-16/X-25 (a.k.a. CRC-16-CCITT variant, poly 0x1021, init 0xFFFF, reflected, final XOR 0xFFFF) | ITU-R M.1371-5 Annex 8; confirmed against the standard CRC-16/X-25 catalogue definition (e.g. as tabulated in the reveng/CRC RevEng catalogue, a well-known cross-reference, not a code source) | AIS FCS |
| AIS message types 1/2/3/5/18/24 field layouts | ITU-R M.1371-5 Annex 8 Tables 45–79 (used only for D2's "cross-check message type and length against the standard", not to add message types not implemented) | AIS |
| CCSDS convolutional code, K=7, rate 1/2, Viterbi decoding | CCSDS 131.0-B-3 ("TM Synchronization and Channel Coding") §3 | D3 catalogue only — no known real recording in scope uses it |
| Reed–Solomon (255,223) | CCSDS 131.0-B-3 §4 / CCSDS 101.0-B-6 (historical reference for the (255,223) RS code, dual-basis, interleave depth per CCSDS) | D3 catalogue only |
| Block interleaver (row/column) | generic, cited via CCSDS 131.0-B-3 §5 (block interleaving of RS codewords) | D3 catalogue only |
| Convolutional (cross) interleaver | generic, cited via CCSDS 131.0-B-3 §5 | D3 catalogue only |
| rtl_433 per-device OOK/FSK framing (short/long pulse widths, PCM/Manchester) | each device's own `r_device` definition in the `rtl_433` source (pinned commit in `g5_manifest.json`); the framing/timing constants are read from that source per-device, not guessed | rtl_433 devices in G5 |

Codes not in this table end as `decode_status: "not_decoded"`,
`decode_reason: "code not in catalogue"` — stated plainly, matching the
task's explicit instruction, and matching this project's existing convention
of never implying a broader capability than what was built
(`docs/LIMITATIONS_AND_ROADMAP.md`'s "Deliberately out of Phase 1" section is
the precedent for this kind of explicit boundary).

## 7. What D0 deliberately does not decide

- Whether Mueller–Müller or Oerder–Meyer wins the GMSK/FSK timing bake-off —
  that's D1's measured result, not a D0 guess.
- The exact internal function signatures in `decode.py`'s extension — D1
  writes those once the bake-off has a winner, so the API isn't designed
  around a method that loses.
- Whether `decode_status`'s value-set narrowing (§3) is safe for existing
  callers — flagged as a D4 open question, to be answered by grepping every
  current reader of `candidate["decode_status"]` before that field's shape
  changes, not assumed safe here.
- Any change to Detect's bounds, pulsed-burst handling, or
  `verify_estimator.py`'s gates — explicitly out of scope per the task's
  hard rule; if D2's real-file work finds a Detect bound too wrong to work
  around from inside `decode.py`, that stops and gets reported rather than
  silently patched.

## References (credit, not copied code)

- Rice, *Digital Communications: A Discrete-Time Approach* — Gardner TED and
  loop-filter design (already cited in `timing_recovery.py`; carried forward
  for any new PI-loop code in D1).
- Oerder, M. and Meyer, H., "Digital Filter and Square Timing Recovery,"
  IEEE Trans. Communications, 1988 — feedforward timing estimator, technique
  credited for the GMSK/FSK timing candidate.
- Mueller, K.H. and Müller, M., "Timing Recovery in Digital Synchronous Data
  Receivers," IEEE Trans. Communications, 1976.
- Costas, J.P., "Synchronous Communications," Proc. IRE, 1956.
- ITU-R Recommendation M.1371-5, "Technical characteristics for an automatic
  identification system using time division multiple access in the VHF
  maritime mobile frequency band."
- ISO/IEC 13239, "Information technology — Telecommunications and
  information exchange between systems — High-level data link control
  (HDLC) procedures."
- CCSDS 131.0-B-3, "TM Synchronization and Channel Coding," Blue Book.
- Berlekamp, E.R., *Algebraic Coding Theory*, 1968 (Berlekamp–Massey
  algorithm, for D3's RS decoder).
- Viterbi, A.J., "Error Bounds for Convolutional Codes and an Asymptotically
  Optimum Decoding Algorithm," IEEE Trans. Information Theory, 1967.
