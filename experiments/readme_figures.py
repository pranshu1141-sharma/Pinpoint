"""Render the README figures from measured data, in light and dark variants.

    python -m experiments.readme_figures

Inputs are the bundled demo capture (run through the real Detect pipeline)
and the committed readiness scoreboard (docs/readiness.json). Nothing is
invented here: every plotted number comes from one of those two sources.
Output: docs/assets/charts/<name>-{light,dark}.svg
"""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib.colors import LinearSegmentedColormap  # noqa: E402
from matplotlib.patches import Rectangle  # noqa: E402
from matplotlib.ticker import MaxNLocator, PercentFormatter  # noqa: E402
from matplotlib.transforms import offset_copy  # noqa: E402

from backend.pipeline.detect import analyze_capture  # noqa: E402
from backend.pipeline.ingest import load_capture  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "assets" / "charts"

# Chart chrome per GitHub theme. Backgrounds stay transparent so the figures
# sit on the README page itself; ink and series steps change per mode.
THEMES = {
    "light": dict(ink="#0b0b0b", ink2="#52514e", muted="#898781", grid="#e1e0d9",
                  axis="#c3c2b7", s1="#2a78d6", s2="#eb6834", box="#0b0b0b",
                  track="#e8eef6", seq=["#ffffff", "#cde2fb", "#6da7ec", "#256abf", "#0d366b"]),
    "dark": dict(ink="#f0efec", ink2="#c3c2b7", muted="#898781", grid="#2c2c2a",
                 axis="#383835", s1="#3987e5", s2="#d95926", box="#f0efec",
                 track="#1b2533", seq=["#0d1117", "#0e2a3a", "#0f5f78", "#1fb3cf", "#b8f3ff"]),
}
FONT = ["Inter", "Segoe UI", "Helvetica Neue", "DejaVu Sans", "sans-serif"]


def style(theme):
    c = THEMES[theme]
    plt.rcParams.update({
        "font.family": "sans-serif", "font.sans-serif": FONT, "font.size": 10,
        "figure.facecolor": "none", "axes.facecolor": "none", "savefig.facecolor": "none",
        "text.color": c["ink"], "axes.labelcolor": c["ink2"], "axes.edgecolor": c["axis"],
        "xtick.color": c["muted"], "ytick.color": c["muted"],
        "axes.grid": False, "grid.color": c["grid"], "grid.linewidth": 0.8,
        "axes.spines.top": False, "axes.spines.right": False,
        "svg.fonttype": "none",
    })
    return c


def save(fig, name, theme, fmt="svg"):
    OUT.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT / f"{name}-{theme}.{fmt}", bbox_inches="tight", pad_inches=0.15, transparent=True, dpi=130)
    plt.close(fig)


def title(fig, text, sub, c):
    renderer = fig.canvas.get_renderer()
    top = max(fig.transFigure.inverted().transform(ax.get_tightbbox(renderer).corners())[:, 1].max()
              for ax in fig.axes)
    fig.text(0.0, top, text, fontsize=13, fontweight="bold", color=c["ink"], ha="left", va="bottom",
             transform=offset_copy(fig.transFigure, fig, y=24, units="points"))
    fig.text(0.0, top, sub, fontsize=9.5, color=c["ink2"], ha="left", va="bottom",
             transform=offset_copy(fig.transFigure, fig, y=8, units="points"))


# --------------------------------------------------------------------- demo

def demo_result():
    data = (ROOT / "backend/data/demo/demo.sigmf-data").read_bytes()
    meta = (ROOT / "backend/data/demo/demo.sigmf-meta").read_text()
    capture = load_capture("demo.sigmf-data", data, sigmf_meta=meta)
    return capture, analyze_capture(capture)


def waterfall(theme, capture, result):
    c = style(theme)
    fs = capture.sample_rate
    f = result.frequencies / 1e3
    t = result.times
    p = 10 * np.log10(np.maximum(result.power, 1e-30))
    noise = np.median(p)
    lo, hi = noise - 2, np.percentile(p, 99.8)
    cmap = LinearSegmentedColormap.from_list("seq", c["seq"])

    fig, ax = plt.subplots(figsize=(9, 4.2))
    ax.pcolormesh(t, f, p, cmap=cmap, vmin=lo, vmax=hi, shading="auto", rasterized=True)
    # Ground truth only names the boxes; the detector never sees it.
    truth = json.loads((ROOT / "backend/data/demo/demo.truth.json").read_text())["signals"]
    labels = {}
    for det in result.response["detections"]:
        for sig in truth:
            if sig["freq_lower_hz"] < det["freq_upper_hz"] and det["freq_lower_hz"] < sig["freq_upper_hz"]:
                labels[det["id"]] = f"{sig['kind'].upper() if sig['kind'] != 'pulsed' else 'Pulsed'} · {sig['snr_db']} dB"
    for det in result.response["detections"]:
        x0, x1 = det["start_sample"] / fs, det["end_sample"] / fs
        y0, y1 = det["freq_lower_hz"] / 1e3, det["freq_upper_hz"] / 1e3
        pad = 0.9
        ax.add_patch(Rectangle((x0, y0 - pad), x1 - x0, y1 - y0 + 2 * pad, fill=False, ec=c["box"], lw=0.9))
        for w in det.get("pulse_windows", []):
            a, b = w["start_sample"] / fs, w["end_sample"] / fs
            ax.plot([a, b], [y0 - pad - 0.6] * 2, color=c["box"], lw=2.0, solid_capstyle="butt")
        ax.text(x1 - 0.03, y1 + pad + 0.5, f"#{det['id']}  {labels.get(det['id'], '')}  ·  conf {det['confidence']:.2f}",
                fontsize=8.5, color=c["ink"], ha="right", va="bottom",
                bbox=dict(boxstyle="round,pad=0.25", fc=c["seq"][0], ec="none", alpha=0.85))
    ax.set_xlabel("Time (s)")
    ax.set_ylabel("Baseband offset (kHz)")
    ax.set_xlim(t[0], t[-1])
    ax.set_ylim(-22, 22)
    ax.spines[["left", "bottom"]].set_visible(False)
    ax.tick_params(length=0)
    title(fig, "Detect on the bundled demo capture",
          "Spectrogram · adaptive-threshold candidates (boxes) · measured pulse windows (ticks) · 48 kS/s, 4 s", c)
    save(fig, "demo-waterfall", theme, fmt="png")


def psd(theme, capture, result):
    c = style(theme)
    r = result.response
    f = np.array([row["frequency_hz"] for row in r["psd"]]) / 1e3
    pw = np.array([row["power_db"] for row in r["psd"]])
    fig, ax = plt.subplots(figsize=(9, 3.0))
    ax.fill_between(f, pw, pw.min() - 3, color=c["s1"], alpha=0.10, lw=0)
    ax.plot(f, pw, color=c["s1"], lw=1.6, solid_joinstyle="round")
    for y, name in ((r["noise_floor_db"], "noise floor"), (r["threshold_db"], "threshold (+8 dB)")):
        ax.axhline(y, color=c["ink2"], lw=0.9)
        ax.text(f[0] + 0.4, y + 0.4, f"{name}  {y:.1f} dB", fontsize=8.5, color=c["ink2"], ha="left", va="bottom")
    for det in r["detections"]:
        ax.axvspan(det["freq_lower_hz"] / 1e3, det["freq_upper_hz"] / 1e3, color=c["s2"], alpha=0.14, lw=0)
    ax.set_xlim(f[0], f[-1])
    ax.set_ylim(pw.min() - 3, pw.max() + 4)
    ax.set_xlabel("Baseband offset (kHz)")
    ax.set_ylabel("dB re 1 unit²/Hz")
    ax.grid(axis="y")
    ax.set_axisbelow(True)
    ax.spines["left"].set_visible(False)
    ax.tick_params(length=0)
    title(fig, "Welch PSD with the measured noise floor and threshold",
          "Shaded bands are the three detected candidates", c)
    save(fig, "demo-psd", theme)


# ---------------------------------------------------------------- readiness

def readiness_bars(theme, scoreboard):
    c = style(theme)
    phases = scoreboard["phases"]
    names = [p["name"] for p in phases]
    frac = np.array([p["passed"] / p["total"] for p in phases])
    y = np.arange(len(names))[::-1]

    fig, ax = plt.subplots(figsize=(9, 4.6))
    ax.barh(y, np.ones_like(frac), height=0.5, color=c["track"], lw=0)
    ax.barh(y, frac, height=0.5, color=c["s1"], lw=0)
    for yi, p, fr in zip(y, phases, frac):
        ax.text(1.02, yi, f"{p['passed']}/{p['total']}", va="center", fontsize=9, color=c["ink2"])
    ax.set_yticks(y, names, color=c["ink"])
    ax.set_xlim(0, 1.08)
    ax.set_xticks([0, 0.5, 1], ["0%", "50%", "100%"])
    ax.spines[["left", "bottom"]].set_visible(False)
    ax.tick_params(length=0)
    passed = sum(p["passed"] for p in phases)
    total = sum(p["total"] for p in phases)
    meta = scoreboard["meta"]
    title(fig, f"Readiness scoreboard · {passed}/{total} criteria pass",
          f"Fraction of pre-registered pass/fail criteria met per phase · verify estimator · commit {meta['commit']} ({meta['date']})", c)
    save(fig, "readiness", theme)


def estimator_compare(theme, scoreboard):
    c = style(theme)
    stats = scoreboard["stats"]
    th = scoreboard["meta"]["thresholds"]
    panels = [
        ("Label published correct", "label", "published_correct_in_library", th["label_correct_min"], "≥"),
        ("Label published wrong", "label", "published_wrong", th["label_wrong_max"], "≤"),
        ("Rate published correct", "rate", "published_correct_digital", th["rate_correct_min"], "≥"),
        ("Rate published wrong", "rate", "published_wrong", th["rate_wrong_max"], "≤"),
    ]
    gens = ["G1", "G2"]
    fig, axes = plt.subplots(1, 4, figsize=(10, 3.3), sharey=False)
    w = 0.34
    for ax, (name, group, key, limit, sense) in zip(axes, panels):
        top = 0
        for i, (system, color, lab) in enumerate((("verify", c["s1"], "verify"), ("shipped", c["s2"], "legacy"))):
            vals = [stats[system][g][group][key] for g in gens]
            xs = np.arange(len(gens)) + (i - 0.5) * (w + 0.04)
            ax.bar(xs, vals, width=w, color=color, lw=0, label=lab)
            for x, v in zip(xs, vals):
                ax.annotate(f"{v:.0%}", (x, v), xytext=(0, 3), textcoords="offset points",
                            ha="center", va="bottom", fontsize=7.5, color=c["ink2"])
            top = max(top, max(vals))
        ax.axhline(limit, color=c["ink"], lw=0.9)
        ax.set_xticks(range(len(gens)), gens)
        ax.set_xlim(-0.6, 1.6)
        ax.set_ylim(0, max(top, limit) * 1.3)
        ax.yaxis.set_major_locator(MaxNLocator(4, steps=[1, 2, 5, 10]))
        ax.yaxis.set_major_formatter(PercentFormatter(1.0, decimals=0))
        ax.set_title(f"{name}\ntarget {sense}{limit:.0%}", fontsize=9, color=c["ink"], loc="left", pad=10)
        ax.spines["left"].set_visible(False)
        ax.tick_params(length=0)
        ax.grid(axis="y")
        ax.set_axisbelow(True)
    axes[0].legend(frameon=False, loc="upper left", bbox_to_anchor=(0, -0.12), ncol=2, fontsize=8.5)
    fig.subplots_adjust(wspace=0.35)
    title(fig, "Propose → verify (MDL) estimator vs the legacy heuristics",
          "Held-out synthetic corpora G1 (spike) and G2 (widened fixtures) · horizontal rule = pass threshold", c)
    save(fig, "estimator-compare", theme)


def main():
    capture, result = demo_result()
    scoreboard = json.loads((ROOT / "docs/readiness.json").read_text())
    for theme in THEMES:
        waterfall(theme, capture, result)
        psd(theme, capture, result)
        readiness_bars(theme, scoreboard)
        estimator_compare(theme, scoreboard)
    print(f"wrote {len(list(OUT.glob('*-*.*')))} figures to {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
