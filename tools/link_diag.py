#!/usr/bin/env python3
"""Linking diagnostics against the dev truth: precision/recall/F0.5, wrong merges, trap scores, splits."""
import argparse
import itertools
import json
from collections import defaultdict
from pathlib import Path


def load(out, truth_p):
    truth = json.loads(Path(truth_p).read_text(encoding="utf-8"))
    report = json.loads((Path(out) / "report.json").read_text(encoding="utf-8"))
    mapped = {e["input_sha256"]: (e.get("output") or "").replace("sanitized/", "", 1) for e in report["files"]}
    recs = defaultdict(dict)
    for line in (Path(out) / "records.jsonl").read_text(encoding="utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            recs[r["file"].replace("sanitized/", "", 1)][r["loc"]] = r["patient"]
    units = []
    for rel, f in truth["files"].items():
        o = mapped.get(f["sha256"])
        for loc, u in f["units"].items():
            if u.get("link") == "required" and u.get("patient") and o:
                got = recs.get(o, {})
                psn = got.get(loc)
                if psn is None and loc.startswith("/"):
                    parts = loc.split("/")
                    for i in range(len(parts) - 1, 1, -1):
                        if "/".join(parts[:i]) in got:
                            psn = got["/".join(parts[:i])]
                            break
                if psn is None:
                    psn = got.get("doc")
                units.append((rel, loc, u["patient"], psn, u["tags"]))
    return truth, units


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", required=True)
    ap.add_argument("--truth", required=True)
    ap.add_argument("--show", type=int, default=0)
    a = ap.parse_args()
    truth, units = load(a.output, a.truth)
    by_true, by_psn = defaultdict(list), defaultdict(list)
    for i, (_r, _l, t, p, _g) in enumerate(units):
        by_true[t].append(i)
        if p:
            by_psn[p].append(i)
    tp = fp = 0
    for m in by_psn.values():
        for i, j in itertools.combinations(m, 2):
            if units[i][2] == units[j][2]:
                tp += 1
            else:
                fp += 1
    true_pairs = sum(len(v) * (len(v) - 1) // 2 for v in by_true.values())
    prec = tp / (tp + fp) if tp + fp else 0
    rec = tp / true_pairs if true_pairs else 0
    f05 = 1.25 * prec * rec / (0.25 * prec + rec) if prec + rec else 0

    def pair_recall(pts):
        pairs = hit = 0
        for t in pts:
            for i, j in itertools.combinations(by_true.get(t, []), 2):
                pairs += 1
                hit += bool(units[i][3] and units[i][3] == units[j][3])
        return hit / pairs if pairs else 0

    lang, frag = pair_recall(truth["traps"]["language"]), pair_recall(truth["traps"]["fragmented"])
    sep = sum(1 for p1, p2 in truth["traps"]["homonym_pairs"]
              if not ({units[i][3] for i in by_true.get(p1, []) if units[i][3]} & {units[i][3] for i in by_true.get(p2, []) if units[i][3]}))
    print(f"units {len(units)} linked {sum(1 for u in units if u[3])}  precision {prec:.3f} recall {rec:.3f} F0.5 {f05:.3f}")
    wrong = [(p, sorted({units[i][2] for i in m})) for p, m in by_psn.items() if len({units[i][2] for i in m}) > 1]
    print(f"wrong merges {len(wrong)}  language-trap recall {lang:.2f}  fragmented-trap recall {frag:.2f}  homonym pairs separated {sep}/{len(truth['traps']['homonym_pairs'])}")
    for p, ts in wrong[:a.show]:
        print("  WRONG", p, ts, [(units[i][0], units[i][1], units[i][2]) for i in by_psn[p]][:6])
    splits = sorted(((len({units[i][3] for i in m}), t) for t, m in by_true.items()), reverse=True)
    print("true patients split across pseudonyms:", sum(1 for n, _ in splits if n > 1), "of", len(by_true))
    for n, t in splits[:a.show]:
        if n > 1:
            groups = defaultdict(list)
            for i in by_true[t]:
                groups[units[i][3]].append(f"{units[i][0].split('/')[-1][:28]}:{units[i][1]}")
            print(f"  SPLIT {t} into {n}:", {str(k)[-4:]: v[:3] for k, v in groups.items()})


if __name__ == "__main__":
    main()
