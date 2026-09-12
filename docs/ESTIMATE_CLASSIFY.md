# Estimate and Classify — Estimate, coarse family, carrier refinement, fine PSK classification, and symbol-rate estimation

The delivered pipeline is **Estimate + coarse envelope family + Mth-power carrier refinement + fine PSK classification (bpsk/qpsk) + symbol-rate estimation**, all gated to continuous candidates within their validated SNR ranges. Fine classification publishes `fine_modulation_label`/`fine_modulation_confidence` when the phase-cluster circular spread clears its threshold; pulsed (gated-carrier) candidates are explicitly excluded from fine classification, since an unmodulated gated carrier has trivially perfect phase concentration that would otherwise be misread as BPSK. Symbol-rate estimation runs when a candidate has a confirmed fine PSK label and measured SNR at or above 4.5 dB; it stays null with an explicit reason otherwise. These functions run in synchronous `POST /api/analyze` (uploads ≤1 MiB) and `POST /api/demo`; their fields are preserved in JSON export and displayed in the dashboard detail table. Async large uploads remain Detect-only. The Detect algorithm and the direct-centroid/coarse-family math are unchanged; only the Mth-power refinement's frequency-estimation resolution and the fine/symbol-rate stages changed in this pass.

## Integration boundary

API `run_analysis` calls `analyze_candidate` after Detect, passing the original `Capture`, each completed candidate and the exact already-computed Welch noise density. `DetectionResult.noise_floor` carries this internal scalar without a dB round trip; it is not a new response field. Preserving the raw occupied samples and `floor * sample_rate` reference preserves the validated full-band SNR and bandwidth contract. Pre-isolating the input and substituting `floor * detected_bandwidth` would change that contract (the BPSK 10 dB fixture would report about 24 dB instead of 9.97 dB). Downstream classification continues to use its existing band-isolation helper.

Large-file analysis shares `analyze_capture` for each overlapping block, then clips and merges candidates into full tracks. Those block estimates have no validated merge rule. Integration therefore happens only in synchronous API orchestration, and all 21 downstream fields remain absent from async results. A real 5,376,000-byte, 672,000-sample upload exercised two processing blocks, completion polling and JSON export in the API tests; its merged candidates remain Detect-only.

`elapsed_ms` on synchronous API results now includes Detect plus all downstream work, excluding ingest and response serialization. The unchanged pipeline log describes Detect's own timing and operations. The integration reaches its requested full API/UI rung, and the DSP stages now include fine PSK classification and gated symbol-rate estimation rather than stopping at coarse family and refinement. See [integration verification](INTEGRATION_VALIDATION.md) for live measurements and timing.

## Calling the functions

```python
from backend.pipeline.detect import analyze_capture
from backend.pipeline.classify import analyze_candidate

# capture is the existing, validated ingest.Capture with complex64 IQ.
detected = analyze_capture(capture).response
enriched = [analyze_candidate(capture, d) for d in detected["detections"]]
```

Individual entry points are `estimate.estimate_candidate`, `classify.classify_coarse`, `classify.refine_frequency`, `classify.classify_fine`, and `classify.estimate_symbol_rate`, in that order. Each returns an enriched dictionary copy and does not mutate the Detect candidate or samples. `estimate_candidate` and `analyze_candidate` accept optional positive `noise_floor` in sample-unit²/Hz; otherwise they call the existing noise-floor estimator on the capture. For block-local use a caller must supply a matching `Capture`, candidate indices and block noise estimate; automatic large-capture integration is not built.

## Measurement contract

- `center_frequency_hz`: approved noise-subtracted PSD centroid inside the candidate band, plus known acquisition tuning frequency. With no tuning metadata, this is a baseband offset. Detect bounds remain baseband offsets.
- `bandwidth_3db_hz`: linearly interpolated crossings around the strongest connected half-power lobe. `bandwidth_99pct_hz`: shortest whole-bin band containing at least 99% of measured in-band power. Both fields always exist; unresolved widths are null. The 99% value is quantized to `sample_rate/1024`.
- `bandwidth_99pct_caveat`: exact requested string `unshaped-pulse-sidelobes` when the ratio exceeds five, otherwise null. This ratio alone cannot identify pulse shaping and also triggers on FM's multiple spectral lines.
- `snr_db`: `10*log10((P_on-P_off)/P_off)`, using all raw occupied samples and capture-level Welch noise density times sample rate. The convention matches the generator's full-band complex-noise SNR. It does not isolate overlapping-source power.
- `estimate_status`: estimated, partial truncated-lobe result, or an explicit not-reliably-estimated reason. All numeric fields are null for insufficient samples, real audio or no resolved excess power. Malformed bounds and nonfinite data raise `ValueError`.
- `modulation_family`: `constant-envelope` if the isolated envelope coefficient of variation is below 0.3, otherwise `varying-envelope`; null without usable evidence. The existing band-isolation helper already mixes to the candidate midpoint; correction removes only the remaining frequency offset. The longest occupied interval is used and 128 samples are trimmed at each end to exclude FIR edge transients.
- `envelope_variation`, `modulation_confidence`, `modulation_confidence_kind`, `modulation_status`: measured coefficient, the specified distance-from-0.3 score, and explicit heuristic/status labels. Constant envelope includes FM and does not assert digital modulation.
- `center_frequency_refined_hz`, `refinement_order`, `refinement_sharpness`, `refinement_status`: separate M=2/4 raised-tone peak with log-parabolic interpolation, selecting the higher peak/median ratio. The peak is now estimated from a single full-segment-length Hann periodogram (capped at 2^20 samples) rather than a fixed 1,024-point Welch average, so frequency resolution scales with the segment instead of staying fixed at ~46.9 Hz regardless of length. The direct centroid is preserved. Null for varying envelope or unavailable evidence. The raised signal is amplitude-normalized to prevent overflow without changing frequency or sharpness.
- `fine_modulation_label` and `fine_modulation_confidence`: Mth-power phase-cluster circular spread on the refined, frequency-corrected segment; published as `"bpsk"`/`"qpsk"` with a `1 - spread/threshold` heuristic confidence when the measured spread clears <0.8 rad. Pulsed (`is_pulsed: true`) candidates never reach this stage — `fine_modulation_status` reads `not reliably classified (pulsed bursts not validated)` for them. Non-pulsed candidates whose spread stays at or above threshold (FM, low-SNR PSK) keep null label/confidence with status `not reliably classified (phase spread above threshold)`; candidates with no refined evidence at all get `not reliably classified (no phase refinement)`. `phase_cluster_spread_rad` always reports the measured circular spread when refinement produced one, independent of whether it clears the labeling threshold. `fine_modulation_confidence` is an explicit heuristic, not a calibrated probability.
- `symbol_rate_hz`: estimated only when `fine_modulation_label` is `"bpsk"` or `"qpsk"` **and** measured `snr_db` is at least 4.5 dB; otherwise null with an explicit `symbol_rate_status` reason (`not reliably estimated (requires a confirmed PSK fine label)` or `not reliably estimated (SNR below validated 5-20 dB range)`). The estimator differentiates and squares the real part of the refined segment, takes its Welch PSD, and picks the lowest bin — excluding the first 4 DC-leakage bins under the window's main lobe — within 3 dB of the global peak, resolving the harmonic-ambiguity problem inherent to rectangular-NRZ symbol timing. Validated 30/30 within 5% of the generator's 500 Hz truth across bpsk/qpsk × {20,10,5} dB × seeds 47–51; accuracy below the 4.5 dB gate is not validated and is reported as unknown, not silently extrapolated. Fresh generator truth files record 500 Hz for BPSK/QPSK, null for other waveforms; waveform generation is unchanged.

Welch remains two-sided Hann, 1,024 samples, 50% overlap, no detrending, using the existing helper. Separate pulse PSDs are equally averaged before centroid/bandwidth calculations; overlapping pulse intervals form a union. Gaps never contribute. All sample indices are end-exclusive. A short pulse causes an explicit unknown rather than an undocumented omission.

## Reproducible evidence

Run from the repository root:

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests -q
.\.venv\Scripts\python.exe -m backend.tests.run_estimate_check
.\.venv\Scripts\python.exe -m backend.validate
```

[The measured JSON](estimate-classify-validation.json) includes every enriched continuous-fixture result, ten refinement trials, all twenty `fine_rule` phase-cluster trials (with an oracle true-frequency diagnostic alongside each), and the `symbol_rate` results across 20/10/5/0/-5 dB for both BPSK and QPSK. Truth is used for scoring only; the production functions never read it.

All direct frequency errors below are relative to **8,000 Hz baseband truth**, not to a large RF tuning offset. Thus the unchanged 2% tolerance has not been diluted by metadata. SNR truth is the requested full-band SNR. `C` means constant-envelope; `V` means varying-envelope. Results are from seed 47 after both approved fixes.

| Fixture | SNR truth dB | Center Hz | Frequency error % | SNR measured dB | −3 dB width Hz | 99% width Hz | Envelope variation | Family |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| BPSK | 20 | 8000.0738 | 0.0009 | 19.9670 | 453.4709 | 1500.000 | 0.2364 | C |
| BPSK | 10 | 8000.2585 | 0.0032 | 9.9686 | 453.3546 | 1500.000 | 0.2432 | C |
| BPSK | 0 | 8000.7829 | 0.0098 | −0.0357 | 454.8802 | 1546.875 | 0.2680 | C |
| BPSK | −5 | 8002.9963 | 0.0375 | −5.0580 | 460.0697 | 843.750 | 0.3405 | V |
| QPSK | 20 | 7998.7465 | 0.0157 | 19.9665 | 446.2499 | 1500.000 | 0.1903 | C |
| QPSK | 10 | 7998.7002 | 0.0162 | 9.9645 | 446.8942 | 1546.875 | 0.1944 | C |
| QPSK | 0 | 7998.3521 | 0.0206 | −0.0501 | 450.3514 | 1546.875 | 0.2259 | C |
| QPSK | −5 | 7998.8692 | 0.0141 | −5.0838 | 459.2943 | 796.875 | 0.2871 | C |
| FM | 20 | 8000.0241 | 0.0003 | 19.9634 | 65.7666 | 1921.875 | 0.0175 | C |
| FM | 10 | 8000.0918 | 0.0011 | 9.9717 | 65.6996 | 1921.875 | 0.0521 | C |
| FM | 0 | 8000.3433 | 0.0043 | −0.0153 | 65.7402 | 1921.875 | 0.1467 | C |
| FM | −5 | 8019.0019 | 0.2375 | −5.0232 | 66.2438 | 1687.500 | 0.2599 | C |

Center and SNR acceptance pass all twelve fixtures. Coarse family passes all nine >=0 dB fixtures; BPSK at −5 dB shows the heuristic's limit. The generator supplies nominal detection extents, **not theoretical half-power bandwidths**. Its 1,800/2,200 Hz nominal bands are not used as −3 dB truth. The half-power implementation is additionally tested against an analytical Gaussian spectrum within the requested 15% tolerance. No claim of theoretical fixture-width accuracy is made without that truth.

The shrinking 99% widths at −5 dB reflect the detector's narrower threshold-selected band, not a measured reduction in the waveform's true bandwidth. FM's approximately 66 Hz half-power result describes its strongest line under the 1,024-point Welch window, not its whole modulation spectrum.

### Independent refinement acceptance after the centroid change

Ten BPSK trials at 10 dB, seeds 47–56, use the generator waveform with 7,200/48,000 cycles/sample and a declared 1 MHz sample rate: true offset 150 kHz, duration 96 ms, symbol rate 10,416.667 Hz. No resampling or change to the generator's random symbols/noise is involved. All trials select M=2. Mean absolute center error changes from **5.6533 Hz** (direct centroid, unchanged) to **0.0627 Hz** (raised-tone peak, after matching the periodogram length to the segment). This is itself an improvement over the previously reported 0.4041 Hz raised-tone result, which used a fixed 1,024-point Welch average regardless of the ~96,000-sample segment length — that fixed resolution (~46.9 Hz raw bin width) is what left the residual frequency error large enough to block fine classification below.

### Fine-classification boundary

The root cause of the earlier QPSK failure was diagnosed, not worked around: `refine_frequency` estimated the Mth-power raised-tone peak from a fixed 1,024-point Welch average irrespective of segment length. For a ~2 s / ~96,000-sample segment that gave far coarser resolution than the segment could support, and for QPSK (M=4) that residual frequency error is multiplied fourfold and accumulates into multiple radians of phase drift over the segment — exactly the mechanism the previous version of this document had already traced. The fix replaces the fixed 1,024-point window with a single full-segment-length periodogram (capped at 2^20 samples), so resolution scales with segment length instead of staying fixed. No threshold was relaxed, no segment was shortened to force a label, and no synchronization loop was introduced — the acceptance rule is still circular spread <0.8 radians on the Mth-power phase clusters.

On five seeds (47–51) per case, both BPSK and QPSK now pass 5/5 at both 20 dB and 10 dB (20/20 trials in `fine_rule`), where QPSK previously passed only 2/5. Representative measured spreads from the JSON: BPSK seed 47 at 20 dB has phase-cluster spread 0.0946 rad (previously accumulated to about 1.3 rad range before the fix); QPSK seed 47 at 20 dB has spread 0.5406 rad and at 10 dB 0.5856 rad — both comfortably under the 0.8 rad threshold. FM candidates still correctly never resolve a label: their spread stays around 1.39–1.46 rad across all four SNRs, which the JSON confirms is driven by genuine continuous phase modulation rather than carrier imprecision, so the FM behavior is unchanged by this fix.

One correctness guard was added alongside the resolution fix: pulsed/gated-carrier candidates (`is_pulsed: true`) are now explicitly excluded from fine classification. An unmodulated gated carrier has trivially perfect phase concentration, which — without this guard — would be indistinguishable from a genuine BPSK carrier and would get misclassified. Excluded candidates report `fine_modulation_status: "not reliably classified (pulsed bursts not validated)"`.

Symbol-rate estimation (`estimate_symbol_rate`) is now implemented, gated to a confirmed `fine_modulation_label` of `"bpsk"`/`"qpsk"` and measured SNR ≥ 4.5 dB. It differentiates and squares the real part of the refined segment, takes a Welch PSD, and selects the lowest bin within 3 dB of the global peak — excluding the first 4 bins, not just bin 0, since the squared-derivative nonlinearity's non-negative DC term leaks into several bins under the Hann window's main lobe (observed ~4 bins wide) and could otherwise be picked as a spuriously "lowest" harmonic. Measured against the `symbol_rate` section of the JSON: 30/30 trials across bpsk/qpsk × {20,10,5} dB × seeds 47–51 land within 5% of the generator's 500 Hz truth (representative value: 499.8381 Hz). Below the SNR gate (0 dB, −5 dB) or without a confirmed PSK label, the field stays null with an explicit `symbol_rate_status` rather than a guess — e.g. `not reliably estimated (SNR below validated 5-20 dB range)` or `not reliably estimated (requires a confirmed PSK fine label)`.

Remaining, genuinely open gaps: only BPSK (M=2) and QPSK (M=4) are supported — no 8PSK, 16-QAM, or other constellation order. `fine_modulation_confidence` remains an explicit `1 - spread/threshold` heuristic, not a calibrated probability. Symbol-rate accuracy below the validated 5–20 dB SNR range (4.5 dB gate) is unverified and reported as unknown rather than assumed to work. All of this remains synthetic-fixture evidence only; no field capture has exercised either stage.
