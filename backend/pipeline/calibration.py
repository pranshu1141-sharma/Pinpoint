"""Calibration utilities for Detect's two uncalibrated confidence scores
(`confidence`, `confidence_evidence_based` in detect.py).

Both scores were designed as heuristics, not probabilities -- this module
measures how far from "calibrated" (a score of 0.8 should mean roughly 80%
of candidates at that score are real signals) they actually are on labeled
synthetic data, and provides isotonic regression to correct them where a
correction generalizes to held-out data.

No sklearn dependency: isotonic regression here is a from-scratch pool-
adjacent-violators (PAV) implementation, since the project has no other use
for scikit-learn and this is the only place that would need it.
"""
import numpy as np


def pool_adjacent_violators(x, y, weights=None):
    """Isotonic (non-decreasing) regression of y on x via PAV.

    Returns (x_sorted, y_fit): y_fit is non-decreasing in x_sorted order.
    Standard PAV: repeatedly merge adjacent blocks whose weighted means
    violate monotonicity, replacing each with its weighted mean, until none
    remain.
    """
    order = np.argsort(x)
    xs = np.asarray(x)[order]
    ys = np.asarray(y, dtype=np.float64)[order]
    w = np.ones_like(ys) if weights is None else np.asarray(weights, dtype=np.float64)[order]
    # Each block: (weighted_sum, weight, start_index, end_index_exclusive)
    blocks = [[ys[i] * w[i], w[i], i, i + 1] for i in range(len(ys))]
    i = 0
    while i < len(blocks) - 1:
        mean_i = blocks[i][0] / blocks[i][1]
        mean_next = blocks[i + 1][0] / blocks[i + 1][1]
        if mean_i > mean_next:
            merged = [blocks[i][0] + blocks[i + 1][0], blocks[i][1] + blocks[i + 1][1],
                      blocks[i][2], blocks[i + 1][3]]
            blocks[i:i + 2] = [merged]
            i = max(i - 1, 0)
        else:
            i += 1
    y_fit = np.empty_like(ys)
    for s, wgt, start, end in blocks:
        y_fit[start:end] = s / wgt
    return xs, y_fit


class IsotonicCalibrator:
    """Fits a monotone score -> empirical-frequency map via PAV, and
    interpolates it for new scores (step-interpolated between the fitted
    knots, clamped at the ends -- standard isotonic-calibration behavior)."""

    def __init__(self):
        self.x_knots = None
        self.y_knots = None

    def fit(self, scores, labels):
        x_sorted, y_fit = pool_adjacent_violators(np.asarray(scores, dtype=np.float64),
                                                   np.asarray(labels, dtype=np.float64))
        # Collapse duplicate x (ties) to their block's single value for interp.
        x_knots, idx = np.unique(x_sorted, return_index=True)
        self.x_knots = x_knots
        self.y_knots = y_fit[idx]
        return self

    def predict(self, scores):
        scores = np.asarray(scores, dtype=np.float64)
        return np.interp(scores, self.x_knots, self.y_knots,
                          left=self.y_knots[0], right=self.y_knots[-1])

    def to_json(self):
        return {"x_knots": self.x_knots.tolist(), "y_knots": self.y_knots.tolist()}

    @classmethod
    def from_json(cls, data):
        c = cls()
        c.x_knots = np.array(data["x_knots"], dtype=np.float64)
        c.y_knots = np.array(data["y_knots"], dtype=np.float64)
        return c


def reliability_diagram(scores, labels, n_bins=10):
    """Bucket (score, label) pairs into n_bins equal-width [0,1] bins.

    Returns a list of dicts, one per non-empty bin: bin_lower, bin_upper,
    mean_confidence (mean predicted score in the bin), empirical_accuracy
    (fraction of labels==1 in the bin), count.
    """
    scores = np.asarray(scores, dtype=np.float64)
    labels = np.asarray(labels, dtype=np.float64)
    edges = np.linspace(0, 1, n_bins + 1)
    rows = []
    for i in range(n_bins):
        lo, hi = edges[i], edges[i + 1]
        mask = (scores >= lo) & (scores < hi) if i < n_bins - 1 else (scores >= lo) & (scores <= hi)
        if not np.any(mask):
            continue
        rows.append({
            "bin_lower": float(lo), "bin_upper": float(hi),
            "mean_confidence": float(np.mean(scores[mask])),
            "empirical_accuracy": float(np.mean(labels[mask])),
            "count": int(np.sum(mask)),
        })
    return rows


def expected_calibration_error(scores, labels, n_bins=10):
    """Standard ECE: sum over bins of (bin_count/total) * |accuracy - confidence|."""
    rows = reliability_diagram(scores, labels, n_bins)
    total = len(scores)
    if total == 0 or not rows:
        return None
    return float(sum(r["count"] / total * abs(r["empirical_accuracy"] - r["mean_confidence"]) for r in rows))


def reliability_diagram_svg(rows, title, width=480, height=360):
    """A minimal, dependency-free SVG reliability diagram: the diagonal
    (perfect calibration) plus the measured (mean_confidence,
    empirical_accuracy) points sized by bin count."""
    pad = 50
    plot_w, plot_h = width - 2 * pad, height - 2 * pad

    def px(v):
        return pad + v * plot_w

    def py(v):
        return height - pad - v * plot_h

    max_count = max((r["count"] for r in rows), default=1)
    points = "".join(
        f'<circle cx="{px(r["mean_confidence"]):.1f}" cy="{py(r["empirical_accuracy"]):.1f}" '
        f'r="{3 + 7 * (r["count"] / max_count):.1f}" fill="#2563eb" fill-opacity="0.75" />'
        for r in rows)
    ticks = "".join(
        f'<text x="{px(t):.1f}" y="{height - pad + 16}" font-size="10" text-anchor="middle">{t:.1f}</text>'
        f'<text x="{pad - 8}" y="{py(t) + 3:.1f}" font-size="10" text-anchor="end">{t:.1f}</text>'
        for t in np.linspace(0, 1, 6))
    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" font-family="sans-serif">
  <rect width="{width}" height="{height}" fill="white" />
  <text x="{width/2}" y="20" font-size="13" text-anchor="middle" font-weight="bold">{title}</text>
  <line x1="{pad}" y1="{height-pad}" x2="{pad}" y2="{pad}" stroke="black" stroke-width="1" />
  <line x1="{pad}" y1="{height-pad}" x2="{width-pad}" y2="{height-pad}" stroke="black" stroke-width="1" />
  <line x1="{px(0):.1f}" y1="{py(0):.1f}" x2="{px(1):.1f}" y2="{py(1):.1f}" stroke="#999" stroke-dasharray="4,4" />
  {ticks}
  {points}
  <text x="{width/2}" y="{height-10}" font-size="11" text-anchor="middle">mean predicted confidence</text>
  <text x="14" y="{height/2}" font-size="11" text-anchor="middle" transform="rotate(-90 14 {height/2})">empirical accuracy</text>
</svg>'''
