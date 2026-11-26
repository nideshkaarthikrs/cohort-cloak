#!/usr/bin/env python3
"""Privacy/utility sweep: runs the pipeline under policy variants and scores each with the proxy
    25*(1-risk)*min(1, U/0.4) + 20*U     (risk from tools/attack_sim.py ratios, U from tools/eval_privacy.py + preserve)
Writes tools/sweep_results.csv and tools/sweep_results.md.  Usage:
    python tools/sweep.py --kit ../Secret-Wards-ToolKit [--stage all|loc|age|dx] [--base k=v,...]
"""
import argparse
import csv
import itertools
import json
import os
import re
import subprocess
import sys
import tempfile
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = sys.executable
DEFAULTS = {"village_mode": "district", "tehsil_mode": "keep", "pin_mode": "prefix3", "dob_mode": "shift",
            "age_band_years": 5, "rare_dx_max_patients": 3, "k_min": 3}


def norm(s):
    return " ".join(unicodedata.normalize("NFKC", s).casefold().split())


def run_policy(kit, policy, tag, secret="practice"):
    work = Path(tempfile.mkdtemp(prefix="sweep_", dir=ROOT / ".tmp_sweep" if (ROOT / ".tmp_sweep").exists() else None))
    pol = work / "policy.yaml"
    pol.write_text("\n".join(f"{k}: {v}" for k, v in policy.items()) + "\n")
    out = work / "out"
    env = dict(os.environ, RAKSHA_SECRET=secret, COHORT_POLICY=str(pol))
    subprocess.run([PY, str(ROOT / "main.py"), "--input", f"{kit}/dev/input", "--output", str(out)], env=env,
                   check=True, capture_output=True)
    return out


def preserve_share(kit, out):
    truth = json.loads(Path(f"{kit}/dev/truth/truth.json").read_text(encoding="utf-8"))
    rep = json.loads((out / "report.json").read_text(encoding="utf-8"))
    mapped = {e["input_sha256"]: (e.get("output") or "").replace("sanitized/", "", 1) for e in rep["files"]}
    ok = tot = 0
    for rel, f in truth["files"].items():
        o = mapped.get(f["sha256"])
        text = norm((out / "sanitized" / o).read_text(encoding="utf-8", errors="replace")) if o else ""
        for u in f["units"].values():
            for pv in u.get("preserve") or []:
                tot += 1
                ok += norm(pv["text"]) in text
    return ok / max(1, tot)


def score_run(kit, policy, tag):
    out = run_policy(kit, policy, tag)
    priv = subprocess.run([PY, str(ROOT / "tools/eval_privacy.py"), "--output", str(out), "--truth", f"{kit}/dev/truth/truth.json"],
                          capture_output=True, text=True, check=True).stdout
    m = dict(kv.split("=") for kv in re.search(r"METRICS (.*)", priv).group(1).split())
    att = subprocess.run([PY, str(ROOT / "tools/attack_sim.py"), "--kit", kit, "--release", str(out), "--raw-cache",
                          str(ROOT / ".tmp_sweep" / "raw_attack.json")], capture_output=True, text=True, check=True).stdout
    ratio = json.loads(re.search(r"ATTACK (.*)", att).group(1))["ratio"]
    clin = preserve_share(kit, out)
    temporal, gen, icd, los = float(m["temporal"]), float(m["generalization"]), float(m["icd_stat"]), float(m["los_exact"])
    stats = 0.5 * icd + 0.5 * los
    U = 0.35 * clin + 0.20 * temporal + 0.10 * gen + 0.15 * stats + 0.10 * 1.0 + 0.10 * 1.0
    risk = 0.2 * (ratio["A1"] + ratio["A3"] + ratio["A4"] + ratio["A5"])  # A6 = A7 = 0 by construction (HMAC, per-secret shifts)
    score = 25 * (1 - risk) * min(1, U / 0.4) + 20 * U
    row = dict(policy, clinical=round(clin, 4), temporal=round(temporal, 4), generalization=round(gen, 4), stats=round(stats, 4),
               U=round(U, 4), A1=round(ratio["A1"], 3), A3=round(ratio["A3"], 3), A4=round(ratio["A4"], 3),
               A5=round(ratio["A5"], 3), risk=round(risk, 4), proxy=round(score, 3))
    return row


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--kit", required=True)
    ap.add_argument("--stage", default="all")
    ap.add_argument("--base", default="")
    a = ap.parse_args()
    (ROOT / ".tmp_sweep").mkdir(exist_ok=True)
    base = dict(DEFAULTS)
    for kv in filter(None, a.base.split(",")):
        k, v = kv.split("=")
        base[k] = int(v) if v.lstrip("-").isdigit() else v
    rows = []

    def sweep(grid, current):
        best = None
        keys = sorted(grid)
        for combo in itertools.product(*(grid[k] for k in keys)):
            pol = dict(current, **dict(zip(keys, combo)))
            row = score_run(a.kit, pol, "x")
            rows.append(row)
            print(json.dumps({k: row[k] for k in keys + ["clinical", "temporal", "generalization", "U", "A3", "A4", "A5", "proxy"]}), flush=True)
            if best is None or row["proxy"] > best["proxy"]:
                best = row
        return {k: best[k] for k in DEFAULTS}

    cur = dict(base)
    if a.stage in ("all", "loc"):
        cur = sweep({"village_mode": ["tehsil", "district", "redact"], "tehsil_mode": ["keep", "district"],
                     "pin_mode": ["prefix3", "redact"], "dob_mode": ["shift", "year", "redact"]}, cur)
    if a.stage in ("all", "age"):
        cur = sweep({"age_band_years": [5, 10], "k_min": [0, 3, 5]}, cur)
    if a.stage in ("all", "dx"):
        cur = sweep({"rare_dx_max_patients": [0, 3, 5, 8, 12, 20]}, cur)
    best = max(rows, key=lambda r: r["proxy"])
    cols = list(rows[0])
    with open(ROOT / "tools/sweep_results.csv", "w", newline="") as f:
        w = csv.DictWriter(f, cols)
        w.writeheader()
        w.writerows(sorted(rows, key=lambda r: -r["proxy"]))
    with open(ROOT / "tools/sweep_results.md", "w") as f:
        f.write("| " + " | ".join(cols) + " |\n|" + "---|" * len(cols) + "\n")
        for r in sorted(rows, key=lambda r: -r["proxy"])[:15]:
            f.write("| " + " | ".join(str(r[c]) for c in cols) + " |\n")
    print("BEST", json.dumps({k: best[k] for k in DEFAULTS}), "proxy", best["proxy"])


if __name__ == "__main__":
    main()
