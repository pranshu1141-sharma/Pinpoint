#### Raw best-hypothesis accuracy (all captures, no abstention)

| Kind | n | Label right | ref | Rate right | ref |
|---|---|---|---|---|---|
| PSK | 163 | 70.6% | 70.6% | 65.0% | 65.0% |
| QAM16 | 61 | 65.6% | 65.6% | 65.6% | 65.6% |
| FSK2 | 78 | 61.5% | 56.4% | 47.4% | 50.0% |
| AM | 54 | 38.9% | 38.9% | n/a | n/a |
| FM | 49 | 51.0% | 51.0% | n/a | n/a |
| 8PSK | 47 | 0.0% | 0.0% | 59.6% | 59.6% |
| noise | 48 | 97.9% | 97.9% | n/a | n/a |

#### Raw rate accuracy by SNR (ours / ref)

| | -6..-1 dB | -1..4 dB | 4..9 dB | 9..14 dB |
|---|---|---|---|---|
| PSK | 20.8% / 20.8% (n=53) | 81.6% / 81.6% (n=38) | 85.3% / 85.3% (n=34) | 92.1% / 92.1% (n=38) |
| QAM16 | 11.8% / 11.8% (n=17) | 72.7% / 72.7% (n=11) | 92.3% / 92.3% (n=13) | 90.0% / 90.0% (n=20) |
| FSK2 | 0.0% / 0.0% (n=21) | 15.4% / 15.4% (n=13) | 87.5% / 87.5% (n=24) | 70.0% / 80.0% (n=20) |

#### Held-out decisions (test half, n=277); thresholds from calibration half: m_fam ≥ 0.411, m_rate ≥ 0.149, unexplained ≤ 0.097 (ref 0.411 / 0.149 / 0.097)

| Kind | n | Label shipped | Label right | Unknown-family | Rate shipped | Rate right | Confidently wrong |
|---|---|---|---|---|---|---|---|
| PSK | 94 (94) | 50% (50%) | 100% (100%) | 7% (7%) | 36% (36%) | 100% (100%) | 0 (0) |
| QAM16 | 34 (34) | 47% (47%) | 100% (100%) | 6% (6%) | 53% (53%) | 100% (100%) | 0 (0) |
| FSK2 | 42 (42) | 26% (26%) | 100% (100%) | 2% (2%) | 50% (57%) | 95% (92%) | 1 (2) |
| AM | 31 (31) | 6% (6%) | 50% (50%) | 3% (3%) | 3% (3%) | 0% (0%) | 2 (2) |
| FM | 26 (26) | 38% (38%) | 100% (100%) | 0% (0%) | 0% (0%) | n/a (n/a) | 0 (0) |
| 8PSK | 21 (21) | 19% (19%) | 0% (0%) | 5% (5%) | 29% (29%) | 100% (100%) | 4 (4) |
| noise | 29 (29) | 0% (0%) | n/a (n/a) | 0% (0%) | 0% (0%) | n/a (n/a) | 0 (0) |

Total confidently wrong: **7/277** (ref 8/277). Reference values in parentheses.

#### Proposal recall (true rate within 2% of some proposal): ours / ref

| | ≥ 4 dB | −1..4 dB | < −1 dB |
|---|---|---|---|
| PSK/QAM gap-difference | 100% / 100% (n=105) | 100% / 96% (n=49) | 74% / 81% (n=70) |
| PSK/QAM old E1/E2 | 96% / 93% (n=105) | 61% / 62% (n=49) | 9% / 8% (n=70) |
| PSK/QAM finalists (after ranking + needle) | 92% / n/a (n=105) | 84% / n/a (n=49) | 19% / n/a (n=70) |
| FSK gap-difference | 100% / 98% (n=44) | 46% / 14–16% (n=13) | 19% / 4% (n=21) |
| FSK old E4 | 0% / 7% (n=44) | 0% / 0% (n=13) | 5% / 0% (n=21) |
| FSK finalists (after Fisher ranking) | 98% / n/a (n=44) | 23% / n/a (n=13) | 0% / n/a (n=21) |

#### Ablations (test half)

| Variant | Confidently wrong | ref | Raw label acc (test half) | ref |
|---|---|---|---|---|
| full system | 7/277 | 8/277 | 59.6% | 59.6% |
| without rrc | 22/277 | 15/277 | 61.4% | 61.4% |
| without fsk | 2/277 | 2/277 | 49.5% | 49.5% |
| without analog | 4/277 | 3/277 | 52.3% | 52.3% |
| without null | 10/277 | 11/277 | 50.5% | n/a |

#### Router (depth-4 tree on the 6 features, trained on calibration half)

| Mode | Mean time / capture | ref | Same answer as dense | ref | Raw label acc | ref | Confidently wrong | ref |
|---|---|---|---|---|---|---|---|---|
| dense | 146 ms | 177 ms | n/a | n/a | 59.6% | 59.6% | 7/277 | 8/277 |
| top-1 | 40 ms | 52 ms | 59.9% | 57.4% | 53.4% | 51.3% | 4/277 | 1/277 |
| top-2 | 55 ms | 80 ms | 85.9% | 83.8% | 56.0% | 59.6% | 4/277 | 1/277 |

#### Per-stage timing (all captures, one core)

| Stage | mean ms | p50 ms | p95 ms | max ms |
|---|---|---|---|---|
| features | 0.4 | 0.4 | 0.5 | 0.6 |
| screen_psk | 6.4 | 6.4 | 7.0 | 7.4 |
| screen_fsk | 5.9 | 5.9 | 7.0 | 7.7 |
| needle_fsk | 0.0 | 0.0 | 0.0 | 0.0 |
| nrz | 5.5 | 5.1 | 7.4 | 8.2 |
| rrc | 48.2 | 51.3 | 53.6 | 58.6 |
| fsk | 78.0 | 77.9 | 80.6 | 83.9 |
| analog | 1.6 | 1.6 | 1.7 | 1.9 |
| total | 146.7 | 149.9 | 154.3 | 160.1 |

Captures over the 0.5 s budget: 0/500.
