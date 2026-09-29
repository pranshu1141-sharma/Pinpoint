# Baseline at f73a69f (origin/main, 2026-09-28)

Recorded before any of the real-recordings work packages (WP1 onward), with unchanged code and thresholds:

- `python -m experiments.readiness.real` (G3 re-run; `real_results.json`), then
- `python -m experiments.readiness.scoreboard --out docs/baselines/f73a69f` (`READINESS.md`, `readiness.json`),
- `python -m pytest backend/tests -q`: **380 passed, 3 skipped** (4 min 43 s).

Every deterministic number equals the committed `docs/READINESS.md` of 2eb056e. Two differences, both wall-clock:
S1 on G2 measured 89.2% (88.8% committed), and so X1 (docs agreement) fails here, because CLAIMS.md and
LIMITATIONS_AND_ROADMAP.md quote the timing-dependent 88.8%. A `--sync-docs` run rewrites those markers.
