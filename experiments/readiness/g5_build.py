"""Build the G5 manifest (WP2): real captures with ground truth, split by protocol, frozen.

    python -m experiments.readiness.g5_build --work /tmp/g5work     # writes experiments/readiness/g5_manifest.json

Run once. Everything is pinned: rtl_433_tests and rtl_433 at fixed commits, IQEngine entries by path.

rtl_433_tests (github.com/merbanan/rtl_433_tests): each capture is `tests/<group>/<device>/<set>/*.cu8`,
8-bit unsigned interleaved IQ, named `<name>_<MHz>M_<kS/s>k.cu8`; its sibling `.json` holds rtl_433's
expected decodes (one JSON object per line, with a `model`). Ground truth comes from the device's
rtl_433 definition, the way the existing backend/data/real/*.rtl433-ground-truth.json files were made:
`model` -> the decoder source that emits it -> its `r_device` (`.modulation`, `.short_width`,
`.long_width`, microseconds). A directory is used only when that chain is unambiguous (every
definition its models reach has the same modulation and widths). OOK_* -> label ASK2 (2-level
unipolar ASK, off level allowed), FSK_* -> FSK2. A symbol rate is scored only where the definition
fixes one: NRZ PCM (short == long width: 1e6/short) and Manchester (short = half bit: 1e6/short is
the keying/chip rate). Pulse-width/position codings have no single rate and are not rate-scored.
One capture per decoder source (protocol): the first directory and first file in sorted order.

IQEngine entries: the curated public recordings whose modulation has a published source (listed with
it); OFDM recordings are negatives (no single-carrier library label is correct).

Split (frozen before any pipeline run): stratified by (source, OOK/FSK or positive/negative); within a
stratum protocols are sorted by sha256(protocol) and alternate test/calibration (test first). AIS is
forced to test because AIS channel A is already a G3 test recording.
"""
import argparse
import collections
import hashlib
import io
import json
import re
import tarfile
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

RTL_TESTS = "1aa8c29d6b9383739d1aeed495dbc5069b704392"      # merbanan/rtl_433_tests master, 2026-09-20
RTL_433 = "02cd4b69270cb27d4cb1a318d5a549fa8e848dc8"        # merbanan/rtl_433 master, 2026-09-26
OUT = Path(__file__).with_name("g5_manifest.json")
CODING = {"OOK_PULSE_PCM": "PCM", "FSK_PULSE_PCM": "PCM", "OOK_PULSE_RZ": "RZ",
          "OOK_PULSE_MANCHESTER_ZEROBIT": "Manchester", "FSK_PULSE_MANCHESTER_ZEROBIT": "Manchester",
          "OOK_PULSE_PWM": "PWM", "FSK_PULSE_PWM": "PWM", "OOK_PULSE_PPM": "PPM", "OOK_PULSE_DMC": "DMC",
          "OOK_PULSE_RZI": "RZI", "OOK_PULSE_NRZS": "NRZS", "OOK_PULSE_PIWM_DC": "PIWM"}
NAME = re.compile(r"_(\d+(?:\.\d+)?)M_(\d+(?:\.\d+)?)k\.cu8$")
RDEV = re.compile(r"r_device\s+(?:const\s+)?(\w+)\s*=\s*\{(.*?)\};", re.S)
FIELD = re.compile(r"\.(\w+)\s*=\s*([^,\n]+),")
FUNC = re.compile(r"^(?:static\s+)?(?:int|void|data_t\s*\*)\s+(\w+)\s*\(", re.M)
MODEL = re.compile(r'"model"\s*,\s*"[^"]*"\s*,\s*DATA_STRING\s*,\s*([^\n]*)')
ARITH = re.compile(r"^[\d.\s()+\-*/]+$")
FORCE_TEST = {"ais"}

IQENGINE = [
    # (protocol, IQEngine path, allowed labels, scored rate or None, what is known, source)
    ("meteor-m2-lrpt", "space/MeteorM2N_180501_17h52_after_resampler", ["QPSK"], 72000.0,
     "Meteor-M N2 LRPT downlink at 137.9 MHz: QPSK, 72 ksym/s",
     "LRPT QPSK at 72,000 sym/s (the symbol rate meteor_demod and SatDump use); recording by J.-M. Friedt (CC BY-SA)"),
    ("meteor-m2-lrpt", "space/MeteorM2_180502_14h12", ["QPSK"], 72000.0,
     "Meteor-M N2 LRPT downlink at 137.9 MHz: QPSK, 72 ksym/s",
     "LRPT QPSK at 72,000 sym/s (the symbol rate meteor_demod and SatDump use); recording by J.-M. Friedt (CC BY-SA)"),
    ("iss-sstv", "space/ISS_180412_sstv", ["FM"], None,
     "ISS SSTV event on 145.800 MHz: narrowband FM carrying SSTV audio",
     "ARISS SSTV events use 145.800 MHz FM; recording description by J.-M. Friedt (CC BY-SA)"),
    ("bluetooth", "bluetooth", ["FSK2"], 1.0e6,
     "Bluetooth BR / LE 1M bursts at 2.42 GHz: GFSK, 1 Msym/s",
     "Bluetooth Core Specification v5.3, Vol 2 Part A (BR: GFSK, BT 0.5, 1 Msym/s) and Vol 6 Part A (LE 1M PHY: "
     "GFSK, 1 Msym/s); recording by J. Gilbert (CC BY-SA)"),
    ("ais", "AIS-Collection-Fort-Smallwood-Pt1-162M025CF-240K0FS-20260730", ["FSK2"], 9600.0,
     "AIS channel B (162.025 MHz) bursts at the capture centre: GMSK, BT 0.4, 9,600 bit/s",
     "ITU-R M.1371-5 (GMSK, BT 0.4, 9,600 bit/s); recording by G. Schafer (CC BY 4.0)"),
    ("lte-dl", "cellular/rx-waveform-td-rec-0-2023_02_23-17_04_58_527", [], None,
     "LTE FDD downlink test model E-TM3.1, 20 MHz: OFDM",
     "3GPP TS 36.141 (E-TM3.1) and TS 36.211 (OFDM downlink); recording by A. Gaber (MIT licence)"),
    ("nr-dl", "cellular/rx-waveform-td-rec-0-2023_02_23-17_01_38_653", [], None,
     "5G NR FR1 downlink test model TM2, 10 MHz, 64-QAM subcarriers: OFDM",
     "3GPP TS 38.141 (NR-FR1-TM2) and TS 38.211 (OFDM); recording by A. Gaber (MIT licence)"),
    ("wifi-ofdm", "northeastern/WiFi_Day_1_meb_s4", [], None,
     "Wi-Fi transmission on the POWDER testbed: OFDM", "IEEE 802.11 OFDM PHY; POWDER (University of Utah)"),
    ("lte-powder", "northeastern/4G_Day_1_bes_s1", [], None,
     "LTE transmission on the POWDER testbed: OFDM", "3GPP TS 36.211 (OFDM); POWDER (University of Utah)"),
    ("nr-powder", "northeastern/5G_Day_1_bes_s1", [], None,
     "5G NR transmission on the POWDER testbed: OFDM", "3GPP TS 38.211 (OFDM); POWDER (University of Utah)"),
    ("wifi-halow", "802.11ah WiFi HaLow/1mhz-mcs0-chan43", [], None,
     "802.11ah HaLow, 1 MHz channel, MCS0: OFDM", "IEEE 802.11ah-2016 S1G OFDM PHY; recording by S. Miller"),
]


def _get(url, tries=4):
    for i in range(tries):
        try:
            return urllib.request.urlopen(url, timeout=60).read()
        except OSError:
            if i == tries - 1:
                raise
            time.sleep(2 ** i)


def _num(v):
    v = v.split("//")[0].strip()
    return float(eval(v, {"__builtins__": {}}, {})) if ARITH.match(v) else v.strip('"')


def index_decoders(src: Path):
    """model string -> [(decoder file, [r_device structs reaching the model's emitting function])]."""
    index, devs = collections.defaultdict(list), {}
    for f in sorted((src / "src" / "devices").glob("*.c")):
        t = re.sub(r"/\*.*?\*/", lambda m: "\n" * m.group(0).count("\n"), f.read_text(errors="replace"), flags=re.S)
        t = re.sub(r"//[^\n]*", "", t)
        defs = [dict({k: _num(v) for k, v in FIELD.findall(body)}, struct=s) for s, body in RDEV.findall(t)]
        if not defs:
            continue
        devs[f.name] = defs
        funcs = [(m.start(), m.group(1)) for m in FUNC.finditer(t)]
        bodies = {name: t[pos:(funcs[i + 1][0] if i + 1 < len(funcs) else len(t))] for i, (pos, name) in enumerate(funcs)}

        def roots(fn, seen=()):
            out = {d["struct"] for d in defs if str(d.get("decode_fn", "")).lstrip("&") == fn}
            for caller, body in bodies.items():
                if caller != fn and caller not in seen and re.search(r"\b%s\s*\(" % re.escape(fn), body):
                    out |= roots(caller, seen + (fn,))
            return out
        for m in MODEL.finditer(t):
            encl = [name for pos, name in funcs if pos < m.start()]
            structs = sorted(roots(encl[-1])) if encl else []
            for s in re.findall(r'"([^"]+)"', m.group(1)):
                index[s].append((f.name, structs))
    return index, devs


def rtl433_entries(work: Path):
    work.mkdir(parents=True, exist_ok=True)
    tree = json.loads(_get(f"https://api.github.com/repos/merbanan/rtl_433_tests/git/trees/{RTL_TESTS}?recursive=1"))
    blobs = {x["path"]: x.get("size", 0) for x in tree["tree"] if x["type"] == "blob"}
    dirs = collections.defaultdict(list)
    for p, s in blobs.items():
        if p.startswith("tests/") and p.endswith(".cu8") and p[:-4] + ".json" in blobs and NAME.search(p):
            dirs[p.rsplit("/", 1)[0]].append((p, s))
    firsts = {d: sorted(v)[0] for d, v in dirs.items()}

    def fetch(p):
        out = work / "json" / p
        if not out.exists():
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(_get(f"https://raw.githubusercontent.com/merbanan/rtl_433_tests/{RTL_TESTS}/"
                                 + urllib.parse.quote(p)))
        return out
    with ThreadPoolExecutor(16) as ex:
        jpaths = dict(zip(firsts, ex.map(fetch, [p[:-4] + ".json" for p, _ in firsts.values()])))
    src = work / "rtl_433"
    if not src.exists():
        with tarfile.open(fileobj=io.BytesIO(_get(f"https://codeload.github.com/merbanan/rtl_433/tar.gz/{RTL_433}"))) as tf:
            tf.extractall(work / "rtl_433_tar", filter="data")
        next((work / "rtl_433_tar").iterdir()).rename(src)
    index, devs = index_decoders(src)
    resolved = {}
    for d in sorted(dirs):
        models = set()
        for line in jpaths[d].read_text().splitlines():
            if line.strip().startswith("{"):
                try:
                    models.add(json.loads(line).get("model"))
                except json.JSONDecodeError:
                    pass
        models.discard(None)
        if not models or any(m not in index for m in models):
            continue
        cands = {(f, s) for m in models for f, structs in index[m] for s in (structs or [x["struct"] for x in devs[f]])}
        defs = [next(x for x in devs[f] if x["struct"] == s) for f, s in cands]
        sig = {(x.get("modulation"), x.get("short_width"), x.get("long_width")) for x in defs}
        if len(sig) != 1:
            continue
        mod, sw, lw = sig.pop()
        if not isinstance(sw, float) or mod not in CODING:
            continue
        resolved[d] = dict(models=sorted(models), decoder="+".join(sorted({f for f, _ in cands})),
                           structs=sorted({s for _, s in cands}), mod=mod, short=sw, long=lw, first=firsts[d])
    groups = collections.defaultdict(list)
    for d, v in resolved.items():
        groups[v["decoder"]].append(d)
    entries = []
    for proto, ds in sorted(groups.items()):
        v = resolved[sorted(ds)[0]]
        path, size = v["first"]
        m = NAME.search(path)
        coding = CODING[v["mod"]]
        scored = (coding == "PCM" and v["short"] == v["long"]) or coding == "Manchester"
        family = "OOK" if v["mod"].startswith("OOK") else "FSK"
        label = "ASK2" if family == "OOK" else "FSK2"
        stem = re.sub(r"[^A-Za-z0-9]+", "_", path[len("tests/"):-len(".cu8")]).strip("_")
        entries.append(dict(
            id=f"rtl433_{stem}", source="rtl_433_tests", protocol=proto, stratum=f"rtl433-{family}",
            url=f"https://raw.githubusercontent.com/merbanan/rtl_433_tests/{RTL_TESTS}/{urllib.parse.quote(path)}",
            path=path, datatype="cu8", sample_rate=float(m.group(2)) * 1e3, center_frequency=float(m.group(1)) * 1e6,
            bytes=size, allowed_labels=[label], expected_rate_hz=1e6 / v["short"] if scored else None,
            truth=dict(label=label, keying=v["mod"], coding=coding, short_width_us=v["short"], long_width_us=v["long"],
                       rate_rule=("1e6 / short_width (NRZ PCM bit period)" if coding == "PCM" and scored else
                                  "1e6 / short_width (Manchester half bit: the keying rate)" if scored else
                                  f"not scored: {coding} coding has no single symbol rate"),
                       source=f"rtl_433 @{RTL_433[:12]} src/devices/{proto}: r_device {', '.join(v['structs'])}",
                       models=v["models"])))
    return entries


def iqengine_entries():
    out = []
    for proto, path, allowed, rate, known, source in IQENGINE:
        stem = re.sub(r"[^A-Za-z0-9]+", "_", path).strip("_")
        out.append(dict(
            id=f"iqe_{stem}", source="IQEngine", protocol=proto, stratum="iqe-" + ("positive" if allowed else "negative"),
            url="https://iqengine.org/api/datasources/local/local/" + urllib.parse.quote(path), path=path,
            truncate_bytes=16_000_000, allowed_labels=allowed, expected_rate_hz=rate,
            truth=dict(label=allowed[0] if allowed else None, known=known, source=source)))
    return out


def _h(s):
    return hashlib.sha256(s.encode()).hexdigest()


def split(entries):
    strata = collections.defaultdict(set)
    for e in entries:
        strata[e["stratum"]].add(e["protocol"])
    side = {}
    for protos in strata.values():
        for i, p in enumerate(sorted((p for p in protos if p not in FORCE_TEST), key=_h)):
            side[p] = "test" if i % 2 == 0 else "calibration"
        side.update({p: "test" for p in protos & FORCE_TEST})
    for e in entries:
        e["split"] = side[e["protocol"]]
    return entries


def split_digest(entries) -> str:
    """sha256 of the sorted (id, split) pairs: config.G5_SPLIT_SHA256 freezes it."""
    return _h(json.dumps(sorted((e["id"], e["split"]) for e in entries)))


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", type=Path, required=True)
    args = ap.parse_args(argv)
    entries = split(sorted(rtl433_entries(args.work) + iqengine_entries(), key=lambda e: e["id"]))
    blob = dict(_about=__doc__.split("\n\n", 1)[1].strip(), rtl_433_tests_commit=RTL_TESTS, rtl_433_commit=RTL_433,
                split_sha256=split_digest(entries), recordings=entries)
    OUT.write_text(json.dumps(blob, indent=1) + "\n")
    print(collections.Counter((e["stratum"], e["split"]) for e in entries), blob["split_sha256"])


if __name__ == "__main__":
    main()
