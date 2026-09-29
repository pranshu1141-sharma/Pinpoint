"""WP: pyproject.toml exists, is valid, and declares the pinpoint console-script."""
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_pyproject_declares_pinpoint_entry_point_and_pinned_deps():
    data = tomllib.loads((ROOT / "pyproject.toml").read_text())
    assert data["project"]["scripts"]["pinpoint"] == "backend.pinpoint_cli:run"
    deps = data["project"]["dependencies"]
    assert "numpy>=2.2,<3" in deps
    assert "scipy>=1.15,<2" in deps
    assert "sigmf>=1.2,<2" in deps
    assert data["project"]["license"] == {"text": "MIT"}


def test_version_module_matches_pyproject_dynamic_source():
    from backend._version import __version__
    data = tomllib.loads((ROOT / "pyproject.toml").read_text())
    assert data["tool"]["setuptools"]["dynamic"]["version"]["attr"] == "backend._version.__version__"
    assert __version__  # non-empty string
