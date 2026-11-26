#!/usr/bin/env python3
"""Utility-side measurements against the dev truth: temporal (intervals, length of stay), truthful bands,
generalisation score, ICD distribution, and a proxy of the official utility score. Prints compact numbers."""
import argparse
import csv
import datetime as dt
import io
import json
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from cloak.privacy.dates import find_dates  # noqa: E402
from cloak.detect.validators import ascii_digits  # noqa: E402


def norm(s):
    return " ".join(unicodedata.normalize("NFKC", s).casefold().split())


def unit_text(raw: str, loc: str, fmt: str, delim: str):
    """Text of one record (CSV row / JSON subtree / whole doc)."""
    if loc == "doc" or loc.startswith("@"):
        return raw
    if loc.startswith("row:"):
        rows = list(csv.reader(io.StringIO(raw, newline=""), delimiter=delim or ","))
        i = int(loc[4:]) + 1
        return "\u0001".join(rows[i]) if i < len(rows) else ""
    try:
        node = json.loads(raw)
        for part in loc.strip("/").split("/"):
            node = node[int(part)] if isinstance(node, list) else node[part.replace("~1", "/").replace("~0", "~")]
        return json.dumps(node, ensure_ascii=False)
    except Exception:  # noqa: BLE001
        return ""


def read(p: Path) -> str:
    return p.read_bytes().decode("utf-8-sig", errors="replace")


def dates_in(text, hint):
    toks = find_dates(ascii_digits(text), hint)
    out = []
    for t in toks:
        try:
            out.append(t.as_date(2026))
        except ValueError:
            pass
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", required=True)
    ap.add_argument("--truth", required=True)
    a = ap.parse_args()
    out, truth_p = Path(a.output), Path(a.truth)
    truth = json.loads(truth_p.read_text(encoding="utf-8"))
    inp_root = truth_p.resolve().parents[1] / "input"
    report = json.loads((out / "report.json").read_text(encoding="utf-8"))
    mapped = {e["input_sha256"]: (e.get("output") or "").replace("sanitized/", "", 1) for e in report["files"]}

    events = defaultdict(list)   # patient -> [(event, true_date, out_date)]
    los_total = los_ok = 0
    band_total = band_ok = 0
    gen = defaultdict(list)
    icd_in, icd_out = Counter(), Counter()
    for rel, f in sorted(truth["files"].items()):
        o = mapped.get(f["sha256"])
        if not o or not (out / "sanitized" / o).is_file():
            continue
        raw_in, raw_out = read(inp_root / rel), read(out / "sanitized" / o)
        for m in re.finditer(r"\b([A-TV-Z]\d{2})(?:\.\d{1,4})?\b", raw_in):
            icd_in[m.group(1)] += 1
        for m in re.finditer(r"\b([A-TV-Z]\d{2})(?:\.\d{1,4})?\b", raw_out):
            icd_out[m.group(1)] += 1
        for loc, u in f["units"].items():
            if not (u.get("dates") or u.get("fields")):
                continue
            ti, to = unit_text(raw_in, loc, f["format"], f.get("delimiter")), unit_text(raw_out, loc, f["format"], f.get("delimiter"))
            if u.get("dates"):
                hint = u["dates"][0].get("hint", "dmy")
                din, dout = dates_in(ti, hint), dates_in(to, hint)
                truth_dates = {dt.date.fromisoformat(d["true"]): d for d in u["dates"]}
                pos = {}
                for i, d in enumerate(din):
                    pos.setdefault(d, i)
                for d, meta in truth_dates.items():
                    i = pos.get(d)
                    od = dout[i] if i is not None and i < len(dout) and len(dout) == len(din) else None
                    events[meta["patient"]].append((meta["event"], d, od))
            for fld in u.get("fields", []):
                path, kind, true = fld.get("path"), fld["kind"], fld["true"]
                if not path:
                    continue
                cell = None
                if path.startswith("col:") and loc.startswith("row:"):
                    rows = list(csv.reader(io.StringIO(raw_out, newline=""), delimiter=f.get("delimiter") or ","))
                    hdr_in = list(csv.reader(io.StringIO(raw_in, newline=""), delimiter=f.get("delimiter") or ","))[0]
                    name = path[4:]
                    if name in hdr_in and rows:
                        j, i = hdr_in.index(name), int(loc[4:]) + 1
                        if i < len(rows) and j < len(rows[i]):
                            cell = rows[i][j]
                else:
                    node = None
                    try:
                        node = json.loads(raw_out)
                        for part in path.strip("/").split("/"):
                            node = node[int(part)] if isinstance(node, list) else node[part]
                    except Exception:  # noqa: BLE001
                        node = None
                    cell = None if node is None else str(node)
                if cell is None:
                    continue
                cell = ascii_digits(cell)
                score = 0.0
                if kind == "age":
                    m = re.search(r"(\d{1,3})\s*-\s*(\d{1,3})", cell)
                    p = re.search(r"(\d{1,3})\s*\+", cell)
                    n = re.search(r"\d{1,3}", cell)
                    band_total += 1
                    if m:
                        lo, hi = int(m.group(1)), int(m.group(2))
                        ok = lo <= true <= hi
                        width = hi - lo + 1
                        score = (0.9 if width <= 5 else 0.8 if width <= 10 else 0.6 if width <= 20 else 0.3) if ok else 0
                    elif p:
                        ok = true >= int(p.group(1))
                        score = 0.3 if ok else 0
                    elif n:
                        ok = int(n.group(0)) == true
                        score = 1.0 if ok else 0
                    else:
                        ok = False
                    band_ok += bool(ok)
                elif kind == "village":
                    low = norm(cell)
                    score = 1.0 if low and low == norm(str(true).split(":")[0]) else 0.0
                    parts = fld.get("true", "")
                    # the truth keeps village as a key; score tehsil/district text as generalised
                    score = score or (0.7 if low and "[" not in low else 0.0)
                elif kind == "district":
                    score = 1.0 if norm(cell) == norm(str(true)) else 0.0
                elif kind == "pin":
                    score = 1.0 if cell.strip() == str(true) else 0.7 if cell.strip().startswith(str(true)[:3]) else 0.0
                elif kind == "dob":
                    try:
                        td = dt.date.fromisoformat(true)
                        od = find_dates(cell, "dmy")
                        if od:
                            d0 = od[0].as_date(2026)
                            score = 1.0 if d0 == td else 0.9 if abs((d0 - td).days) <= 366 else 0.0
                        elif re.fullmatch(r"\s*(\d{4})\s*", cell):
                            score = 0.8
                    except ValueError:
                        pass
                elif kind == "gender":
                    score = 1.0 if cell.strip()[:1].upper() == str(true)[:1].upper() else 0.0
                gen[kind].append(score)
    # temporal: intervals between every pair of a patient's dated events, LOS from admission/discharge pairs
    pairs = exact = near = 0
    for pid, evs in events.items():
        evs = [e for e in evs if e[2] is not None]
        for (e1, t1, o1), (e2, t2, o2) in __import__("itertools").combinations(evs, 2):
            pairs += 1
            d = abs((o2 - o1).days - (t2 - t1).days)
            exact += d == 0
            near += d <= 1
        adm = [e for e in evs if e[0] == "admission"]
        dis = [e for e in evs if e[0] == "discharge"]
        for ea in adm:
            for ed in dis:
                if 0 <= (ed[1] - ea[1]).days < 60:
                    los_total += 1
                    los_ok += (ed[2] - ea[2]).days == (ed[1] - ea[1]).days
    temporal = 0.6 * ((exact + 0.5 * (near - exact)) / pairs if pairs else 0) + 0.4 * (los_ok / los_total if los_total else 0)
    gscore = sum(sum(v) for v in gen.values()) / max(1, sum(len(v) for v in gen.values()))
    keys = set(icd_in) | set(icd_out)
    tin, tout = sum(icd_in.values()) or 1, sum(icd_out.values()) or 1
    tvd = 0.5 * sum(abs(icd_in[k] / tin - icd_out[k] / tout) for k in keys)
    print(f"temporal: intervals exact {exact}/{pairs} (+-1 day {near}/{pairs}); LOS exact {los_ok}/{los_total}")
    print(f"bands: truthful {band_ok}/{band_total}")
    print("generalisation by field: " + ", ".join(f"{k} {sum(v) / len(v):.2f}" for k, v in sorted(gen.items())) + f"; mean {gscore:.3f}")
    print(f"icd distribution TVD {tvd:.3f}")
    print(f"METRICS temporal={temporal:.4f} generalization={gscore:.4f} icd_stat={1 - tvd:.4f} los_exact={los_ok / max(1, los_total):.4f} bands_truthful={band_ok / max(1, band_total):.4f}")


if __name__ == "__main__":
    main()
