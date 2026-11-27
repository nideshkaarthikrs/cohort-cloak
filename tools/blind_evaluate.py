"""Score a frozen independently authored corpus without changing its generator or answers."""
import argparse
from collections import Counter,defaultdict
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys


def relative(value):
    value=value.replace("\\","/")
    return value[6:] if value.startswith("input/") else value


def main():
    ap=argparse.ArgumentParser();ap.add_argument("--split",type=Path,required=True);ap.add_argument("--out",type=Path,required=True);args=ap.parse_args()
    split=args.split.resolve();out=args.out.resolve()
    if out.exists() and any(out.iterdir()):ap.error("Use an empty output directory to preserve previous results")
    out.mkdir(parents=True,exist_ok=True)
    manifest=json.loads((split/"manifest.json").read_text(encoding="utf-8"));files={relative(x["file"]):x for x in manifest["files"]}
    for name,meta in files.items():
        assert hashlib.sha256((split/"input"/name).read_bytes()).hexdigest()==meta["sha256"]
    env={k:v for k,v in os.environ.items() if k!="COHORT_POLICY"};env.setdefault("RAKSHA_SECRET","practice");env["PYTHONUTF8"]="1"
    root=Path(__file__).resolve().parent.parent
    run=subprocess.run([sys.executable,str(root/"main.py"),"--input",str(split/"input"),"--output",str(out/"release")],env=env,capture_output=True,text=True,encoding="utf-8",timeout=900)
    (out/"run.txt").write_text(run.stdout+run.stderr,encoding="utf-8");assert run.returncode==0
    report=json.loads((out/"release/report.json").read_text(encoding="utf-8"));mapping={}
    for entry in report["files"]:
        if entry["status"]=="sanitized":mapping[entry["input_sha256"]]=entry["output"]
    truth=json.loads((split/"truth.json").read_text(encoding="utf-8"));leaks=[];missing=[];counts=Counter();by_file=defaultdict(Counter)
    for section in ["pii","medical"]:
        for entry in truth[section]:
            name=relative(entry["file"]);meta=files[name];raw=(split/"input"/name).read_bytes();assert entry["value"] in raw.decode(meta["encoding"])
            dest=mapping.get(meta["sha256"]);text=(out/"release"/dest).read_text(encoding="utf-8") if dest else ""
            hit=entry["value"] in text or (section=="pii" and bool(dest) and entry["value"] in dest)
            if section=="pii":
                counts["pii_total"]+=1;counts["pii_leaked"]+=hit;by_file[name]["pii_leaked"]+=hit
                if hit:leaks.append(entry)
            else:
                counts["medical_total"]+=1;counts["medical_kept"]+=hit;by_file[name]["medical_missing"]+=not hit
                if not hit:missing.append(entry)
    records=[json.loads(x) for x in (out/"release/records.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    assigned={(r["file"],r["loc"]):r["patient"] for r in records};oracle=json.loads((split/"linkage.json").read_text(encoding="utf-8"))
    groups=defaultdict(set);covered=0;expected=0
    for patient,units in oracle["patients"].items():
        for u in units:
            if not u.get("required",True):continue
            expected+=1;meta=files[relative(u["file"])];dest=mapping.get(meta["sha256"])
            if not dest:continue
            loc=u["loc"];psn=assigned.get((dest,loc))
            if psn is None:
                # Only map standard pointer ancestors or explicit doc fallback; never invent CSS/HL7 locators.
                candidates=[(len(l),v) for (f,l),v in assigned.items() if f==dest and v and (l=="doc" or (loc.startswith("/") and loc.startswith(l+"/")))]
                psn=max(candidates)[1] if candidates else None
            if psn:covered+=1;groups[psn].add(patient)
    link={"truth_units":expected,"assigned_truth_units":covered,"unresolved_or_unexported_truth_units":expected-covered,"pseudonyms_covering_different_truth_patients":sum(len(v)>1 for v in groups.values()),"recall":"not defined for this corpus: each patient has one oracle unit; custom locators are diagnostic only"}
    result={"counts":dict(counts),"report_counts":report["counts"],"leaks_by_kind":dict(Counter(e["kind"] for e in leaks)),"per_file":{k:dict(v) for k,v in by_file.items()},"linkage_diagnostic":link,"truth_sha256":hashlib.sha256((split/"truth.json").read_bytes()).hexdigest(),"method":"Exact displayed values and output filenames. Quarantine counts as medical loss. No hidden-score claim."}
    for name,obj in [("results",result),("leaks",leaks),("medical_missing",missing)]:
        (out/(name+".json")).write_text(json.dumps(obj,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps({k:result[k] for k in ["counts","report_counts","leaks_by_kind","linkage_diagnostic"]},indent=2))


if __name__=="__main__":main()
