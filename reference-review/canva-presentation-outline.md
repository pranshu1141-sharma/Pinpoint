PRESENTATION BRIEF
Title: Automated IQ & WAV Signal Analysis
Purpose: SIH26147 internal college round, 12 September 2026. NTRO, software category. Faculty/industry jury at Thapar Institute of Engineering & Technology, AISHE U-0385.
14 slides, 16:9. Follow this exact section order from the supplied Innovate_2025_Hackathon_Template. The instruction slide is excluded and old 2025 date removed.
Visual direction: warm white backgrounds, dark navy text, muted teal and green accents, colored header bars, small icon badges, two-column content layouts, strong readable typography. One large diagram or figure on each technical slide. Use the supplied sample decks' layout habits. Use much less text than the samples. No paragraphs in slide bodies, no decorative stock radio towers, no invented logos, no old team names.
Status: REVIEW DRAFT. Team name, team number, leader contact and exact official theme are pending. Confirmed roster: Dev Ariwala (leader, COPC), Shashvt Mishra (COE), Pranshu Sharma (COE), Shreya Gupta (COE), Paryag Kakkar (COE), Yashwalia (COE). All six are third year. Preserve supplied spellings; do not invent surname spacing. User confirms prototype ready, interpreted as the available working Detect prototype. Use unobtrusive 'Pending team details' text in relevant areas, not fabricated values or angle-bracket markers. Do not imply this is ready for submission.
Evidence precedence: Current workspace source and a fresh actual Detect run supersede stale prototype-status claims in the supplied planning brief. The implemented prototype is Detect with pulse timing and detection JSON/SigMF export. Full Estimate, modulation Classify, and comprehensive Report are planned. Basic export is already present; do not say no reporting/export exists. The local dashboard visualizes Detect evidence; the main proposed innovation is signal analysis.
The earlier brief's 1 MS/s / 150 kHz / 117x refinement / symbol-rate figures describe a separate reported experiment without run artifacts in this review. Do not present them as results of the current prototype. Do not mix those figures with the current 48 kHz demo.
Narrative: analyst's raw recording → parameter-extraction need → four-stage proposal → explainable uncertainty → working Detect implementation → actual synthetic evidence → next build scope.

SLIDE 1 — Automated IQ & WAV Signal Analysis
Goal: identify project and internal-round context.
Body:
- SIH26147 · NTRO · Software
- Internal college round · 12 September 2026
- Thapar Institute of Engineering & Technology
- AISHE U-0385
- Leader: Dev Ariwala (COPC)
- Shashvt Mishra, Pranshu Sharma, Shreya Gupta, Paryag Kakkar, Yashwalia (COE)
- All members: third year
- Team name / number / leader contact: pending
Visual: clear title left, simple IQ waveform-to-annotation motif right. Reserved compact roster area. No fabricated team names.
Speaker notes: This is the internal round deck. Confirm official theme and team details before submission.

SLIDE 2 — Background
Goal: establish the analyst and input.
Body:
- IQ: recorded complex baseband samples
- WAV: real audio or a recorded IQ pair
- End user: analyst performing first-pass triage
- Need: locate signals and inspect evidence
Visual: recording file → time-frequency map → analyst, three large illustrated nodes.
Speaker notes: Raw samples need sample rate and datatype metadata. Ambiguous stereo WAV requires explicit interpretation; a quadrature check is evidence, not proof. Real demodulated audio does not preserve every original RF parameter.

SLIDE 3 — Problem Statement
Goal: preserve problem text and requested parameter categories.
Body: "Automated model for analysis of .IQ and .wav files along with signal parameter extraction."
Six short labels: Frequency; Bandwidth; Modulation; Symbol rate; SNR; Pulse timing.
Visual: central IQ/WAV capture icon surrounded by six output labels.
Speaker notes: PS identifier and wording come from the supplied brief. Absolute RF frequency needs receiver tuning metadata; otherwise report baseband offsets. Outputs must declare what the recording supports.

SLIDE 4 — Objectives
Goal: four concrete project objectives.
Body:
- Detect candidate regions without known signal labels
- Extract frequency, bandwidth, SNR and timing
- Return “unclassified” when evidence is insufficient
- Export interoperable annotations and plots
Visual: four equal numbered blocks with one icon each. Small status tags: Detect demonstrated; remaining objectives staged.
Speaker notes: These are full-project objectives, not a claim that all phases work today. Validate quality separately for each output and across SNR conditions.

SLIDE 5 — Proposed Solution
Goal: make the four-stage architecture the visual centerpiece.
Body:
- DETECT — time/frequency regions
- ESTIMATE — physical parameters
- CLASSIFY — label or unclassified
- REPORT — annotations and plots
Visual: four large horizontal blocks connected by arrows. Detect in solid teal with 'Working prototype'. Other three in pale outlines with 'Planned'. Small solid branch from Detect to 'Detection JSON + SigMF export available'.
Speaker notes: The current end-to-end demo runs the detector and exports its detections. The full Estimate, modulation Classify, and comprehensive Report phases remain planned. The existing dashboard supports evidence inspection.

SLIDE 6 — Novelty and Show Stopper
Goal: lead with the proposed uncertainty behavior and accurately position existing tools.
Lead: “Unclassified” is a valid output.
Body:
- Proposed: evidence-linked labels and rejection
- Current: heuristic detection score + review flag
- Pulse timing stays visible
- SigMF annotations support interoperability
Visual: compact four-row capability comparison:
GNU Radio — composable DSP development toolkit.
MATLAB example — trained CNN for 11 predefined modulation classes.
IQEngine — recording analysis with extensible DSP plugins.
Our proposed pipeline — integrated extraction + explicit uncertainty.
Footer: Qualitative comparison; no head-to-head benchmark.
Speaker notes: Open-set classification is a design objective, not yet a validated feature. Detection confidence is heuristic, not a calibrated probability of a correct modulation label. Do not claim that competing platforms cannot be extended to implement equivalent capabilities.
Sources: https://www.gnuradio.org/about/ ; https://www.mathworks.com/help/comm/ug/modulation-classification-with-deep-learning.html ; https://iqengine.org/about

SLIDE 7 — Methodology
Goal: show the implemented flow, with future methods clearly separate.
Main flow: Metadata / WAV interpretation → Welch PSD noise estimate → adaptive threshold + STFT → candidate regions → envelope edges → pulse width / PRI.
Small parameters: 1,024-sample Hann window; 256-sample hop; default margin +8 dB.
Small planned strip: Estimate: frequency refinement, dual bandwidth, on/off SNR. Classify: envelope features, cumulants, PSK-specific Mth-power refinement. Symbol-rate estimator: evaluate harmonic rejection.
Visual: large two-row flowchart with solid implemented nodes and an outlined planned strip.
Speaker notes: Frequency-median noise estimation assumes limited occupied bandwidth and reasonably stationary noise. Thresholding is CFAR-style, not calibrated CFAR. Envelope smoothing limits timing resolution. Planned Mth-power methods assume particular PSK structures; hand-coded cumulant rules still require validation. Source: https://docs.scipy.org/doc/scipy/reference/generated/scipy.signal.welch.html

SLIDE 8 — Tech Stack used and Budget
Goal: connect tools to work and state incremental hardware cost.
Body:
- Python + NumPy + SciPy: signal processing
- SigMF: recording metadata and annotations
- FastAPI + React: local demo and inspection
- Matplotlib: presentation evidence plots
- Hardware budget: ₹0
Visual: four compact labeled tool groups and a large ₹0 budget block.
Speaker notes: Existing computer assumed; no SDR purchase required. Zero is the additional hardware budget, not an accounting claim that electricity or development time has no cost. Avoid listing scikit-learn as an implemented dependency.

SLIDE 9 — Deliverable / Expected Outcome
Goal: make prototype honesty explicit.
Two columns:
Working now:
- Detect pipeline on synthetic IQ/WAV
- Time/frequency candidate regions
- Pulse width and PRI
- Inspectable plots + JSON/SigMF export
Next build:
- Frequency, bandwidth and SNR estimation
- Modulation label or unclassified
- Symbol-rate reliability checks
- Comprehensive per-signal report
Bottom line: “Detect validated on synthetic fixtures; full Estimate, Classify and Report planned.”
Speaker notes: Current source and project-status documentation support this narrower status. The planning brief's stronger Detect + Estimate line is stale relative to the available repository. No field validation, co-channel separation, hopping tracking or angle-of-arrival estimation is claimed.

SLIDE 10 — Team Role
Goal: present a six-person assignment matrix without inventing people.
Visual: six-row matrix with columns Member, Branch, Year, Proposed responsibility:
1. Dev Ariwala (leader) | COPC | III | Integration and demo coordination
2. Shashvt Mishra | COE | III | Input formats and metadata
3. Pranshu Sharma | COE | III | Detection and pulse timing
4. Shreya Gupta | COE | III | Parameter estimation
5. Paryag Kakkar | COE | III | Classification and uncertainty
6. Yashwalia | COE | III | Validation and ground truth
Small label: Proposed allocation — confirm with team.
Speaker notes: The user supplied these six names and branches and confirmed all are third year. The responsibility assignments are proposed, not confirmed. Obtain leader contact, team name and team number. Do not reuse any member or mentor from the sample decks.

SLIDE 11 — Screenshot of the outcome — 1
Subtitle: Measured output vs known synthetic truth
Goal: use real measured evidence from a fresh current detector run.
Main table:
Metric | Measured | Truth
Candidate signal regions | 3 | 3
Pulse windows | 16 | 16
Median pulse width | 49.625 ms | 50.000 ms
Median PRI | 250.021 ms | 250.000 ms
Small setup strip: 48 kS/s complex IQ · 4-second mixed demo · BPSK + FM + pulsed synthetic components.
Separate small evidence card: Stored validation report: 12/12 continuous synthetic fixtures detected. BPSK/QPSK/FM at −5, 0, 10, 20 dB; one deterministic fixture per combination.
Footer: Synthetic fixtures only. Generator labels are ground truth, not predicted modulation classes.
Visual: large legible table occupying most of slide, narrow setup strip, one small validation card.
Speaker notes: Fresh run measured pulse width 2,382 samples and PRI 12,001 samples at 48,000 samples/second. Raw results are in reference-review/current-demo-results.json. The separate stored report is backend/validation-report.json, with one fixture per class/SNR combination; it does not establish a population accuracy rate or a low-SNR limit. Do not call 12/12 a general 100% classification result.

SLIDE 12 — Screenshot of the outcome — 2
Subtitle: Actual annotated spectrogram
Goal: show the real demo measurements visually.
Body:
- Three candidate regions
- Individual pulse windows outlined
- Frequency axis: baseband offset
Visual: insert the supplied actual-demo annotated spectrogram image as the dominant figure. Preserve its axes, colorbar and measured region boxes. Do not synthesize, redraw or invent a scientific plot if the asset is unavailable; leave a clearly labeled figure slot instead.
Caption: Fresh run of the current Detect pipeline on the bundled 4-second synthetic capture, 48 kS/s. Boxes mark detector output. Modulation classification is not implemented.
Speaker notes: The two continuous bands and upper pulsed band match the three planted components in demo.truth.json. Pulse windows are separate detections in time within the same band, not 16 distinct emitters. Source files: backend/data/demo/demo.sigmf-data and demo.sigmf-meta; image generated from current detector output.

SLIDE 13 — References
Goal: six readable references.
1. SigMF specification — metadata and annotations — https://sigmf.org/
2. SciPy signal.welch — PSD estimation — https://docs.scipy.org/doc/scipy/reference/generated/scipy.signal.welch.html
3. GNU Radio — DSP toolkit — https://www.gnuradio.org/about/
4. MathWorks — Modulation Classification with Deep Learning — https://www.mathworks.com/help/comm/ug/modulation-classification-with-deep-learning.html
5. IQEngine — recording analysis and plugins — https://iqengine.org/about
6. Team prototype evidence — backend/validation-report.json; reference-review/current-demo-results.json; demo.truth.json.
Visual: six short numbered references, aligned in two columns. Use readable short hyperlinks; no tiny URL walls.
Speaker notes: Public sources support methods and tool descriptions, not the team's measured performance. Current synthetic figures come from the local project artifacts. The official problem wording/date originate in the supplied project brief.

SLIDE 14 — Thank You
Body:
- Questions & live Detect demo
- Team and leader contact: pending
Visual: clean closing slide with small four-stage motif; Detect highlighted.
Speaker notes — likely jury questions:
Q1. What actually works today? A: File interpretation, signal-region detection, pulse timing, evidence inspection, detection JSON and SigMF export. Full parameter estimation and modulation classification remain planned.
Q2. Why should we trust the reported confidence? A: It is explicitly a heuristic detection score based on measured energy evidence, not a calibrated probability. Classification rejection is a future behavior that must be tested against unseen signals.
Q3. What do your accuracy figures prove? A: They show agreement with known synthetic truth under the stated fixtures. They do not establish field performance. Next validation must vary channels, noise, pulse shaping, signal mixtures and unseen captures.

FINAL AUTHORING CONSTRAINTS
Do not claim full pipeline completion, real-world validation, competitor performance improvements, classified modulation output, universal 0 dB detection limits, or a proven open-set classifier. Do not reuse old dates or team data. Do not insert fictitious screenshots or infer identities. The supplied template bans AI slide generation; this is an explicitly requested review draft and makes no claim of eligibility for submission. Keep this process note in speaker notes rather than repeated on slide bodies.
