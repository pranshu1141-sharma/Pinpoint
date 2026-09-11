"""Create audible, reproducible WAV fixtures and verify actual Detect output."""
import json
from pathlib import Path
import zipfile
import numpy as np
from scipy.io import wavfile
from backend.pipeline.ingest import load_capture
from backend.pipeline.detect import analyze_capture


def main():
    output = Path(__file__).resolve().parents[1] / "test-audio"
    output.mkdir(exist_ok=True)
    fs, duration = 24000, 5
    t = np.arange(fs*duration)/fs
    rng = np.random.default_rng(26147)
    noise = lambda: rng.normal(0, .015, len(t))
    pulse = (t >= .25) & (((t-.25) % .5) < .1)
    burst = (t >= 2) & (t < 2.15)
    fixtures = [
        ("01-steady-tone.wav", .3*np.sin(2*np.pi*1200*t)+noise(),
         "A steady 1,200 Hz tone with light noise. Expect one continuous candidate band."),
        ("02-two-tones.wav", .22*np.sin(2*np.pi*700*t)+.22*np.sin(2*np.pi*3000*t)+noise(),
         "Two simultaneous tones at 700 and 3,000 Hz. Expect two separate candidate bands."),
        ("03-pulsed-tone.wav", .4*np.sin(2*np.pi*1800*t)*pulse+noise(),
         "Ten 1,800 Hz beeps. Pulse width 100 ms (2,400 samples); PRI 500 ms (12,000 samples). Expect a pulsed candidate."),
        ("04-short-burst.wav", .4*np.sin(2*np.pi*2400*t)*burst+noise(),
         "One 2,400 Hz beep from 2.000 to 2.150 seconds. Expect a localized burst with no PRI (only one pulse)."),
        ("05-noise-only.wav", noise(),
         "Only Gaussian noise. Expect no candidate at the default 8 dB adaptive margin."),
    ]
    results = []
    for name, x, description in fixtures:
        path = output/name
        # PCM16 is widely accepted by browsers/audio tools. Validation reopens
        # the saved bytes, so reported detections include quantization effects.
        wavfile.write(path, fs, np.round(np.clip(x, -.98, .98)*32767).astype(np.int16))
        capture = load_capture(name, path.read_bytes())
        response = analyze_capture(capture).response
        results.append({"filename":name,"description":description,"sample_rate_hz":fs,
                        "duration_seconds":duration,"detections":response["detections"]})
        print(name, json.dumps(response["detections"]), flush=True)
    assert [len(r["detections"]) for r in results] == [1, 2, 1, 1, 0]
    train = results[2]["detections"][0]
    assert train["is_pulsed"] and len(train["pulse_windows"]) == 10
    assert abs(train["pulse_width_samples"]-2400) < 150
    assert abs(train["pri_samples"]-12000) < 100
    assert results[3]["detections"][0]["pri_samples"] is None
    (output/"measured-results.json").write_text(json.dumps(results,indent=2),encoding="utf-8")
    text = ["# WAV test pack for Detect", "", "Five synthetic, mono PCM16 WAV files; each is 5 seconds at 24 kHz.",
            "These are real generated sound samples, not recordings or decoded RF content.", "",
            "Upload one WAV at a time in the dashboard. Leave WAV interpretation on automatic and adaptive margin at 8 dB.",
            "The WAV header supplies the sample rate. Start playback at a low volume; these contain test tones.", ""]
    for r in results:
        text += [f"## {r['filename']}", "", r["description"],
                 f"Validated saved-file result: {len(r['detections'])} candidate(s).", ""]
    text += ["See measured-results.json for real detector outputs. Regenerate with python -m backend.make_audio_test_pack."]
    (output/"README.md").write_text("\n".join(text),encoding="utf-8")
    with zipfile.ZipFile(output/"detect-wav-test-pack.zip","w",zipfile.ZIP_DEFLATED) as archive:
        for path in [*(output/name for name,_,_ in fixtures),output/"README.md",output/"measured-results.json"]:
            archive.write(path,path.name)


if __name__ == "__main__":
    main()
