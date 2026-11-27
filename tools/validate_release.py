"""Independent local export reconciliation and structural FHIR checks (not a full R4 schema validator)."""
import argparse
import base64
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from cloak.ingest.sniff import parse


def fhir(bundle):
    entries=bundle.get("entry",[])
    resources=[e.get("resource",{}) for e in entries]
    targets={e["fullUrl"] for e in entries if e.get("fullUrl")}
    targets.update(r.get("resourceType","")+"/"+r["id"] for r in resources if r.get("id"))
    for resource in resources:
        assert isinstance(resource.get("resourceType"),str)
        if "id" in resource: assert re.fullmatch(r"[A-Za-z0-9\-.]{1,64}",resource["id"])
        contained={"#"+r["id"] for r in resource.get("contained",[]) if "id" in r}
        def walk(node):
            if isinstance(node,list):
                for value in node: walk(value)
            elif isinstance(node,dict):
                if "reference" in node:
                    ref=node["reference"]
                    assert ref in targets or ref in contained, "Unresolved internal FHIR reference"
                if "contentType" in node and "data" in node:
                    base64.b64decode(node["data"],validate=True)
                for value in node.values(): walk(value)
        walk(resource)


def main():
    ap=argparse.ArgumentParser();ap.add_argument("--input",type=Path,required=True);ap.add_argument("--output",type=Path,required=True);args=ap.parse_args()
    report=json.loads((args.output/"report.json").read_text(encoding="utf-8"))
    inputs=Counter(hashlib.sha256(p.read_bytes()).hexdigest() for p in args.input.rglob("*") if p.is_file())
    assert Counter(e["input_sha256"] for e in report["files"])==inputs
    exported={p.relative_to(args.output).as_posix() for p in (args.output/"sanitized").rglob("*") if p.is_file()}
    declared={e["output"] for e in report["files"] if e["status"]=="sanitized"}
    assert exported==declared
    counts=Counter()
    for path in sorted(exported):
        raw=(args.output/path).read_bytes();raw.decode("utf-8")
        parsed=parse(raw,Path(path).suffix,200)
        if parsed.kind=="fhir": fhir(parsed.data)
        counts[parsed.kind]+=1
    records=[json.loads(line) for line in (args.output/"records.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    c=report["counts"]
    assert c["files_total"]==sum(inputs.values())
    assert c["files_sanitized"]==len(exported)
    assert c["files_quarantined"]==len(report["files"])-len(exported)
    assert c["records_processed"]==len(records)
    assert c["records_linked"]==sum(r["patient"] is not None for r in records)
    assert all(r["file"] in exported for r in records)
    assert report["resources"]["peak_rss_mb"]>0
    print("EXPORT RECONCILED",dict(counts))


if __name__=="__main__":main()
