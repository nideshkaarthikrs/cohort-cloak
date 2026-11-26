#!/usr/bin/env python3
"""Dev evaluation beyond check_dev.py: record coverage, raw copies, per-kind medical preservation,
and linking quality. Prints a compact table. Dev data is for evaluation only.
"""
import argparse
import json
import re
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path


def norm(s):
    return " ".join(unicodedata.normalize("NFKC", s).casefold().split())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", required=True)
    ap.add_argument("--truth", required=True)
    a = ap.parse_args()
    out, truth_p = Path(a.output), Path(a.truth)
    truth = json.loads(truth_p.read_text(encoding="utf-8"))
    inp_root = truth_p.resolve().parents[1] / "input"
    report = json.loads((out / "report.json").read_text(encoding="utf-8"))
    mapped = {e["input_sha256"]: e.get("output") for e in report["files"]}
    recs = [json.loads(l) for l in (out / "records.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    rec_locs = defaultdict(set)
    for r in recs:
        rec_locs[r["file"]].add(r["loc"])

    kept, total = Counter(), Counter()
    raw_copies = missing_rec = truth_units = 0
    for rel, f in truth["files"].items():
        o = mapped.get(f["sha256"])
        exists = bool(o) and (out / o).is_file()
        text = norm((out / o).read_text(encoding="utf-8", errors="replace")) if exists else ""
        src = inp_root / rel
        if exists and f["expect"] == "either" and src.is_file() and (out / o).read_bytes() == src.read_bytes():
            raw_copies += 1
        for loc, u in f["units"].items():
            if loc.startswith("@"):
                continue
            if u.get("link") == "required" or u["entities"]:
                truth_units += 1
                if exists and not any(l == loc or l == "doc" or (loc.startswith(l + "/")) for l in rec_locs[o]):
                    missing_rec += 1
            for pv in u.get("preserve") or []:
                total[pv["kind"]] += 1
                kept[pv["kind"]] += exists and norm(pv["text"]) in text
    linked = sum(r["patient"] is not None for r in recs)
    print(f"records written {len(recs)} (truth units with entities/links: {truth_units}, uncovered: {missing_rec})")
    print(f"records linked {linked}; raw copies of broken files: {raw_copies}")
    print("medical preservation by kind (kept/total):")
    for k in sorted(total):
        print(f"   {k:<16} {kept[k]:>5}/{total[k]:<5} {100 * kept[k] / total[k]:5.1f}%")
    print(f"   {'ALL':<16} {sum(kept.values()):>5}/{sum(total.values()):<5} "
          f"{100 * sum(kept.values()) / max(1, sum(total.values())):5.1f}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
