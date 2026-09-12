# SIH26147 — Master Project Context

## 1. What This Project Is

- **PS ID:** SIH26147
- **Title:** Automated model for analysis of .IQ and .wav files along with signal parameter extraction
- **Sponsor:** NTRO (National Technical Research Organisation)
- **Category:** Software
- **Core task:** given a raw radio-frequency capture (no human has looked at it), automatically extract: center frequency, bandwidth, SNR, pulse timing/envelope characteristics, and (as far as feasible) modulation type and symbol rate — without a human RF analyst manually reading a spectrogram.
- **Team constraints (stated up front, not hidden):** no confirmed prior RF/DSP or SDR hardware background. Software-only — we process **provided or realistically-simulated** `.iq`/`.wav` files; we are not building or operating an SDR receiver.
- **Competitive context:** ~40–90 estimated submissions on this PS — lower competition than flagship AI/app tracks.

This is a **signal-processing / classification problem**, not a chatbot, dashboard, or web-app problem. That framing matters for the architecture section below.

---

## 2. File Formats & Ingestion — what's actually in these files, and why we handle them this way

### `.iq` files — raw complex baseband
A raw `.iq` file is just a binary block of numbers (interleaved I and Q floats) — **no header, no sample rate, no frequency information built in.** You cannot correctly process one without a sidecar telling you those things.

**SigMF (Signal Metadata Format)** is the standard we adopt to solve this. A SigMF recording = two files:
- `capture.sigmf-data` — the raw binary samples
- `capture.sigmf-meta` — a JSON sidecar with three sections:
  - `global`: sample rate, datatype (e.g. `cf32_le` = complex float32, little-endian), hardware, author
  - `captures`: frequency + sample offset for each capture segment
  - `annotations`: labeled regions (exactly the shape our own detector output reuses — see §6)

Why SigMF specifically: it has a **"signal" extension** built for describing modulation/wireless-signal attributes, so our tool's output has a natural, judge-recognizable home instead of inventing a bespoke report format. Cheap credibility signal in front of an NTRO panel.

### `.wav` files — audio, not IQ by default
`.wav` only carries the ordinary WAV header (sample rate, bit depth, channel count) — no frequency/modulation metadata, and it's **real-valued**, not complex, unless it's specifically a 2-channel recording where channel 1 = I and channel 2 = Q (some SDR software exports this way).

So the first ingestion step for any `.wav` is **disambiguation**: is this an IQ-pair recording, or real demodulated audio?
- Check: cross-correlation / quadrature relationship between channels (if stereo) tells you if channel 2 is a 90°-shifted version of channel 1 (→ IQ pair) or unrelated audio (→ real audio).
- If it's real audio: reconstruct the missing "Q" channel mathematically using a **Hilbert transform** (`scipy.signal.hilbert`), producing the analytic signal — a complex signal whose real part is the original audio and whose imaginary part is its 90°-phase-shifted version. After this, the exact same downstream pipeline (built for complex IQ) applies unchanged.

### Common internal representation
Regardless of source format, everything is converted to one shape before processing:
> **complex baseband numpy array + sample rate + optional center-frequency metadata**

- `.iq`: loaded via `numpy.memmap` — memory-maps the file instead of reading it fully into RAM, so files larger than available memory don't break the pipeline.
- `.wav`: loaded via `scipy.io.wavfile`, then Hilbert-transformed if needed as above.

**Why memmap even though we don't expect huge files:** cheap insurance. Building it in from day one costs almost nothing and quietly covers the pipeline if NTRO's eval files turn out bigger than expected — without over-engineering for a worst case that's unlikely (40–90 teams need to test uniformly against the same files, so extreme sizes are improbable).

---

## 3. Architecture — no frontend/backend split, by design

Worth stating explicitly since it's a common point of confusion: **this project is a script/pipeline, not a web app.**

- **No frontend.** No web UI, no mobile app, no dashboard.
- **No backend server, no database, no auth.** Nothing here needs to be "always on" or serve multiple users.
- **What actually exists:**
  - **Input:** a file path (`.iq`/`.sigmf-data` or `.wav`) + optional SigMF metadata
  - **Processing:** a Python pipeline (§4) run as a CLI script or notebook
  - **Output:** a JSON report (SigMF-annotation-shaped, §5) + PSD/spectrogram plots (matplotlib) with detected regions overlaid

**Why deliberately no GUI/app:** GUI polish is a design/frontend distraction from the actual problem being judged — signal-processing correctness. A shaky pipeline behind a polished app is a worse submission than a correct pipeline behind a plain script. A "deployable desktop app" is explicitly a **roadmap slide item**, not a 36-hour build target.

### Tech stack

| Layer | Choice | Why |
|---|---|---|
| Language | Python | Fast iteration, no prior GNU Radio/C++ experience required |
| Core numerics | `numpy` | Array/complex arithmetic |
| DSP | `scipy.signal` (`welch`, `spectrogram`, `find_peaks`, `hilbert`) | Standard, well-documented, no exotic dependencies |
| File I/O | `sigmf` (pip package), `scipy.io.wavfile`, `numpy.memmap` | Standard-compliant, handles large files |
| Classification (Stage 4, optional) | `scikit-learn` (k-means) | Simple, no training data required |
| Plotting | `matplotlib` | PSD/spectrogram visualization for the report |
| Speed (only if profiling shows a need) | `numba` | JIT-compile a *proven* bottleneck, not used speculatively |
| Explicitly roadmap-only | GNU Radio (block-based/real-time), C++/GPU/concurrency | Real rigor = profile first, optimize only the proven bottleneck; rewriting in C++ upfront is premature optimization that maximizes risk for a team without confirmed C++/DSP background |

---

## 4. The Pipeline — stage by stage, with formulas and the reasoning behind each choice

```
raw .iq / .wav
      │
      ▼
[1] DETECT — where in time/frequency is there energy?
      │
      ▼
[2] ESTIMATE — center freq, bandwidth, SNR, burst timing   (Plan A — reliable core)
      │
      ▼
[3] COARSE CLASSIFY — constant- vs varying-envelope
      │
      ▼
[3.5] REFINE FREQUENCY — Mth-power nonlinearity            (Plan B — unlocks 4 & 5)
      │
      ▼
[4] FINE CLASSIFY — IQ constellation clustering (BPSK/QPSK/etc.)
      │
      ▼
[5] SYMBOL RATE — nonlinearity + FFT, reliable 5–20 dB SNR
      │
      ▼
[6, optional] ANALOG DEMOD — AM/FM to audible .wav
      │
      ▼
REPORT — SigMF-shaped JSON + annotated plots
```

**Stages 1–2 are the non-negotiable floor** (classical DSP, no exotic dependencies). Stage 3.5 is a later addition that materially de-risked 4 and 5 — worth knowing the before/after story if a judge asks how the plan evolved.

### Stage 1 — Detection
**Goal:** find *where* (in time and frequency) there is signal, before asking what it is.

- Instantaneous power: `P[n] = |x[n]|²`
- Smooth with a moving-average window → short-time energy
- Estimate noise floor from a signal-free region (or a low percentile of the whole capture's PSD) — **use a median/low percentile, not the mean**, because the mean gets dragged up by the signal itself
- **Adaptive threshold (CFAR-style):** `threshold = noise_floor × margin` (e.g. 3×, or +6–10 dB) — samples above threshold = "signal present"
- Rising/falling edges of the thresholded mask → burst start/stop times (feeds Stage 2 timing)

**Why adaptive, not fixed:** a fixed absolute threshold breaks the moment the noise floor shifts between files — and it will, across captures/gain settings. This is a simplified CFAR (constant-false-alarm-rate) approach, the standard technique family for this problem.

### Stage 2 — Parameter Estimation

**Center frequency:**
- `scipy.signal.welch()` → PSD with much lower variance than a single raw FFT/periodogram, because it averages multiple overlapping windowed segments instead of relying on one noisy snapshot
- Peak bin of the PSD = coarse center frequency
- **Parabolic interpolation** across the 3 bins around the peak, for sub-bin accuracy without a finer (costlier) FFT:
  ```
  Let y₋₁, y₀, y₊₁ = PSD magnitude at (peak−1, peak, peak+1)
  offset = 0.5 × (y₋₁ − y₊₁) / (y₋₁ − 2y₀ + y₊₁)
  refined_freq = freq[peak] + offset × bin_spacing
  ```
- **Critical reliability step: average the PSD across multiple detected bursts before peak-finding.** A single burst's periodogram is high-variance — in the worked example, one burst alone gave a −3dB bandwidth estimate of 10.74 kHz vs. the correct ~44 kHz; averaging across all 10 bursts fixed it.

**Bandwidth — two definitions, used for different purposes:**
- **−3 dB (half-power) bandwidth:** width of the main lobe where PSD ≥ half its peak power. The default "engineer's" bandwidth.
- **99%-occupied bandwidth:** smallest band containing 99% of total signal power (standard spectrum-management definition — 0.5% of power below the lower edge, 0.5% above the upper edge).
  - **Known failure mode, worth a slide:** blows up on unshaped rectangular (NRZ) pulses, because their sinc-shaped sidelobes decay very slowly, so real energy sits far from the main lobe. In the worked example this metric came out at 914 kHz on a signal whose −3dB bandwidth was ~46 kHz. **Not a bug** — real systems apply pulse shaping (e.g. root-raised-cosine) specifically to avoid this.

**SNR:**
```
SNR_dB = 10 × log10((P_on − P_off) / P_off)
```
- `P_on` = average power during detected "on" time (from Stage 1's mask)
- `P_off` = average power during "off" time = the noise floor
- (A named alternative for blind SNR estimation without clean on/off segmentation is the **M2M4 moment-based estimator**, using 2nd/4th-order signal moments — flagged as more rigorous but potentially unstable at low SNR. The on/off ratio above is the one actually validated in the worked example and is the simpler, safer default.)

**Burst timing:**
- Duration = falling edge − rising edge (from Stage 1's mask)
- **PRI (Pulse Repetition Interval)** = time between consecutive rising edges

### Stage 3 — Coarse Modulation Classification
1. Frequency-correct the isolated burst: `x_corrected[n] = x[n] × exp(−j·2π·f_center_est·t)`
2. Instantaneous envelope: `envelope[n] = |x_corrected[n]|`
3. **Normalized envelope variation:**
   ```
   env_var_norm = std(envelope) / mean(envelope)
   ```
   - Low (roughly < 0.3) → **constant-envelope family** (PSK, FSK — digital)
   - High → **varying-envelope family** (ASK, QAM, AM)

**Why this is the robust first cut:** it only depends on amplitude, so it isn't corrupted by imprecise frequency correction the way phase-based methods are — trustworthy even before the harder refinement step below exists.

### Stage 3.5 — Frequency Refinement ("Plan B") — the step that unlocks everything after it
**The problem:** Stage 2's PSD-peak estimate is accurate enough for detection/bandwidth/SNR/timing, but **not** precise enough for anything phase-sensitive. In the worked example, ~4 kHz of residual frequency error caused the signal's phase to rotate through ~8 full turns over a single 2 ms burst — completely scrambling phase-based analysis.

**Technique — Mth-power nonlinearity:** for a constant-modulus digital signal (BPSK → M=2, QPSK → M=4), raising the frequency-corrected burst to the Mth power strips out the phase modulation, collapsing the signal into a single unmodulated tone at `M × (residual frequency offset)`:
```
y[n] = x_corrected[n] ^ M
```
Welch-PSD `y[n]`, peak-find it (reusing Stage 2's own peak-finding + interpolation code), then divide the result by `M`.

**Why this instead of a Costas loop / full carrier recovery:** a Costas loop (the "proper" synchronization technique) is genuinely more DSP-native and harder to build correctly without prior background. The Mth-power trick gets most of the benefit — ~15 lines of code, reusing existing peak-finding — without a synchronization-loop subsystem.

**Validated (Monte Carlo, N=100 trials, BPSK, true offset 150 kHz):**

| Method | SNR | Mean absolute frequency error |
|---|---|---|
| Stage 2 baseline (PSD peak) | 10 dB | 5,167 Hz |
| Stage 3.5 (M=2 squaring) | 10 dB | 44 Hz |
| Stage 3.5 (M=2 squaring) | −5 dB | 44 Hz (std ≈ 7 Hz) |

**~117× reduction in mean error** — squaring gives processing gain by turning a spread-out modulated spectrum into one narrow tone.

### Stage 4 — Fine Modulation Classification
**Technique — IQ constellation clustering:** plot instantaneous I vs Q of the Stage-3.5-refined, frequency-corrected signal; count/cluster the point cloud (2 clusters ≈ BPSK, 4 ≈ QPSK, …) using histogram peak-counting or k-means with a small range of `k` — **not** a trained deep network.

**Why it's now more tractable than originally assumed:** using Stage 3.5's refined frequency instead of Stage 2's raw one, folded-phase clustering spread for BPSK dropped from 1.83 rad (no usable clusters) to 0.56 rad (clean 2-cluster BPSK), close to the 0.46 rad achievable with the *true* frequency.

**Still genuinely open:** validated only on the 2-cluster BPSK case — a broader sweep across QPSK/8PSK is real remaining work. Keep a confidence score regardless.

**Fallback:** if this doesn't converge in time, report Stage 3's coarse family only, with a stated confidence.

### Stage 5 — Symbol Rate Estimation
**Technique — nonlinearity + FFT** (a simplified cyclostationary / "delay-and-multiply" method): on the Stage-3.5-refined signal, take the real part, compute its numerical derivative (spikes at symbol transitions), square it, then FFT/Welch-PSD:
```
nonlin[n] = (diff(Re(x_corrected))[n])²
```

**Two independent bugs, both had to be fixed:**
1. Imprecise frequency (Stage 2 alone) corrupts the phase → fixed by Stage 3.5's estimate.
2. **Harmonic ambiguity:** rectangular-NRZ symbol transitions sit at fixed periodic positions regardless of whether a transition occurs, so every harmonic of the true symbol rate is theoretically equal-strength. Naively taking the FFT's global max picks a harmonic essentially at random. **Fix:** take the *lowest* frequency bin within ~3 dB of the global max, not the raw argmax.

**Validated (both fixes applied, N=100 trials, "correct" = within 5% of true rate):**

| SNR | Correct |
|---|---|
| 10 dB | 100/100 |
| 5 dB | 95/100 |
| 0 dB | 8/100 |
| −5 dB | 0/100 |

**Honest reliable range: ~5–20 dB SNR.** Below that, noise amplification from the differentiation step is a separate, unsolved problem — the fallback applies: **report "not reliably estimated" rather than a specific wrong number.**

### Stage 6 (optional, zero allocated hours) — Analog Demodulation to Audio
Pure bonus differentiator, **never allowed to threaten required-stage time.**

- **Scope boundary:** AM/FM only. Never attempted on anything Stage 3/4 classified as digital — full digital decoding needs synchronization plus a specific voice codec that isn't reverse-engineerable in general. Digital signals get labeled `"not attempted — digital signal"`, never a garbage audio clip.
- **Routing:** high envelope variance → AM candidate. Low variance (PSK/FSK/FM all constant-envelope) → check the instantaneous-frequency trace: continuous, many-leveled → FM (attempt); discrete fixed levels → FSK (skip decode).
- **AM demod:** envelope detector `|x[n]|` → remove DC → low-pass to audio band (300 Hz–3 kHz) → decimate to 8/44.1 kHz → normalize to [−1,1] → write `.wav`
- **FM demod:** instantaneous frequency `= (Fs/2π) · d(unwrap(phase(x)))/dn` → same filter/decimate/normalize/write chain
- **Marker:** output `.wav` audibly recognizable. **Fallback:** present as a waveform plot instead of an overclaimed "decoded" clip.

---

## 5. Output Format

Detection output is shaped to be near-identical to a real **SigMF annotation object**, so it serializes as valid SigMF annotations essentially for free:

```json
{
  "start_sample": 120000,
  "end_sample": 340000,
  "freq_lower_hz": -125000,
  "freq_upper_hz": -75000,
  "confidence": 0.87,
  "detection_method": "adaptive_threshold",
  "is_pulsed": false,
  "pulse_width_samples": null,
  "pri_samples": null,
  "needs_review": false
}
```

The full report per detected signal adds: modulation label + confidence, SNR, and pulse timing — plus PSD/spectrogram plots with detected regions overlaid, for the demo.

---

## 6. What Existing Tools Already Do (the bar to beat)

| Tool | What it gives you | Gap it leaves |
|---|---|---|
| **GNU Radio** | FFT/waterfall/energy-detection *primitives* | Not a finished "file in, parameters out" tool; auto modulation classification exists only as research-grade side modules |
| **MATLAB Communications Toolbox** | Gold-standard reference: CNN classifying 11 modulation types at ~94% accuracy, using 10,000 training frames/type + real SDR validation | Not matchable in 36 hours with no prior DSP background — target coarse-family classification with stated confidence instead |
| **scikit-rf** | RF *network* analysis (S-parameters, VNA calibration, antenna/filter characterization) | **Not actually relevant** — nothing to do with analyzing an unknown captured signal's modulation/timing. Don't cite it; it costs credibility. |
| **IQEngine** | Closest real analog: web-based, SigMF-native, built-in auto-annotation detector, plugin system for further detection/classification | Leaves modulation classification and symbol-rate estimation as a *plugin slot* — exactly our hardest sub-problem, and a real, citable gap |

**Bottom line:** on frequency/bandwidth/timing/SNR, the bar is "a human doesn't have to click around a spectrogram" — clearly beatable, it's arithmetic on an FFT. On modulation classification, the bar is "no polished open tool does this automatically at all" — so even an honest, coarse, confidence-scored classifier is a real contribution.

### 6.1 Counter-Arguments — "Why not just use X?" (have these ready)

**vs. MATLAB Communications Toolbox:**
- MATLAB's classifier answers one of six things the PS asks for — it doesn't ingest a raw file, detect the signal, and produce a full structured report. That orchestration/automation is exactly the gap we fill.
- Cost: paid, per-seat license vs. our free, open Python stack — a real deployment-cost difference for a sponsor rolling this out widely.
- Explainability: a CNN gives a label with no reason; our cumulant/envelope features trace every output to a specific named measurement — matters more to an intelligence sponsor's trust than a black-box accuracy number.
- Honest degradation: CNNs trained on fixed synthetic data generalize poorly to novel/adversarial signals and fail *confidently* — our fallback ladder ("unclassified, confidence too low") is safer for genuinely unknown signals, the actual use case.
- Interoperability: SigMF-based output plugs into open tooling; MATLAB output stays inside MATLAB's ecosystem.

**vs. IQEngine:**
- IQEngine is a viewing/annotation platform — a human still opens it and looks at a spectrogram. The PS asks for an automated model, not a better way to look at signals.
- It explicitly leaves modulation classification and symbol-rate estimation as an empty plugin slot — exactly the hardest sub-problem we solve, not something we're duplicating.
- It's human-in-the-loop by design; our deliverable is unattended, start-to-finish, on an unseen file — a materially different automation claim.
- Deployment fit: IQEngine is browser-based; a self-contained, offline pipeline suits an NTRO SIGINT workflow better than a web app.
- Best framing to use live: don't compete with it — our SigMF-shaped output could literally *be* the plugin IQEngine is missing.

---

## 7. Explicitly Out of Scope (state proactively — reads as understanding, not gaps)

- **AOA (Angle of Arrival):** needs multiple antennas or a phased array to compare phase across receivers — a single-channel `.iq` file physically cannot contain that information.
- **Frequency-hopping / jamming defeat:** at most "detect and characterize" (peak frequency per time-slice, flag "frequency-agile, hop range X–Y, avg dwell Z ms") if time allows — never full defeat/demodulation through hopping.
- **Overlapping co-channel signal separation:** research-grade, flagged out of reach from the start.
- **Cyclostationary detection, deep-learning detector on spectrogram images:** valid techniques, documented as roadmap items, not 36-hour code.
- **Real-time/streaming detection:** run-once-on-a-file only.
- **Full digital demodulation to a decoded message:** never attempted — needs full sync + a non-reverse-engineerable codec.

---

## 8. Proof It Actually Works — Worked Example (synthetic BPSK burst)

**Ground truth:** 1 MS/s sample rate, 150.0 kHz true center-frequency offset, 50.0 kSym/s BPSK (rectangular/NRZ), 2.00 ms burst ON duration, 5.00 ms PRI, 10.0 dB SNR, 10 bursts.

| Estimate | Result | Truth | Verdict |
|---|---|---|---|
| Center frequency (Stage 2) | 153.99 kHz | 150.0 kHz | ~2.7% error |
| Center frequency (Stage 3.5 refined) | 149.96 kHz | 150.0 kHz | 44 Hz error |
| Bandwidth (−3 dB) | 45.90 kHz | ~44 kHz (theory) | Excellent |
| Bandwidth (99% occupied) | 914.06 kHz | — | Correctly reflects unshaped-NRZ sidelobe behavior |
| SNR | 9.99 dB | 10.0 dB | Excellent |
| Bursts detected | 10/10 | 10 | Correct |
| Burst duration | 2.029 ms | 2.00 ms | Excellent |
| PRI | 4.998 ms | 5.00 ms | Excellent |
| Envelope variation | 0.207 | — | Correctly flagged constant-envelope → digital PSK/FSK-family |
| Fine phase clustering (Stage 2 freq only) | Failed — no usable clusters | — | Fixed by 3.5 (spread 1.83 → 0.56 rad) |
| Symbol rate (Stage 2 freq only) | 250.00 kHz (wrong harmonic) | 50.0 kHz | Fixed by 3.5 + peak-picking fix → 48.83 kHz |

This shows the actual before/after of adding Stage 3.5: the original pipeline genuinely failed on fine classification and symbol rate; adding the frequency refinement and peak-picking fix (~15 extra lines total) turned both into reliable, bounded-range capabilities rather than stretch goals unlikely to converge.

---

## 9. 36-Hour Build Plan (condensed)

| Hours | Task | Notes |
|---|---|---|
| 0–2 | Env setup, repo skeleton, Python/numpy/scipy decided | — |
| 2–6 | Ingest: `.iq`/SigMF + `.wav` → PSD/spectrogram baseline | — |
| 6–10 | Detection + Stage 2 estimation (freq/BW/SNR/timing) | — |
| 10–12 | SigMF-annotated output; test end-to-end on 3–4 synthetic signals | **PROTOTYPE CHECKPOINT — non-negotiable floor** |
| 12–13 | Stage 3.5 frequency refinement | Validated, no fallback needed — treat as reliable core |
| 13–20 | Stage 3 coarse classification; begin Stage 4 fine classification | Fallback: freeze at Stage 3 by hour 20 if 4 isn't converging |
| 20–26 | Stage 5 symbol rate | Fallback decision at hour 24: "not reliably estimated" if not converging |
| 26–30 | Broader testing across SNRs/signals/edge cases | — |
| (opportunistic) | Stage 6 analog demod — only if ahead of schedule | Drop silently if not working; zero protected time |
| 30–33 | Demo script, plots/metrics for PPT | — |
| 33–36 | Buffer, PPT finalization, rehearsal, submission | **Protected — never build new features here** |

**Guiding rule:** Markers are go/no-go checkpoints. If a phase isn't at its Marker by the stated hour, take the Fallback and move on — protecting the final packaging/pitch time matters more than perfecting any one phase.

---

## 10. Formula Quick-Reference

| Quantity | Formula |
|---|---|
| Instantaneous power | `P[n] = \|x[n]\|²` |
| Parabolic peak interpolation | `offset = 0.5×(y₋₁ − y₊₁) / (y₋₁ − 2y₀ + y₊₁)` |
| SNR (on/off ratio) | `SNR_dB = 10·log10((P_on − P_off) / P_off)` |
| Frequency correction | `x_corrected[n] = x[n]·exp(−j·2π·f_center·t)` |
| Envelope | `env[n] = \|x_corrected[n]\|` |
| Normalized envelope variation | `env_var_norm = std(env) / mean(env)` |
| Mth-power frequency refinement | `y[n] = x_corrected[n]^M`, peak-find PSD(y), divide by `M` |
| Symbol-rate nonlinearity | `nonlin[n] = (diff(Re(x_corrected))[n])²`, FFT/Welch, pick **lowest** bin within ~3 dB of max |
| Instantaneous frequency (FM demod) | `f_inst[n] = (Fs / 2π) · d(unwrap(phase(x)))/dn` |

---

## 11. Future Scope — Terminal Application & Open-Source Package

Not built in the 36-hour core, but both are cheap to add on top of the same code — worth stating as roadmap.

### Terminal (CLI) application
- **What:** wrap the pipeline so `python analyze.py signal.iq` runs the full pipeline and saves the JSON report + plots — no code editing needed to run it.
- **How to achieve it:** a thin `argparse` wrapper around the existing pipeline functions. Almost free, since Phase 6's demo script already runs end-to-end unattended.
- **Bonus automation win:** add folder/batch mode — point it at a directory, it processes every file inside with no human touching it between files. This is the clearest possible proof of "automated," stronger than one carefully-run demo file.

### Open-source importable package
- **What:** the same pipeline usable as `from sih_pipeline import analyze; analyze("file.iq")` inside someone else's code, not just from the terminal.
- **How to achieve it:** structure the pipeline as clean, separate functions (`detect()`, `estimate()`, `classify()`) in a proper module from the start, instead of one linear script. The CLI just calls these functions — same code, two ways to use it, nothing duplicated.
- **Why it matters for judging:** shows the tool is a reusable component, not a one-off script — a strong, cheap differentiator that also directly strengthens the interoperability pitch point already made about SigMF/IQEngine (§6, §6.1).

---

## 12. If Future Scope Is Realized — the Bigger Picture

Should the CLI + package layer get built (post-hackathon, or near the end if time allows):

- **Architecture (§3) gains one line, nothing changes underneath:** still no backend server, no database, no web app — just two additional *entry points* (a CLI command and an importable module) on top of the same pipeline functions. "No frontend/backend split, by design" still holds — this isn't a pivot, it's packaging.
- **Deployment story strengthens:** NTRO (or any downstream user) could drop the package into their own scripts, or run it standalone from a terminal on an air-gapped machine — no browser, no server, no internet dependency. This directly reinforces the IQEngine counter-argument (offline, self-contained fit for a SIGINT workflow) and the interoperability point about SigMF.
- **Automation story strengthens:** batch/folder mode becomes the headline proof of "automated" — a judge can watch it process a whole folder of unseen files with zero human interaction, a stronger demo than one script run once.
- **What still doesn't change:** this remains explicitly *not* real-time streaming and *not* an API — file-in/report-out, just now callable three ways (script, CLI, import) instead of one. The core DSP pipeline (§4) is untouched; this is purely an interface upgrade layered on a working core, which is why it's safe to defer without risking the required deliverable.
