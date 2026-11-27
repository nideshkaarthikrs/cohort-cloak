"""Reproducible local measurements; never imported by the application.
Scores are estimates from public practice tools, not official hidden-set scores.
"""
import argparse
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import importlib.util
import itertools
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import unicodedata
import yaml

ROOT = Path(__file__).resolve().parent.parent
PROTECTED = {"doctor", "dose", "frequency", "medication", "lab", "lab_test", "vital", "complaint", "history", "context", "hospital", "ward", "range", "amount"}


def run(args, log, env=None):
    result = subprocess.run([sys.executable] + list(map(str,args)), cwd=ROOT, env=env,
                            capture_output=True, text=True, encoding="utf-8", timeout=900)
    log.write_text(result.stdout + result.stderr, encoding="utf-8")
    if result.returncode:
        raise RuntimeError("Audit command failed; see " + str(log))
    return result.stdout


def norm(s):
    return " ".join(unicodedata.normalize("NFKC",s).casefold().split())


def verify(kit):
    truth=json.loads((kit/"dev/truth/truth.json").read_text(encoding="utf-8"))
    for rel,f in truth["files"].items():
        assert hashlib.sha256((kit/"dev/input"/rel).read_bytes()).hexdigest()==f["sha256"], "Practice hash mismatch"
    return truth


def preservation(kit, truth, release, policy):
    spec=importlib.util.spec_from_file_location("official_dev",kit/"check_dev.py")
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    report=json.loads((release/"report.json").read_text(encoding="utf-8"))
    mapped={f["input_sha256"]:f.get("output") for f in report["files"]}
    kept,total=Counter(),Counter(); losses=[]
    for rel,f in truth["files"].items():
        dest=mapped.get(f["sha256"])
        raw=(release/dest).read_text(encoding="utf-8") if dest else ""
        expanded=module.with_b64(raw);text=norm(expanded)
        for loc,u in f["units"].items():
            for pv in u.get("preserve",[]):
                kind=pv["kind"];total[kind]+=1
                hit=norm(pv["text"]) in text;kept[kind]+=hit
                if not hit:
                    intentional=kind=="district" or (kind in {"diagnosis","diagnosis_code","eponym"} and policy["rare_dx_max_patients"]>0) or (kind in {"procedure","package"} and policy.get("rare_proc_mode","generalise")=="generalise")
                    losses.append(dict(file=rel,loc=loc,kind=kind,value=pv["text"],classification="intentional_generalisation" if intentional else "false_positive_redaction",evidence="Configured rare clinical/location generalisation" if intentional else "Protected or non-generalised clinical probe missing"))
                elif norm(pv["text"]) not in norm(raw):
                    losses.append(dict(file=rel,loc=loc,kind=kind,value=pv["text"],classification="evaluation_error",evidence="Probe survives after base64 decoding"))
    return kept,total,losses


def measure(kit, truth, folder, policy):
    folder.mkdir(parents=True,exist_ok=True)
    pol=folder/"policy.yaml";pol.write_text(yaml.safe_dump(policy,sort_keys=True),encoding="utf-8")
    env=dict(os.environ,RAKSHA_SECRET="practice",COHORT_POLICY=str(pol),PYTHONUTF8="1")
    release=folder/"release"
    run([ROOT/"main.py","--input",kit/"dev/input","--output",release],folder/"run.txt",env)
    contract=run([kit/"validate_output.py","--input",kit/"dev/input","--output",release],folder/"contract.txt")
    dev=run([kit/"check_dev.py","--output",release],folder/"check_dev.txt")
    temporal=run([ROOT/"tools/eval_privacy.py","--output",release,"--truth",kit/"dev/truth/truth.json","--details",folder/"temporal.json"],folder/"privacy.txt")
    attack=run([ROOT/"tools/attack_sim.py","--kit",kit,"--release",release,"--raw-cache",folder/"raw_attack.json"],folder/"attack.txt")
    values={k:float(v) for k,v in re.findall(r"(\w+)=([0-9.]+)",temporal.split("METRICS ")[-1])}
    attacks=json.loads(re.search(r"ATTACK (.*)",attack).group(1))
    kept,total,losses=preservation(kit,truth,release,policy)
    (folder/"clinical_losses.json").write_text(json.dumps(losses,ensure_ascii=False,indent=2),encoding="utf-8")
    by_kind={k:{"kept":kept[k],"total":total[k]} for k in sorted(total)}
    medical=sum(kept.values())/sum(total.values())
    leaks=int(re.search(r"PERSONAL DATA: (\d+)",dev).group(1))
    canaries=int(re.search(r"CANARIES: (\d+)",dev).group(1))
    precision,recall=map(float,re.search(r"precision ([0-9.]+), recall ([0-9.]+)",dev).groups())
    protected=sum(total[k]-kept[k] for k in PROTECTED)
    context_kinds=PROTECTED|{"eponym"}
    context=sum(kept[k] for k in context_kinds)/max(1,sum(total[k] for k in context_kinds))
    detection=5*context/(4*context+1) if not leaks else 0
    utility=.35*medical+.20*values["temporal"]+.10*values["generalization"]+.15*(.5*values["icd_stat"]+.5*values["los_exact"])+.20
    risk=.2*sum(attacks["ratio"][k] for k in ("A1","A3","A4","A5"))
    estimate=20*detection+15*(1.25*precision*recall/(.25*precision+recall) if precision+recall else 0)+25*(1-risk)*min(1,utility/.4)+20*utility+20
    report=json.loads((release/"report.json").read_text(encoding="utf-8"))
    recs=[json.loads(x) for x in (release/"records.jsonl").read_text(encoding="utf-8").splitlines()]
    assert report["counts"]["records_processed"]==len(recs)
    assert report["counts"]["records_linked"]==sum(x["patient"] is not None for x in recs)
    assert report["counts"]["files_sanitized"]==sum(p.is_file() for p in (release/"sanitized").rglob("*"))
    source_files = [ROOT/"main.py"] + sorted((ROOT/"cloak").rglob("*.py"))
    source_sha256 = hashlib.sha256(b"".join(p.relative_to(ROOT).as_posix().encode()+b"\0"+p.read_bytes() for p in source_files)).hexdigest()
    result=dict(source_sha256=source_sha256,policy=policy,leaks=leaks,canaries=canaries,medical=medical,medical_by_kind=by_kind,protected_losses=protected,link_precision=precision,link_recall=recall,
                temporal=values,alignment=json.loads((folder/"temporal.json").read_text()),attacks=attacks,local_score_estimate=estimate,
                score_limitations="Estimate: assumes full integrity/performance, approximate contextual/clinical weights and official linking components; not an official score",
                report=report,contract_ok="CONTRACT OK" in contract)
    (folder/"metrics.json").write_text(json.dumps(result,indent=2),encoding="utf-8")
    return result


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--kit",type=Path,required=True)
    ap.add_argument("--out",type=Path,default=ROOT/"out_audit/hardening")
    ap.add_argument("--sweep",action="store_true")
    ap.add_argument("--apply",action="store_true")
    args=ap.parse_args();kit=args.kit.resolve();out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
    truth=verify(kit)
    base=json.loads((out/"baseline.json").read_text())["policy"] if (out/"baseline.json").exists() else (ROOT/"config/policy.yaml").read_text()
    policy=yaml.safe_load(base)
    if not args.sweep:
        result=measure(kit,truth,out/"final",yaml.safe_load((ROOT/"config/policy.yaml").read_text()))
        print(json.dumps({k:result[k] for k in ["leaks","medical","protected_losses","local_score_estimate"]},indent=2));return
    baseline=measure(kit,truth,out/"fixed_baseline_policy",policy)
    policies=[]
    for age,k,cap,fraction,proc in itertools.product([5,10],[3,5],[3,5,8],[.05,.10],["generalise","keep"]):
        policies.append(dict(policy,age_band_years=age,k_min=k,rare_dx_max_patients=cap,rare_dx_fraction=fraction,rare_proc_mode=proc))
    rows=[]
    def job(pair):
        i,p=pair;folder=out/"grid"/f"{i:02d}"
        row=measure(kit,truth,folder,p);row["index"]=i
        row["policy_changes"]=sum(p.get(k)!=policy.get(k,"generalise" if k=="rare_proc_mode" else None) for k in p)
        row["eligible"]=(row["leaks"]==row["canaries"]==row["protected_losses"]==0 and row["medical"]>=4576/4855 and row["link_precision"]==row["link_recall"]==1 and row["temporal"]["temporal"]>=baseline["temporal"]["temporal"] and row["alignment"]["resolved"]>=baseline["alignment"]["resolved"] and row["temporal"]["bands_truthful"]==1 and row["contract_ok"])
        return row
    with ThreadPoolExecutor(max_workers=2) as executor:
        for future in as_completed([executor.submit(job,pair) for pair in enumerate(policies)]):
            row=future.result();rows.append(row)
            print(f"Grid {len(rows)}/{len(policies)}: candidate {row['index']} eligible={row['eligible']} score_estimate={row['local_score_estimate']:.3f} medical={row['medical']:.4f} A5_ratio={row['attacks']['ratio']['A5']:.4f}",flush=True)
    rows.sort(key=lambda r:r["index"])
    (out/"grid_results.json").write_text(json.dumps(rows,indent=2),encoding="utf-8")
    eligible=[r for r in rows if r["eligible"]]
    if not eligible: raise RuntimeError("No policy met the acceptance gates")
    best=max(eligible,key=lambda r:(r["local_score_estimate"],-r["attacks"]["ratio"]["A5"],r["medical"],-r["policy_changes"],-r["index"]))
    (out/"selected.json").write_text(json.dumps(best,indent=2),encoding="utf-8")
    if args.apply:
        (ROOT/"config/policy.yaml").write_text("# Selected by the reproducible local balanced-score audit; see README.\n"+yaml.safe_dump(best["policy"],sort_keys=True),encoding="utf-8")
    print("SELECTED",best["index"],json.dumps(best["policy"],sort_keys=True),flush=True)


if __name__=="__main__":
    main()
