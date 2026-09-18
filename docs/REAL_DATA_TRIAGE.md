# Real-data triage (Phase 1 of the field-validation roadmap item)

This documents the project's runs against captures it did not generate itself: one file in the first pass (sigid3), extended to a second (GRCon23 CTF "qam") in a later pass once fine classification grew beyond BPSK/QPSK. Every prior accuracy claim in this repo (`docs/ESTIMATE_CLASSIFY.md`, `docs/PROJECT_STATUS.md`, `backend/validation-report.json`) still comes exclusively from `backend/pipeline/synth_gen.py`'s synthetic generator. This document is evidence only — nothing here should be read as a broader accuracy claim than the specific files it describes.

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
| Refinement | tried, order 2 (BPSK hypothesis) selected | not attempted (requires constant-envelope) |
| PSK phase-spread test | declined, spread 1.18 rad (above 0.8 rad threshold) | not attempted |
| **FSK cluster test (new, see below)** | **fine_modulation_label = "fsk", confidence 1.0, 2 frequency levels, gap/spread score 12.9 (trimmed) / 14.3 (full)** | not attempted (requires constant-envelope) |
| `symbol_rate_status` | `not reliably estimated (requires a confirmed PSK/ASK fine label)` (FSK is excluded from this gate) | same |
| Confidence / review | 90%, not flagged | 54%, **flagged for review** |

*(Table shows the trimmed slice's numbers; the full recording's values are the same to the precision shown here except where the "new finding" below discusses them separately.)*

None of the six known failure modes from the original investigation (DC spike/IQ imbalance, non-flat noise floor, sample-rate mismatch, clipping, multi-emitter interference, frequency drift/multipath) were flagged by `triage_real.py`'s heuristic checks on this file — `dc_spike_suspected`, `noise_floor_nonflat`, and `clipping_suspected` were all `False` for both the trimmed and full versions. This one recording happens to be clean of the most common real-hardware artifacts; that is a property of this specific file, not a general claim about real captures. (`noise_floor_nonflat` actually measures whole-PSD dynamic range, not the noise floor specifically — it would trip on a strong narrowband signal too, so "not flagged" here is a weaker claim than "the noise floor is provably flat.")

**What actually worked:** the pipeline found real energy, at real frequencies, with a real (Detect-stage) confidence split that correctly flagged the weaker candidate for review. Fine PSK classification correctly declined to guess on a real signal it wasn't confident about — refinement selected an M=2 (BPSK) hypothesis, but the phase-cluster spread (1.18 rad) sat well above the 0.8 rad acceptance threshold, and the pipeline reported "not reliably classified" rather than a false "bpsk" label. This is exactly the intended honest-degradation behavior, and it held on the first unseen real file tried.

**A finding from the first pass (now root-caused, see below):** the refined center frequency was **not stable** between the trimmed and full versions of the same recording — 929,292,300 Hz (trimmed, 0.524 s) vs. 929,282,700 Hz (full, 1.387 s), a ~9.6 kHz difference. The synthetic validation in `docs/ESTIMATE_CLASSIFY.md` reports sub-Hz refinement error on its BPSK fixtures; at the time, nothing in this repo had tested whether that refinement is stable on real, non-BPSK-shaped data.

## Phase 2: FSK classification succeeds, and the instability is explained

Extending fine classification beyond BPSK/QPSK (see [Estimate and Classify](ESTIMATE_CLASSIFY.md)) added an instantaneous-frequency-clustering path (`classify_fine_fsk`) that runs as a fallback whenever every PSK Mth-power hypothesis fails. Re-running `python -m backend.triage_real` against the same sigid3 files with this new code produced the pipeline's **first real-capture positive classification**: candidate 0 is now labeled `fine_modulation_label: "fsk"` with confidence 1.0 on both the trimmed and full recordings independently.

This is not a marginal call. Directly inspecting the instantaneous frequency of the corrected segment (`np.diff(np.unwrap(np.angle(x)))*fs/(2*pi)`) shows two tight, well-separated clusters in both files:

| | Trimmed (0.524 s, 130,815 samples) | Full (1.387 s, 346,367 samples) |
|---|---|---|
| Cluster separation score (gap / within-cluster std) | 12.9 | 14.3 |
| Low tone | -4729 Hz, std 738 Hz, 49.9% of samples | -4704 Hz, std 649 Hz, 50.3% of samples |
| High tone | +4768 Hz, std 738 Hz, 50.1% of samples | +4823 Hz, std 667 Hz, 49.7% of samples |

Two independent time slices of the same file agree on a ~4.7-4.8 kHz frequency deviation with a near-exactly 50/50 duty cycle between tones — consistent with 2-level FSK paging traffic (e.g. POCSAG-style signaling, which commonly uses several-kHz deviation) at 929.25 MHz, a documented US paging-band frequency. This is the kind of cross-validated, physically-plausible positive result the field-validation roadmap item was looking for, not just an honest decline.

**The refinement instability is now explained, not just observed.** `refine_frequency` runs *before* fine classification decides what the signal actually is; it only checks that the coarse envelope family is constant-envelope (true for both real PSK and real FSK) before searching for a sharp Mth-power raised-tone peak. For genuine PSK, that search converges on a stable estimate because the hypothesis is correct. For this signal — now confidently known to be FSK, not PSK — the order-2 "raised tone" the search locks onto is a spurious artifact of squaring frequency-shift-keyed data, not a real carrier line, and there is no reason to expect it to land on the same frequency for two different segment lengths of the same non-PSK signal. The ~9.6 kHz discrepancy is exactly what an unconfirmed, wrong hypothesis produces — not a resolution bug in the Mth-power search itself (which remains validated and stable on genuine PSK fixtures, see `docs/ESTIMATE_CLASSIFY.md`).

This is deliberately **not** "fixed" by suppressing `center_frequency_refined_hz` when fine classification doesn't confirm PSK: `refinement_status` already labels it a "heuristic," and an existing test (`test_sync_pulses_and_sigmf_absolute_frequency`) relies on the refined value staying available even when fine classification is intentionally skipped (pulsed candidates). The correct fix already exists in the pipeline's design — `fine_modulation_label` is the field that gates trust, and a caller must not treat `center_frequency_refined_hz` as validated unless a fine label confirms the hypothesis it came from. What changed here is understanding, not code: this is the first concrete, explained example of that design principle actually mattering on real data.

## A second real file: GRCon23 CTF "qam" (correct decline on real, degraded QAM)

**Source:** GRCon23 CTF's "qam" challenge ("Broken modulator," `https://ctf-2023.gnuradio.org`), also by Clayton Smith (the same verified real-hardware CTF author as sigid3), obtained the same way via IQEngine's public browser. Format: SigMF, `cf32_le`, 835,584 samples, 38.4 kHz sample rate, RF center 1337 MHz, 6,684,672 bytes. Regenerate via `python -m backend.triage_real` (added to `FILES` in `backend/triage_real.py`).

Detect found one candidate at [-6469, 6431] Hz baseband (RF ~1337.0 MHz), SNR 25.75 dB, correctly classified `varying-envelope` (envelope variation 0.44 — a real signal, not noise). Unlike sigid3, this file's own heuristic checks flagged real hardware artifacts: `dc_spike_suspected: true` and `noise_floor_nonflat: true` (both `false` for sigid3), consistent with the challenge's own "broken modulator" framing.

The QAM heuristic (`classify_fine_ask`, see [Estimate and Classify](ESTIMATE_CLASSIFY.md)) **declined** to publish a label: `fine_modulation_status: "not reliably classified (envelope levels not well separated)"`. Directly inspecting the envelope-clustering score shows why — it measured 2.84, just under the 3.0 acceptance threshold, on a genuinely continuous, roughly bell-shaped envelope distribution (min 0.0014, max 2.35, mean 0.89, std 0.40) rather than the crisp, well-separated discrete levels the synthetic QAM fixture produces. This is very plausibly root-raised-cosine pulse shaping and inter-symbol interference on a real constellation blending adjacent amplitude levels together — an effect the idealized synthetic generator doesn't reproduce, and which the current clustering approach (no matched filtering or symbol-timing recovery) isn't built to see through.

**This was treated as evidence, not as a target to tune against.** The threshold was not lowered to force this one file to classify — doing so would fit a heuristic to a single real sample rather than validating it, which is exactly the overfitting risk this project's own rigor is meant to avoid. The correct reading is: on a real, degraded QAM-family signal, the classifier declined rather than guessing, which is the intended honest-degradation behavior, but it also surfaced a concrete, specific gap (ISI-blurred real envelopes vs. idealized synthetic ones) worth fixing with matched filtering or symbol-timing recovery in a future pass, not silently ignoring.

## Phase 3: the two confidence scores disagree, instructively

Once `confidence_evidence_based` (see [Limitations and roadmap](LIMITATIONS_AND_ROADMAP.md)'s Confidence section) existed, re-running `python -m backend.triage_real` against all three real files surfaced genuine disagreement between it and the original `confidence`:

| | sigid3 candidate 0 (fsk) | sigid3 candidate 1 (unclassified, flagged) | qam candidate |
|---|---|---|---|
| `confidence` (trimmed / full) | 90% / 88% | 54% / 54% | 95% |
| `confidence_evidence_based` (trimmed / full) | 51% / 70% | 87% / 86% | 69% |

Candidate 1 — the weaker candidate the original heuristic correctly flagged for review — scores *high* on the evidence-based statistic: its power distribution shape deviates substantially from pure noise even though its threshold-excess margin is small. This is exactly the situation two independent evidence channels are for: a human reviewer sees both "this barely clears the energy threshold" and "this really doesn't look like noise" side by side, rather than one number averaging the two claims away.

The FSK candidate's evidence-based score also moved more between the trimmed and full recordings (51% vs 70%, a 19-point swing) than its original heuristic score did (90% vs 88%, 2 points) — consistent with what was already measured about this statistic in `docs/LIMITATIONS_AND_ROADMAP.md`: the coefficient-of-variation estimator needs more samples to stabilize, and the trimmed slice has roughly a third of the full recording's samples in this band. This is not a bug fix candidate; it is exactly the kind of measured-not-assumed evidence about the new statistic's real-data behavior that this triage exercise is for.

## What this phase does and does not establish

This is two files, from one real author/source, at a small number of SNRs. The qam file does have real hardware artifacts (DC spike, non-flat floor) per its own heuristic flags, and the classifier correctly declined on it rather than guessing — but that is one degraded real QAM example, not a general robustness claim. It does not establish field performance, a false-alarm rate, or that the pipeline is robust to DC offset/colored noise/clipping/drift in general. It also does not establish anything about ASK or 8PSK on real data — no real capture of either has been tried yet (see [Limitations and roadmap](LIMITATIONS_AND_ROADMAP.md)). Establishing broader field performance requires the multi-source, multi-condition dataset described in that document's roadmap item 1, which remains open.

## Reproduce

```
source .venv/bin/activate
python -m backend.triage_real
```

Writes `backend/triage-report.json` (per-file, per-candidate detail) and prints a console summary.
