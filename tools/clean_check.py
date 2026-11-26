#!/usr/bin/env python3
"""Token retention on documents that hold no PII (truth `clean: true`): must be 100%."""
import argparse
import json
import re
from pathlib import Path


def toks(path):
    return re.findall(r"[^\s,\[\]{}\":]+", path.read_bytes().decode("utf-8-sig", errors="replace"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", required=True)
    ap.add_argument("--truth", required=True)
    a = ap.parse_args()
    truth_p = Path(a.truth)
    truth = json.loads(truth_p.read_text(encoding="utf-8"))
    report = json.loads((Path(a.output) / "report.json").read_text(encoding="utf-8"))
    mapped = {e["input_sha256"]: e.get("output") for e in report["files"]}
    kept = total = 0
    for rel, f in sorted(truth["files"].items()):
        if not f.get("clean"):
            continue
        o = mapped.get(f["sha256"])
        src = toks(truth_p.resolve().parents[1] / "input" / rel)
        out = set(toks(Path(a.output) / o)) if o else set()
        total += len(src)
        kept += sum(t in out for t in src)
    print(f"clean/ token retention {kept}/{total} = {100 * kept / max(1, total):.1f}%")
    return 0 if kept == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
