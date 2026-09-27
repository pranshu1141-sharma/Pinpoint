"""Text progress bars for docs/READINESS.md."""

MARK = {True: "✓", False: "✗", None: "–"}


def render_bar(name: str, passed: int, total: int, gens: dict, width: int = 22, blocks: int = 10) -> str:
    """`Modulation label   ████░░░░░░  40%  (2/5 criteria)  [G1 ✓ G2 ✗ G3 –]`."""
    frac = passed / total if total else 0.0
    full = int(frac * blocks + 1e-9)
    bar = "█" * full + "░" * (blocks - full)
    marks = " ".join(f"{g} {MARK[v]}" for g, v in gens.items())
    return f"{name.ljust(width)}{bar}  {int(round(100 * frac)):>2}%  ({passed}/{total} criteria)  [{marks}]"
