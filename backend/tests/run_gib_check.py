"""Opt-in full 1 GiB HTTP integration check; never allocates the file in RAM."""
import argparse
import ctypes
from ctypes import wintypes
import json
from pathlib import Path
import tempfile
import time
import httpx
import numpy as np


def working_set(pid):
    class Counters(ctypes.Structure):
        _fields_=[("cb",wintypes.DWORD),("faults",wintypes.DWORD)]+[(name,ctypes.c_size_t) for name in
                   ("peak_working_set","working_set","peak_paged","paged","peak_nonpaged","nonpaged","pagefile","peak_pagefile")]
    kernel=ctypes.WinDLL("kernel32",use_last_error=True)
    kernel.OpenProcess.restype=wintypes.HANDLE
    kernel.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD]
    kernel.CloseHandle.argtypes=[wintypes.HANDLE]
    handle=kernel.OpenProcess(0x410,False,pid)
    if not handle:return {}
    info=Counters();info.cb=ctypes.sizeof(info)
    psapi=ctypes.WinDLL("psapi")
    psapi.GetProcessMemoryInfo.argtypes=[wintypes.HANDLE,ctypes.c_void_p,wintypes.DWORD]
    if not psapi.GetProcessMemoryInfo(handle,ctypes.byref(info),info.cb):
        raise ctypes.WinError(ctypes.get_last_error())
    kernel.CloseHandle(handle)
    return {"working_set_mib":info.working_set/1024**2,"peak_working_set_mib":info.peak_working_set/1024**2}


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--url",default="http://127.0.0.1:5173")
    parser.add_argument("--backend-pid",type=int,required=True)
    args=parser.parse_args()
    size=1024**3
    count=size//8
    fs=48000
    chunk=524288
    rng=np.random.default_rng(47)
    noise=((rng.standard_normal(chunk)+1j*rng.standard_normal(chunk))/np.sqrt(2)).astype("<c8")
    intervals=[(chunk-2400,chunk+2400),(count//2+10000,count//2+14800),(count-12000,count-7200)]
    began=time.monotonic()
    with tempfile.TemporaryDirectory(prefix="detect-gib-check-") as directory:
        path=Path(directory)/"full-gib.iq"
        with path.open("wb") as output:
            for i in range(count//chunk):
                part=noise.copy()
                for a,b in intervals:
                    lo,hi=max(a,i*chunk),min(b,(i+1)*chunk)
                    if hi>lo:
                        part[lo-i*chunk:hi-i*chunk]+=5*np.exp(2j*np.pi*8000*np.arange(hi-lo)/fs)
                output.write(part.tobytes())
        print(f"Generated {path.stat().st_size:,} bytes; uploading full file",flush=True)
        with httpx.Client(timeout=httpx.Timeout(600,connect=15)) as client, path.open("rb") as source:
            r=client.post(args.url+"/api/analyze",files={"file":(path.name,source,"application/octet-stream")},
                          data={"sample_rate":str(fs),"datatype":"cf32_le"})
        assert r.status_code==202,r.text
        job=r.json()["job_id"]
        peak=0
        with httpx.Client(timeout=60) as client:
            while True:
                state=client.get(args.url+f"/api/jobs/{job}").json()
                memory=working_set(args.backend_pid)
                peak=max(peak,memory.get("peak_working_set_mib",0))
                print(f"{state['status']}: {state.get('message')} | peak RSS {peak:.1f} MiB",flush=True)
                if state["status"] in ("failed","complete"):break
                time.sleep(5)
            assert state["status"]=="complete",state
            result=state["result"]
            assert state["processed_samples"]==count==result["metadata"]["sample_count"]
            detections=result["detections"]
            for a,b in intervals:
                assert any(d["freq_lower_hz"]<8000<d["freq_upper_hz"] and d["start_sample"]<=a+200 and d["end_sample"]>=b-200 for d in detections),(a,b,detections)
            spec=client.get(args.url+f"/api/spectrogram/{job}?width=64&height=32")
            assert spec.status_code==200
            assert len(spec.json()["magnitude_db"])==32
            tail=next(d for d in detections if d["end_sample"]>=intervals[-1][1]-200)
            layers=client.get(args.url+f"/api/detections/{job}/{tail['id']}/layers")
            assert layers.status_code==200,layers.text
            assert layers.json()[0]["sample_count"]<=1_000_000
            peak=max(peak,working_set(args.backend_pid).get("peak_working_set_mib",0))
        report={"file_bytes":size,"samples_scanned":count,"all_three_ground_truth_bursts_detected":True,
                "bursts_at_sample_ranges":intervals,"candidate_count":len(detections),
                "peak_backend_working_set_mib":peak,"wall_seconds":time.monotonic()-began,
                "analysis_ms":result["elapsed_ms"],"job_id":job,"spectrogram_verified":True,"tail_layers_verified":True}
        Path("backend/large-file-validation.json").write_text(json.dumps(report,indent=2))
        print(json.dumps(report,indent=2),flush=True)


if __name__=="__main__":main()
