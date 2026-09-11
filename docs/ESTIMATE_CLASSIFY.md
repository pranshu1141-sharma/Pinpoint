# Estimate and Classify — integrated, DSP fallback rung 2

The delivered pipeline is **Estimate + coarse envelope family + carrier refinement**. Fine classification retains measured phase-spread diagnostics but publishes null label/confidence. Symbol-rate estimation was not attempted after fine classification failed its QPSK majority target. These functions now run in synchronous `POST /api/analyze` (uploads ≤1 MiB) and `POST /api/demo`; their fields are preserved in JSON export and displayed in the dashboard detail table. Async large uploads remain Detect-only. The Detect algorithm and downstream math are unchanged.

## Integration boundary

API `run_analysis` calls `analyze_candidate` after Detect, passing the original `Capture`, each completed candidate and the exact already-computed Welch noise density. `DetectionResult.noise_floor` carries this internal scalar without a dB round trip; it is not a new response field. Preserving the raw occupied samples and `floor * sample_rate` reference preserves the validated full-band SNR and bandwidth contract. Pre-isolating the input and substituting `floor * detected_bandwidth` would change that contract (the BPSK 10 dB fixture would report about 24 dB instead of 9.97 dB). Downstream classification continues to use its existing band-isolation helper.

Large-file analysis shares `analyze_capture` for each overlapping block, then clips and merges candidates into full tracks. Those block estimates have no validated merge rule. Integration therefore happens only in synchronous API orchestration, and all 21 downstream fields remain absent from async results. A real 5,376,000-byte, 672,000-sample upload exercised two processing blocks, completion polling and JSON export in the API tests; its merged candidates remain Detect-only.

`elapsed_ms` on synchronous API results now includes Detect plus all downstream work, excluding ingest and response serialization. The unchanged pipeline log describes Detect's own timing and operations. The integration reaches its requested full API/UI rung; the separate DSP fallback remains rung 2. See [integration verification](INTEGRATION_VALIDATION.md) for live measurements and timing.

## Calling the functions

```python
from backend.pipeline.detect import analyze_capture
from backend.pipeline.classify import analyze_candidate

# capture is the existing, validated ingest.Capture with complex64 IQ.
detected = analyze_capture(capture).response
enriched = [analyze_candidate(capture, d) for d in detected["detections"]]
```

Individual entry points are `estimate.estimate_candidate`, `classify.classify_coarse`, `classify.refine_frequency`, and diagnostic-only `classify.classify_fine`, in that order. Each returns an enriched dictionary copy and does not mutate the Detect candidate or samples. `estimate_candidate` and `analyze_candidate` accept optional positive `noise_floor` in sample-unit²/Hz; otherwise they call the existing noise-floor estimator on the capture. For block-local use a caller must supply a matching `Capture`, candidate indices and block noise estimate; automatic large-capture integration is not built.

## Measurement contract

- `center_frequency_hz`: approved noise-subtracted PSD centroid inside the candidate band, plus known acquisition tuning frequency. With no tuning metadata, this is a baseband offset. Detect bounds remain baseband offsets.
- `bandwidth_3db_hz`: linearly interpolated crossings around the strongest connected half-power lobe. `bandwidth_99pct_hz`: shortest whole-bin band containing at least 99% of measured in-band power. Both fields always exist; unresolved widths are null. The 99% value is quantized to `sample_rate/1024`.
- `bandwidth_99pct_caveat`: exact requested string `unshaped-pulse-sidelobes` when the ratio exceeds five, otherwise null. This ratio alone cannot identify pulse shaping and also triggers on FM's multiple spectral lines.
- `snr_db`: `10*log10((P_on-P_off)/P_off)`, using all raw occupied samples and capture-level Welch noise density times sample rate. The convention matches the generator's full-band complex-noise SNR. It does not isolate overlapping-source power.
- `estimate_status`: estimated, partial truncated-lobe result, or an explicit not-reliably-estimated reason. All numeric fields are null for insufficient samples, real audio or no resolved excess power. Malformed bounds and nonfinite data raise `ValueError`.
- `modulation_family`: `constant-envelope` if the isolated envelope coefficient of variation is below 0.3, otherwise `varying-envelope`; null without usable evidence. The existing band-isolation helper already mixes to the candidate midpoint; correction removes only the remaining frequency offset. The longest occupied interval is used and 128 samples are trimmed at each end to exclude FIR edge transients.
- `envelope_variation`, `modulation_confidence`, `modulation_confidence_kind`, `modulation_status`: measured coefficient, the specified distance-from-0.3 score, and explicit heuristic/status labels. Constant envelope includes FM and does not assert digital modulation.
- `center_frequency_refined_hz`, `refinement_order`, `refinement_sharpness`, `refinement_status`: separate M=2/4 raised-tone Welch/log-parabolic interpolation, selecting the higher peak/median ratio. The direct centroid is preserved. Null for varying envelope or unavailable evidence. The raised signal is amplitude-normalized to prevent overflow without changing frequency or sharpness.
- `fine_modulation_label` and `fine_modulation_confidence`: always null at this fallback. `phase_cluster_spread_rad` contains the requested circular-spread measurement when available; `fine_modulation_status` explains the fallback.
- `symbol_rate_hz`: always null. `symbol_rate_status`: `not reliably estimated (not attempted: fallback rung 2)`. This is not a claim that the proposed SNR gate or rate estimator was implemented. Fresh generator truth files record 500 Hz for BPSK/QPSK, null for other waveforms; waveform generation is unchanged.

Welch remains two-sided Hann, 1,024 samples, 50% overlap, no detrending, using the existing helper. Separate pulse PSDs are equally averaged before centroid/bandwidth calculations; overlapping pulse intervals form a union. Gaps never contribute. All sample indices are end-exclusive. A short pulse causes an explicit unknown rather than an undocumented omission.

## Reproducible evidence

Run from the repository root:

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests -q
.\.venv\Scripts\python.exe -m backend.tests.run_estimate_check
.\.venv\Scripts\python.exe -m backend.validate
```

[The measured JSON](estimate-classify-validation.json) includes every enriched continuous-fixture result, ten refinement trials, all twenty exploratory fine-rule trials, a clearly labeled true-frequency diagnostic, and null symbol-rate results at 10/5/0/-5 dB. Truth is used for scoring only; the production functions never read it.

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

Ten BPSK trials at 10 dB, seeds 47–56, use the generator waveform with 7,200/48,000 cycles/sample and a declared 1 MHz sample rate: true offset 150 kHz, duration 96 ms, symbol rate 10,416.667 Hz. No resampling or change to the generator's random symbols/noise is involved. All trials select M=2. Mean absolute center error changes from **5.6533 Hz** (centroid) to **0.4041 Hz** (raised-tone peak). This meets the tens-of-Hz target; the old approximately 5 kHz coarse-error expectation no longer applies after the approved centroid correction.

### Fine-classification boundary

The original threshold is retained: circular spread <0.8 radians. On five seeds (47–51) per case, BPSK passes 5/5 at both 20/10 dB, but QPSK passes only 2/5 at both levels. Those two QPSK majority checks are strict expected failures in pytest, so an unexpected improvement forces a review of the documented fallback rather than silently changing claims.

For QPSK seed 47 at 10 dB, refined frequency error is +0.07533 Hz and measured spread is 1.30496 radians. A diagnostic correction using the known true frequency gives 0.58531 radians: small residual frequency error accumulates over the two-second segment. This diagnostic uses truth only to explain the failed hypothesis; no output is corrected with truth. No threshold was relaxed, segment shortened to force a label, or replacement synchronization algorithm introduced. All fine labels remain null, and Stage 5 was not attempted, as allowed by fallback rung 2.
