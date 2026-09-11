# SIH26147 Detect Documentation

This directory is the complete technical and project context for the current Phase 1 **Detect** implementation. The root [`README.md`](../README.md) remains the quickest way to install and run the application. These documents explain what exists, why it exists, how the parts communicate, what has been verified, and what remains outside the implemented scope.

## Current identity

- Project: SIH26147
- Sponsor context: NTRO, Smart India Hackathon, software track
- Implemented phase: Phase 1 — Detect
- Product type: offline radio-capture signal detector and inspection dashboard
- Primary purpose: find candidate regions where energy consistent with a signal exists in time and frequency
- Explicit non-purpose: this version does not identify modulation, demodulate IQ, decode audio/data, track frequency hopping, or classify a transmitter
- Documentation audit date: 2026-09-10

## Reading order

| Document | Read it when you need to understand… |
|---|---|
| [Project status](PROJECT_STATUS.md) | The exact completion state of every original requirement. |
| [Architecture](ARCHITECTURE.md) | The system boundaries, request flow, runtime state, and component relationships. |
| [Repository map](REPOSITORY_MAP.md) | The responsibility and dependencies of every project-owned file and artifact family. |
| [Backend pipeline](BACKEND_PIPELINE.md) | The DSP sequence, formulas, thresholds, output semantics, and engineering rationale. |
| [Input formats](INPUT_FORMATS.md) | How IQ, WAV, and SigMF files are interpreted, validated, or rejected. |
| [API reference](API_REFERENCE.md) | Every endpoint, request parameter, response object, status code, and job state. |
| [Frontend dashboard](FRONTEND_DASHBOARD.md) | Every panel, interaction, visualization, state, and frontend dependency. |
| [Signal Breakdown](SIGNAL_BREAKDOWN.md) | What each isolation layer does and why it is not decoding. |
| [Large-file processing](LARGE_FILE_PROCESSING.md) | The 1–2 GiB upload path, bounded-memory scan, block merge rules, storage, and recovery. |
| [Testing and validation](TESTING_AND_VALIDATION.md) | Automated coverage, synthetic truth, measured results, and the limits of those results. |
| [Operations](OPERATIONS.md) | Installation, startup, routine use, troubleshooting, cleanup, and operational constraints. |
| [Limitations and roadmap](LIMITATIONS_AND_ROADMAP.md) | Known technical limits and everything intentionally unbuilt. |
| [Judge defense guide](JUDGE_DEFENSE_GUIDE.md) | Concise, defensible explanations for an SIH technical review. |
| [Glossary](GLOSSARY.md) | RF, DSP, file-format, API, and UI terminology used by the project. |

## Truth hierarchy

When two descriptions appear inconsistent, use this order:

1. Executing source code and dependency locks describe current behavior.
2. Passing automated tests describe behavior verified in the current environment.
3. `backend/validation-report.json`, `backend/large-file-validation.json`, and `test-audio/measured-results.json` contain recorded measurements from real runs of the current pipeline at the time they were generated.
4. This documentation explains the inspected implementation and evidence.
5. The original product prompt describes desired scope; it is not proof that a feature was implemented.

Generated reports can become stale after source changes. Regenerate and rerun the commands in [Testing and validation](TESTING_AND_VALIDATION.md) before making performance or completion claims.

## Status vocabulary

| Term | Meaning in these documents |
|---|---|
| Complete | Source exists and fresh verification covers the relevant behavior. |
| Implemented | Source exists; the entry names the available verification and any limits. |
| Partial | A meaningful subset exists, but the prompt's complete behavior is absent. |
| Not built | No working implementation exists. |
| Intentionally out of scope | The original prompt expressly prohibited implementation in Phase 1. |
| Measured | A value came from an executed test or validation artifact. |
| Heuristic | An engineering score or decision rule that is not statistically calibrated. |

## Core safety and honesty rules

- Frontend results come from the real FastAPI pipeline. When the API is unreachable, the UI displays a disconnected state instead of example results.
- The UI and API call outputs **detections** or **candidates**. They do not call them decoded messages or identified modulations.
- IQ files require an explicit sample rate and datatype unless valid SigMF metadata supplies them.
- Ambiguous stereo WAV files require an explicit user interpretation.
- Power is reported as dB relative to one sample-unit squared per hertz. It is not dBm because capture-chain calibration is unavailable.
- A confidence value is an evidence score, not a probability that the signal is real.
- Large-file display pooling reduces only retained visualization detail. The detector scans every sample block.

## Maintainer rule

Update the relevant focused document whenever an interface, limit, algorithm, dependency, test, or completion state changes. Update [Project status](PROJECT_STATUS.md) only after fresh verification. Avoid copying full source into documentation; link to the source and document its public behavior, assumptions, dependencies, and rationale so there is one executable source of truth.
