import numpy as np
FAM = {"BPSK": "PSK", "QPSK": "PSK", "QAM16": "QAM16", "FSK2": "FSK", "AM": "AM", "FM": "FM", "none": "none"}
DIGITAL = ("nrz", "rrc", "fsk")

def decide(r, active=("nrz", "rrc", "fsk", "analog")):
    H = [h for h in r["hyps"] if h[0] in active or h[0] == "null"]
    sc = np.array([h[2] for h in H])
    b = int(np.argmin(sc)); best = H[b]
    fam = FAM[best[3]]
    null = [h[2] for h in H if h[0] == "null"][0]
    other_fam = [h[2] for h in H if FAM[h[3]] != fam]
    m_fam = (min(other_fam) - best[2]) if other_fam else 0.0
    m_null = null - best[2]
    m_rate = np.nan
    if best[0] in DIGITAL:
        alt = [h[2] for h in H if h[0] in DIGITAL and abs(h[1] - best[1]) / best[1] >= 0.05]
        m_rate = (min(alt) - best[2]) if alt else 0.0
    nv, p = r["noise_var"], r["ptot"]
    unexpl = max(best[4] - nv, 0) / max(p - nv, 1e-12) if fam != "none" else np.nan
    return dict(fam=fam, label=best[3], rate=best[1], expert=best[0],
                m_fam=m_fam, m_null=m_null, m_rate=m_rate, unexpl=unexpl)

def truth_ok(r, d):
    fam_ok = d["fam"] == r["fam"]
    label_ok = fam_ok and (r["fam"] != "PSK" or d["label"] == r["label"])
    rate_ok = r["Rs"] is not None and d["rate"] is not None and abs(d["rate"] - r["Rs"]) / r["Rs"] < 0.05
    return fam_ok, label_ok, rate_ok
