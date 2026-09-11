# WAV test pack for Detect

Five synthetic, mono PCM16 WAV files; each is 5 seconds at 24 kHz.
These are real generated sound samples, not recordings or decoded RF content.

Upload one WAV at a time in the dashboard. Leave WAV interpretation on automatic and adaptive margin at 8 dB.
The WAV header supplies the sample rate. Start playback at a low volume; these contain test tones.

## 01-steady-tone.wav

A steady 1,200 Hz tone with light noise. Expect one continuous candidate band.
Validated saved-file result: 1 candidate(s).

## 02-two-tones.wav

Two simultaneous tones at 700 and 3,000 Hz. Expect two separate candidate bands.
Validated saved-file result: 2 candidate(s).

## 03-pulsed-tone.wav

Ten 1,800 Hz beeps. Pulse width 100 ms (2,400 samples); PRI 500 ms (12,000 samples). Expect a pulsed candidate.
Validated saved-file result: 1 candidate(s).

## 04-short-burst.wav

One 2,400 Hz beep from 2.000 to 2.150 seconds. Expect a localized burst with no PRI (only one pulse).
Validated saved-file result: 1 candidate(s).

## 05-noise-only.wav

Only Gaussian noise. Expect no candidate at the default 8 dB adaptive margin.
Validated saved-file result: 0 candidate(s).

See measured-results.json for real detector outputs. Regenerate with python -m backend.make_audio_test_pack.