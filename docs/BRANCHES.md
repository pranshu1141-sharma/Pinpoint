# Branches and archived experiments

PinPoint was built as a sequence of numbered work packages, each on its own branch. Once a branch is merged into `main`, its full history lives in `main`; the branch name is then only a bookmark. To keep the branch list short without losing those bookmarks, every merged branch is replaced by an **`archive/<branch>` tag at its exact tip**.

```bash
git fetch --tags
git checkout archive/fix/wp3b-ask-fsk                          # inspect an old experiment
git switch -c wp3b-revisit archive/fix/wp3b-ask-fsk            # continue from it
git push origin archive/fix/wp3b-ask-fsk:refs/heads/fix/wp3b-ask-fsk   # restore the branch itself
```

`scripts/compress-branches.sh` performs the archiving (dry run by default, `--apply` to execute). It only touches branches that are fully contained in `main`, and pushes every tag before deleting any branch. Pull-request heads (`refs/pull/N/head`) are kept by GitHub regardless.

## Active branches

| Branch | Status |
|---|---|
| `main` | Default branch, release tag `v0.1.0-beta.1`. |
| `readiness/wp3b-merge` | Open PR #5: bounds criteria B1–B3, impairment ablation, X1 timing tolerance (2 commits ahead of `main`). |
| `readiness/detect-bounds` | Open PR #6, stacked on #5: occupied-bandwidth Detect bounds (5 commits ahead of `main`, includes #5). |

## Archived branches (all merged into `main`)

| Branch | Tip | Date | Last commit |
|---|---|---|---|
| `devariwala2712-push-completed-core-items` | `cad5801` | 2026-09-12 | Complete stage 5 |
| `docs/readiness-status` | `f942f41` | 2026-09-26 | Bring README, PROJECT_STATUS and a new CLAIMS table in line with measured readin |
| `docs/wp10-honesty` | `c43ffb1` | 2026-09-26 | Document measured open issues and mark legacy-estimator docs as such (WP10) |
| `feat/decode-endpoint` | `b4bf598` | 2026-10-23 | refactor(frontend): split App.tsx into app/ hooks and components; run frontend C |
| `feat/decode-track` | `2063ae3` | 2026-09-30 | decode: D1 -- 2-FSK/GMSK (discriminator) and OOK/ASK2 bit decoding |
| `feat/estimate-spike` | `3c63def` | 2026-09-27 | Label the fresh-seed confirmation scoreboard as such and explain its Docs row |
| `fix/final-review` | `3c63def` | 2026-09-27 | Label the fresh-seed confirmation scoreboard as such and explain its Docs row |
| `fix/wp0-readiness-scoreboard` | `2e8497a` | 2026-09-26 | Add readiness scoreboard with cross-generator matrix (WP0) |
| `fix/wp1-carrier-aliasing` | `08f9fab` | 2026-09-26 | Take the spike's coarse carrier from the occupied band, not the 4th power (WP1) |
| `fix/wp2-pulse-shapes` | `684e527` | 2026-09-26 | Add a least-squares pulse expert with decision-directed rate refinement (WP2) |
| `fix/wp3-library-fm-sink` | `130d269` | 2026-09-26 | Add 8PSK and 4-FSK to the verify library and gate FM behind a discrete-IF probe  |
| `fix/wp3b-ask-fsk` | `f02b3f1` | 2026-09-26 | Add unipolar ASK, fix 4-FSK timing and harmonic rates, gate FM on its digital ma |
| `fix/wp4-integrate-verify` | `17d3c6e` | 2026-09-26 | Make the verify estimator the product default for label and symbol rate (WP4) |
| `fix/wp5-parameters` | `e5408b8` | 2026-09-26 | Fix bandwidth collapse, SNR bias and centre-frequency refinement (WP5) |
| `fix/wp6-fragmentation` | `6493c2a` | 2026-09-26 | Merge fragments of one signal into one Detect candidate (WP6) |
| `fix/wp7-real-data` | `5afebd9` | 2026-09-26 | Run the pipeline on six public SigMF recordings and report every outcome (WP7) |
| `fix/wp8-speed` | `7db82e4` | 2026-09-26 | Cut verify latency to ~0.33 s per candidate and time it sequentially (WP8) |
| `fix/wp9-batch-cli` | `4bcf47a` | 2026-09-26 | Add an offline batch CLI: python -m backend.cli analyze (WP9) |
| `wp1-quick-wins` | `db4b0c9` | 2026-09-28 | Estimate over-long large-capture tracks from sampled spans; fix modulation claim |
| `wp2-benchmarks` | `8673551` | 2026-09-29 | Add G4 impaired generator, G5 real benchmark and throughput to the scoreboard (W |
| `wp3-diagnosis` | `fdd92e2` | 2026-09-29 | Diagnose why the product abstains on real, impaired and pulsed captures (WP3) |
