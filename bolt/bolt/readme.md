# SIH26147 Signal-Analysis Dashboard — Frontend

Phase 1 (Detect) frontend for the signal-analysis pipeline. Built to look and
behave like real RF instrumentation software (GQRX, SDR#, Inspectrum), not a
web dashboard or sci-fi HUD.

## Design Decisions — Mapping to Real RF Software Conventions

### Palette: Qt Fusion Dark Theme
The color scheme is taken directly from the Qt Fusion dark palette that real
desktop RF tools (GQRX, SDR++, Inspectrum) are built on:

| Token | Hex | Role |
|---|---|---|
| Window background | `#353535` | Main app background |
| Panel background | `#3c3c3c` | Dock panels, toolbars, status bar |
| Recessed/plot background | `#252525` / `#1e1e1e` | FFT plot, waterfall canvas |
| Border/divider | `#3c3c3c` / `#4a4a4a` | All 1px solid borders |
| Primary text | `#d4d4d4` | Labels, values |
| Secondary text | `#7f7f7f` | Axis labels, metadata |
| Accent (selection) | `#2a82da` | Selected detection, active tab |
| Alert (needs_review) | `#cc3c34` | Threshold line, review markers |

No gradients, no box-shadows, no glow effects. Borders are 1px solid, always.
Corners are 2px radius maximum. This is what real instrument software looks
like — flat, functional, information-dense.

### Typography
- **Inter** (system-ui fallback) for all labels, menus, and UI text.
- **JetBrains Mono** (Roboto Mono fallback) with `font-variant-numeric:
  tabular-nums` for every numeric readout — frequency, dB values, sample
  counts, timestamps. This ensures digits align in columns and don't shift
  width as values change, matching the behavior of real instrument displays.

No display or decorative fonts anywhere.

### Waterfall Colormap
The classic cold-to-hot gradient used by GQRX, SDR#, and Inspectrum:
dark blue → blue → cyan → green → yellow → orange → red → white.

This is deliberately **not** viridis/inferno/plasma — those read as "modern
data visualization," not "radio instrument." The cold-to-hot map is the
convention RF engineers expect; it maps intuitively to signal intensity.

### Animation
Minimal, functional, fast. All CSS transitions are under 150ms for state
changes (panel collapse, selection highlight, tab swap). No scanning sweeps,
no boot sequences, no typewriter effects, no pulsing glows. A control change
should feel instant — the way toggling a setting in GQRX does.

### Layout Conventions
- **Top toolbar**: thin, flat — file open, sample rate/duration readout, analyze
  button. Mirrors GQRX/SDR# toolbar layout.
- **Center stacked plots**: FFT/PSD on top, waterfall below, sharing one
  frequency (x) axis. The threshold line is draggable (GQRX/SDR# squelch-line
  convention). Detections drawn as flat brackets, not glowing boxes.
- **Right sidebar**: styled as Qt dock widgets (title bar with collapse
  arrow). Detections table, file info, pipeline log — all flat, no cards.
- **Bottom status bar**: sample rate, duration, cursor frequency/power —
  standard desktop RF tool convention.
- **Signal Breakdown**: collapsible panel below the plots, flat tabs per
  layer, disabled tabs for unavailable layers (visually distinct from hidden).

## Architecture

```
src/
  components/
    Toolbar.tsx           — file open, analyze, readout
    FftPlot.tsx           — PSD line plot + draggable threshold + noise floor + peak markers
    Waterfall.tsx         — canvas spectrogram with cold-to-hot colormap
    DetectionsPanel.tsx  — flat detection table + stats header + CSV export
    DetectionDetailPanel — full metadata for selected detection (pulse/PRI/PRF)
    FileInfoPanel.tsx    — monospace key/value file metadata
    PipelineLogPanel.tsx — scrollable pipeline log
    StatusBar.tsx        — bottom status bar with cursor + noise floor + selected ID
    SignalBreakdown.tsx  — layer tabs + waveform canvas + wavesurfer player
    DockPanel.tsx        — reusable Qt-style dock widget wrapper
    ColormapLegend.tsx   — colorbar legend beside waterfall
    WelcomeScreen.tsx    — drag-and-drop empty state
  lib/
    types.ts             — TypeScript interfaces for API contract
    api.ts               — API client (analyze, spectrogram, layers)
    colormap.ts          — cold-to-hot colormap + LUT builder
    format.ts            — frequency/dB/time/sample formatters
    mockData.ts          — mock data generator (6 detections, rich pipeline log)
```

## Features

- **Drag-and-drop file loading** — drop an IQ file anywhere on the welcome screen
- **FFT/PSD plot** — filled line, peak markers per detection, draggable threshold line
- **Waterfall** — cold-to-hot colormap with colorbar legend, detection brackets
- **Detections table** — sortable columns, stats header (total/pulsed/review/avg conf), CSV export
- **Detection Detail panel** — full metadata: center freq, bandwidth, duration, pulse width, PRI, PRF
- **Signal Breakdown** — per-layer tabs with waveform canvas + wavesurfer audio player
- **Keyboard shortcuts** — Arrow keys to navigate detections, Space to toggle breakdown, Esc to deselect
- **Crosshair cursor readout** — frequency + power in the FFT plot, frequency + time in the waterfall
- **Status bar** — sample rate, duration, noise floor, threshold, detection count, selected ID, cursor values

## API Contract

The frontend consumes these endpoints (already implemented in the backend):

- `POST /api/analyze` — file upload, returns detections + noise floor + log
- `GET /api/spectrogram/{job_id}` — time/freq bins + 2D magnitude array
- `GET /api/detections/{job_id}/{detection_id}/layers` — per-layer waveform data

When no backend is available, the app uses mock data generators that produce
realistic-looking IQ-style data so the full UI is demonstrable. Set
`useMockData.current = false` in `App.tsx` to switch to the real API.

## Detect-Stage Scope

This frontend only presents Detect-stage results (candidate signal regions
in time/frequency). It does not imply modulation classification or
demodulation. The Signal Breakdown panel shows Detect-stage transformations
(isolated band, magnitude envelope, pulse profile) — not decoded content.
A visible notice reads: "Detect-stage isolation only — full demodulation is a
planned future stage (Classify), not built here."
