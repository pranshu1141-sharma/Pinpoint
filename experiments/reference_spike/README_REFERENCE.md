# Reference spike code (THROWAWAY — read, don't copy-paste into the product)

These files are the exploratory code that produced the numbers in CLAUDE_CODE_TASK.md.
They run (python 3, numpy, scipy, scikit-learn) but are hacky: global N=4096 and FS=1 MHz,
chained imports, leftover code from earlier versions.

Import chain: spike5.py -> spike4.py -> spike3.py
- spike3.py : RRC pulse, M-th power frequency estimate, rrc expert (mdl_rrc), _quantize (BPSK/QPSK/16-QAM),
              plus older v3 code that is no longer used (group vote, meta-verifier, bootstrap).
- spike4.py : test-signal generator gen() for all 7 kinds, features(), nrz_expert, fsk_expert,
              analog_expert, fine_search. Its own analyze() (grid-based v4) is superseded.
- spike5.py : the v5 pipeline analyze() = gap-difference proposals -> ranking -> finalists -> experts.
- decide4.py: decision rule (best hypothesis, margins, unexplained fraction) + truth checks.
- evaluate4.py: evaluation tables, ablations, router test.

Reproduce:  python spike5.py 500 4 && python evaluate4.py rows5_4.json   (~90 s + a few s)
