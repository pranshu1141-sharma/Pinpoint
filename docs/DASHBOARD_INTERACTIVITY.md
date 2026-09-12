# Dashboard interactivity

## Scope statement

This is the professional analyst dashboard getting genuinely interactive, not
redesigned. Core covers deep interactivity on the spectrogram and detection
list, full evidence-trail transparency on classification/symbol-rate outputs,
tighter Signal Breakdown controls, and the export/session/notes layer analysts
will actually use. Nice-to-have ships if time allows without breaking the idea
if cut. Manual review is explicitly parked, not built now. Nothing is Out.

This pass does not change the NASA mission-control aesthetic, the cyan accent,
monospace numerics, glow-on-active states, or the scanning sweep animation.
Every number shown must still come from a real computed value returned by the
backend; nothing here introduces mocked or placeholder data, consistent with
how the rest of [FRONTEND_DASHBOARD.md](FRONTEND_DASHBOARD.md) is built.

## Core (build this pass)

- [x] Click-to-inspect readout on the spectrogram (live freq/power/time at cursor)
- [x] Zoom/pan controls on the spectrogram
- [x] Detection rows clickable → jump spectrogram viewport to that detection
- [x] Sortable/filterable detection table (confidence, frequency, needs_review)
- [x] Confidence-threshold slider live-filtering the detection list + spectrogram
- [x] Adjustable CFAR margin control with live re-run
- [x] Interactive accuracy-vs-SNR curve (hover for trial counts)
- [x] Symbol-rate panel: reveal the FFT plot with the chosen harmonic marked
- [x] Modulation panel: reveal cumulant features + decision-tree path
- [x] "Explain this number" affordance on every estimated value
- [x] Signal Breakdown: adjustable auto-play speed
- [x] Signal Breakdown: per-layer download (waveform image + audio clip)
- [x] Synced playhead — audio scrub position mirrored on the spectrogram
- [ ] SigMF export preview panel + copy-to-clipboard before download
- [ ] Session history panel — reload previously analyzed files
- [ ] Per-detection analyst notes field
- [x] Distinct styling for "not reliably estimated" states
- [ ] Keyboard shortcuts + discoverable shortcuts overlay

## Nice-to-have (documented, not built this pass)

- Draggable region selector to re-run estimation on a sub-region
- Side-by-side two-layer comparison (Signal Breakdown)
- Live pipeline-stage progress checklist
- "Report card" snapshot export

## Maybe-later (parked)

- Manual review workflow (confirm/reject a detection) — trigger: once the
  classifier is in active use and analysts want to correct its mistakes
