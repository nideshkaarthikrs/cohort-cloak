#!/usr/bin/env python3
"""Own re-implementation of the arena attacks A1-A5 (see docs/ATTACKS.md) on a release folder or the raw input.

    python tools/attack_sim.py --kit ../Secret-Wards-ToolKit --release out_a [--raw]
Reports A3 (record linkage), A4 (patients re-identified at >=0.5), A5 (targeted success), A1 (direct exposure share)
for the release and, with --raw, for the raw input; prints each as a ratio to raw. Dev data is for evaluation only.
"""
import argparse
import csv
import datetime as dt
import hashlib
import io
import itertools
import json
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from cloak.detect.validators import ascii_digits  # noqa: E402
from cloak.ingest.records import csv_rows, json_locs  # noqa: E402
from cloak.ingest.sniff import parse  # noqa: E402
from cloak.link.translit import consonants, name_tokens_for_key, skeleton  # noqa: E402
from cloak.privacy.dates import find_dates  # noqa: E402


def norm(s):
    return " ".join(unicodedata.normalize("NFKC", s).casefold().split())


# ---------------------------------------------------------------------------------------------- registry
class Registry:
    def __init__(self, path):
        self.people = list(csv.DictReader(open(path, encoding="utf-8")))
        self.places = {k: defaultdict(set) for k in ("district", "tehsil", "village")}
        for i, p in enumerate(self.people):
            p["_i"] = i
            p["_tok"] = {skeleton(t) for t in name_tokens_for_key(p["name"])}
            p["_rel"] = {skeleton(t) for t in name_tokens_for_key(p["relative_name"] or "")}
            p["_given"] = skeleton((name_tokens_for_key(p["name"]) or [""])[0])
            p["_sur"] = skeleton((name_tokens_for_key(p["name"]) or [""])[-1])
            for k in self.places:
                if p[k]:
                    self.places[k][consonants(p[k])].add(p[k])
        self.by_phone = defaultdict(list)
        for p in self.people:
            if p["phone"]:
                self.by_phone[p["phone"]].append(p)


# ---------------------------------------------------------------------------------------------- evidence
_AGE_FORMS = [re.compile(r"(?<![\d.\-/])(\d{1,3})(?=\s*/\s*[MFmf]\b)"),
              re.compile(r"(?<![\d.\-/x])(\d{1,3})(?=\s*(?:Y|Yrs?|Years?|वर्ष)(?![A-Za-zऀ-ॿ]))", re.I)]
_BAND = re.compile(r"(?<![\d.\-/])(\d{1,3})\s*-\s*(\d{1,3})(?=\s*(?:Y|Yrs?|वर्ष|/\s*[MF]|\b))")
_TOP = re.compile(r"(?<![\d.])(\d{2,3})\s*\+")
_DR = re.compile(r"(?:Dr|DR|डॉ)\.?\s+(?:[A-Z][\w.]*|[ऀ-ॿ]+)(?:\s+(?:[A-Z][\w.]*|[ऀ-ॿ]+)){0,2}")
_WORD = re.compile(r"[A-Za-z]{3,}|[ऀ-ॣॱ-ॿ]{2,}")


class Ev:
    def __init__(self):
        self.ages, self.bands, self.birth, self.genders = [], [], set(), set()
        self.places = {"district": set(), "tehsil": set(), "village": set()}
        self.pins, self.pin3 = set(), set()
        self.skels, self.phones, self.emails, self.last4, self.masked = set(), set(), set(), set(), set()
        self.houses = set()
        self.dates, self.intervals, self.dx, self.hospitals, self.refs = set(), set(), set(), set(), set()
        self.texts = []
        self.dxtext = ""

    def merge(self, o):
        for k in ("ages", "bands", "texts"):
            getattr(self, k).extend(getattr(o, k))
        for k in ("birth", "genders", "pins", "pin3", "skels", "phones", "emails", "last4", "masked", "houses", "dates",
                  "intervals", "dx", "hospitals", "refs"):
            getattr(self, k).update(getattr(o, k))
        self.dxtext += " " + o.dxtext
        for k in self.places:
            self.places[k] |= o.places[k]


def extract(text, reg, hospitals, fields=()):
    ev = Ev()
    ev.texts.append(text)
    t = ascii_digits(text)
    for key, val in fields:
        k = norm(key)
        v = ascii_digits(str(val))
        if re.search(r"\bage\b|umar|आयु", k) and "sex" not in k and "gender" not in k:
            m = re.search(r"(\d{1,3})\s*-\s*(\d{1,3})", v)
            if m:
                ev.bands.append((int(m.group(1)), int(m.group(2))))
            elif re.search(r"(\d{1,3})\s*\+", v):
                ev.bands.append((int(re.search(r"(\d{1,3})\s*\+", v).group(1)), 120))
            elif re.fullmatch(r"\s*\d{1,3}\s*", v):
                ev.ages.append(int(v))
        if re.search(r"dob|birth|janm|जन्म", k):
            for d in find_dates(v, "dmy"):
                ev.birth.add(d.year or 0)
            m = re.fullmatch(r"\s*(\d{4})\s*", v)
            if m:
                ev.birth.add(int(m.group(1)))
        if re.search(r"gender|sex|ling|लिंग", k):
            g = v.strip()[:1].upper()
            if g in "MF":
                ev.genders.add(g)
            elif g == "म" or "महिला" in v:
                ev.genders.add("F")
            elif "पुरुष" in v:
                ev.genders.add("M")
        if re.search(r"\bpin\b|zip|postal", k):
            m = re.search(r"(\d{6})", v)
            if m:
                ev.pins.add(m.group(1))
            m = re.search(r"(\d{3})\*+", v)
            if m:
                ev.pin3.add(m.group(1))
    for rx in _AGE_FORMS:
        for m in rx.finditer(t):
            if 0 <= int(m.group(1)) <= 120:
                ev.ages.append(int(m.group(1)))
    for m in _BAND.finditer(t):
        lo, hi = int(m.group(1)), int(m.group(2))
        if 0 <= lo < hi <= 120 and hi - lo <= 25:
            ev.bands.append((lo, hi))
    for m in _TOP.finditer(t):
        if 60 <= int(m.group(1)) <= 110:
            ev.bands.append((int(m.group(1)), 120))
    for m in re.finditer(r"(?i)\bdob\W{0,3}[:\-]?\s*([^\n,;]{6,20})", t):
        for d in find_dates(m.group(1), "dmy"):
            ev.birth.add(d.year or 0)
    for m in re.finditer(r"/\s*([MF])\b", t):
        ev.genders.add(m.group(1))
    for m in re.finditer(r"(?i)\b(?:S/O|D/O|W/O)\b", t):
        ev.genders.add({"s": "M", "d": "F", "w": "F"}[m.group(0)[0].lower()])
    if re.search(r"(?i)sahab|sahib|babu\b|\bbhai\b", t):
        ev.genders.add("M")
    if re.search(r"(?i)behenji|\bdidi\b|\bamma\b|\bbibi\b", t):
        ev.genders.add("F")
    for m in re.finditer(r"(?<!\d)(\d{6})(?!\d)", t):
        ev.pins.add(m.group(1))
    for m in re.finditer(r"(?<!\d)(\d{3})\*{3}", t):
        ev.pin3.add(m.group(1))
    for m in re.finditer(r"(?<!\d)(?:\+?91[\s-]?)?([6-9]\d{4}[\s-]?\d{5})(?!\d)", t):
        ev.phones.add(re.sub(r"\D", "", m.group(1)))
    for m in re.finditer(r"(?<!\d)([6-9]\d)[Xx*]{4,6}(\d{2})(?!\d)", t):
        ev.masked.add((m.group(1), m.group(2)))
    for m in re.finditer(r"[\w.+\-]+@[\w\-]+\.[\w.\-]+", t):
        ev.emails.add(m.group(0).casefold())
    for m in re.finditer(r"[Xx*•]{4}[ \-]?[Xx*•]{4}[ \-]?(\d{4})", t):
        ev.last4.add(m.group(1))
    for m in re.finditer(r"(?i)(?:h\.?\s*no\.?|house(?:\s*no\.?)?|makan(?:\s*no\.?)?)\s*[:\-]?\s*(\d{1,4})", t):
        ev.houses.add(m.group(1))
    # names / places by transliteration-aware token lookup (doctors skipped)
    clean = _DR.sub(" ", text)
    words = _WORD.findall(clean)
    ev.skels = {skeleton(w) for w in words if skeleton(w)}
    cons = {consonants(w) for w in words}
    for kind in ev.places:
        for key, names in reg.places[kind].items():
            if len(key) >= 3 and key in cons:
                ev.places[kind] |= names
    for d in find_dates(t, "dmy"):
        try:
            ev.dates.add(d.as_date(2026))
        except ValueError:
            pass
    ds = sorted(ev.dates)
    for a, b in itertools.combinations(ds, 2):
        ev.intervals.add((b - a).days)
    for m in re.finditer(r"\b[A-TV-Z]\d{2}(?:\.\d{1,4})?\b", t):
        ev.dx.add(m.group(0))
    low = norm(text)
    for h in hospitals:
        if norm(h) in low:
            ev.hospitals.add(h)
    for m in re.finditer(r"(?<![A-Za-z0-9])[A-Za-z]{2,5}[\-/ ]?\d{5,}(?![A-Za-z0-9])", text):
        ev.refs.add(re.sub(r"[^a-z0-9]", "", m.group(0).casefold()))
    ev.dxtext = low
    return ev


# ---------------------------------------------------------------------------------------------- attack
def candidates(ev, reg, ages_tol=(1, 2)):
    cand = list(reg.people)

    def narrow(pred):
        nonlocal cand
        new = [p for p in cand if pred(p)]
        if new:
            cand = new

    if ev.phones:
        narrow(lambda p: p["phone"] in ev.phones)
    if ev.emails:
        narrow(lambda p: p["email"].casefold() in ev.emails)
    if ev.last4:
        narrow(lambda p: p["aadhaar_last4"] in ev.last4)
    if ev.masked:
        narrow(lambda p: any(p["phone"][:2] == a and p["phone"][-2:] == b for a, b in ev.masked if p["phone"]))
    if ev.places["district"]:
        narrow(lambda p: p["district"] in ev.places["district"])
    if len(ev.genders) == 1:
        g = next(iter(ev.genders))
        narrow(lambda p: p["gender"] == g)
    if ev.ages or ev.bands:
        def age_ok(p):
            a = int(p["age"] or 0)
            ok = True
            if ev.ages:
                ok = ok and any(x - ages_tol[0] <= a <= x + ages_tol[1] for x in ev.ages)
            if ev.bands:
                ok = ok and any(lo - ages_tol[0] <= a <= hi + ages_tol[1] for lo, hi in ev.bands)
            return ok
        narrow(age_ok)
    by = {y for y in ev.birth if y}
    if by:
        narrow(lambda p: any(abs(2026 - int(p["age"] or 0) - y) <= 2 for y in by))
    if ev.places["tehsil"]:
        narrow(lambda p: p["tehsil"] in ev.places["tehsil"])
    if ev.places["village"]:
        narrow(lambda p: p["village"] in ev.places["village"])
    if ev.pins:
        narrow(lambda p: p["pin"] in ev.pins)
    if ev.pin3:
        narrow(lambda p: p["pin"][:3] in ev.pin3)
    weights = []
    for p in cand:
        w = 1.0
        if len(p["_tok"]) >= 2 and p["_tok"] <= ev.skels:
            w *= 60
        else:
            if p["_given"] and p["_given"] in ev.skels:
                w *= 8
            if p["_sur"] and p["_sur"] in ev.skels:
                w *= 3
        if p["_rel"] and p["_rel"] <= ev.skels:
            w *= 8
        if p["house_no"] and p["house_no"] in ev.houses:
            w *= 2
        weights.append(w)
    return cand, weights


def prob_true(ev, reg, rid):
    cand, w = candidates(ev, reg)
    tot = sum(w)
    for p, x in zip(cand, w):
        if p["rid"] == rid:
            return x / tot
    return 0.0


# ---------------------------------------------------------------------------------------------- release loading
def units_of(root: Path, kind: str):
    """Yield (relpath, loc, Ev-builder inputs) for every record of a folder."""
    for p in sorted(x for x in root.rglob("*") if x.is_file()):
        rel = p.relative_to(root).as_posix()
        try:
            ps = parse(p.read_bytes(), p.suffix, 200)
        except Exception:  # noqa: BLE001
            continue
        if ps.kind == "csv":
            rows = csv_rows(ps.text, ps.delimiter)
            for i, row in enumerate(rows[1:]):
                yield rel, f"row:{i}", " ".join(row), list(zip(rows[0], row))
        elif ps.kind in ("json", "fhir"):
            data, locs = ps.data, json_locs(ps.data, ps.kind == "fhir")
            for loc in locs:
                node = data
                try:
                    for part in ([] if loc == "doc" else loc.strip("/").split("/")):
                        node = node[int(part)] if isinstance(node, list) else node[part.replace("~1", "/").replace("~0", "~")]
                except Exception:  # noqa: BLE001
                    continue
                fl = []

                def walk(o, key=""):
                    if isinstance(o, dict):
                        for k, v in o.items():
                            walk(v, k)
                    elif isinstance(o, list):
                        for v in o:
                            walk(v, key)
                    else:
                        fl.append((key, o))
                walk(node)
                yield rel, loc, json.dumps(node, ensure_ascii=False), fl
        else:
            yield rel, "doc", ps.text, []


def build_records(root, truth, mapped_out, reg, hospitals, is_raw, release_dir=None):
    """Return list of dict(file, loc, patient_true_rid, ev, psn|None, ref keys)."""
    psn = {}
    if not is_raw:
        for line in (Path(release_dir) / "records.jsonl").read_text(encoding="utf-8").splitlines():
            r = json.loads(line)
            psn[(r["file"].replace("sanitized/", "", 1), r["loc"])] = r["patient"]
    # truth lookup
    tmap = {}
    for rel, f in truth["files"].items():
        out_rel = rel if is_raw else mapped_out.get(f["sha256"])
        for loc, u in f["units"].items():
            if u.get("patient") and u.get("link") == "required":
                tmap[(out_rel, loc)] = u["patient"]
    pat_rid = {pid: p["rid"] for pid, p in truth["patients"].items()}
    out = []
    for rel, loc, text, fields in units_of(root, "raw" if is_raw else "out"):
        pid = tmap.get((rel, loc))
        if pid is None and loc.startswith("/"):
            parts = loc.split("/")
            for i in range(len(parts) - 1, 1, -1):
                pid = tmap.get((rel, "/".join(parts[:i])))
                if pid:
                    break
        if pid is None:
            pid = tmap.get((rel, "doc"))
        ev = extract(text, reg, hospitals, fields)
        out.append({"file": rel, "loc": loc, "pid": pid, "ev": ev, "psn": psn.get((rel, loc)),
                    "text": text})
    return out


def truth_rid(truth, pid):
    # truth.patients is keyed by P-id; units use PT-ids via a cid mapping: find rid through any unit with that PT id
    return truth["_pt2rid"].get(pid)


def run(kit, release, raw_input, label):
    kit = Path(kit)
    truth = json.loads((kit / "dev/truth/truth.json").read_text(encoding="utf-8"))
    pt2rid = {pid: p["rid"] for pid, p in truth["patients"].items()}
    truth["_pt2rid"] = pt2rid
    reg = Registry(kit / "dev/attacker/registry.csv")
    facts = [json.loads(l) for l in open(kit / "dev/attacker/known_facts.jsonl", encoding="utf-8")]
    hospitals = sorted({f["hospital"] for f in facts if f.get("hospital")})
    if raw_input:
        recs = build_records(kit / "dev/input", truth, None, reg, hospitals, True)
    else:
        rep = json.loads((Path(release) / "report.json").read_text(encoding="utf-8"))
        mapped = {e["input_sha256"]: (e.get("output") or "").replace("sanitized/", "", 1) for e in rep["files"]}
        recs = build_records(Path(release) / "sanitized", truth, mapped, reg, hospitals, False, release)
    labelled = [r for r in recs if r["pid"] and truth["_pt2rid"].get(r["pid"])]
    for r in labelled:
        r["rid"] = truth["_pt2rid"][r["pid"]]
    # A3: record-level probability on the true person
    a3 = [prob_true(r["ev"], reg, r["rid"]) for r in labelled]
    # profiles: shared pseudonym (release) / true patient (raw: attacker joins by shared reference values)
    prof = defaultdict(list)
    for i, r in enumerate(labelled):
        key = ("p", r["pid"]) if raw_input else (("psn", r["psn"]) if r["psn"] else ("rec", i))
        prof[key].append(r)
    prof_ev = {}
    for k, members in prof.items():
        ev = Ev()
        for m in members:
            ev.merge(m["ev"])
        prof_ev[k] = ev
    rid_best = {}
    a4_by_patient = defaultdict(float)
    for i, r in enumerate(labelled):
        key = ("p", r["pid"]) if raw_input else (("psn", r["psn"]) if r["psn"] else ("rec", i))
        pr = max(a3[i], prob_true(prof_ev[key], reg, r["rid"]))
        a4_by_patient[r["rid"]] = max(a4_by_patient[r["rid"]], pr)
    a4 = sum(1 for v in a4_by_patient.values() if v >= 0.5) / max(1, len(a4_by_patient))
    # A5 targeted
    patient_rids = set(a4_by_patient)
    offset_votes = Counter()
    reid = {}
    for k, members in prof.items():
        ev = prof_ev[k]
        rids = {m["rid"] for m in members}
        if len(rids) == 1:
            rid = next(iter(rids))
            p = prob_true(ev, reg, rid)
            if p >= 0.9:
                reid[k] = rid
    kf = {f["rid"]: f for f in facts}
    for k, rid in reid.items():
        f = kf.get(rid)
        if f:
            for vd in f["visit_dates"]:
                vd = dt.date.fromisoformat(vd)
                for d in prof_ev[k].dates:
                    offset_votes[(d - vd).days] += 1
    shift = 0
    if offset_votes:
        off, n = offset_votes.most_common(1)[0]
        agree = sum(1 for k, rid in reid.items() if rid in kf and any(
            (d - dt.date.fromisoformat(kf[rid]["visit_dates"][0])).days == off for d in prof_ev[k].dates))
        if agree >= 2 and off != 0:
            shift = off
    dx_count = Counter()
    for ev in prof_ev.values():
        for d in {c for c in ev.dx}:
            dx_count[d] += 1
    hits = []
    for rid, f in kf.items():
        vd = {dt.date.fromisoformat(x) for x in f.get("visit_dates", [])}
        scores = {}
        for k, ev in prof_ev.items():
            w = 0.0
            dates = {d - dt.timedelta(days=shift) for d in ev.dates}
            if vd & dates:
                w += 1
            cond = norm(f.get("condition_hint") or "")
            if cond and cond in ev.dxtext:
                share = sum(1 for e2 in prof_ev.values() if cond in e2.dxtext)
                w += 8 if share <= 3 else 1
            if f.get("stay_days") is not None and f["stay_days"] in ev.intervals:
                w += 1
            if w <= 0:
                continue
            if f.get("hospital") and f["hospital"] in ev.hospitals:
                w *= 2
            # consistency with the person
            person = next((p for p in reg.people if p["rid"] == rid), None)
            if person:
                a = int(person["age"] or 0)
                if ev.genders and person["gender"] not in ev.genders:
                    continue
                if (ev.ages or ev.bands) and not (any(x - 1 <= a <= x + 2 for x in ev.ages) or any(lo - 1 <= a <= hi + 2 for lo, hi in ev.bands) or not (ev.ages or ev.bands)):
                    continue
            scores[k] = w
        if not scores:
            hits.append((rid, 0.0))
            continue
        tot = sum(scores.values())
        p_true = 0.0
        for k, w in scores.items():
            members = prof[k]
            if any(m["rid"] == rid for m in members):
                p_true += w / tot
        hits.append((rid, p_true))
    targets = [p for rid, p in hits if rid in patient_rids]
    a5 = sum(targets) / max(1, len(targets))
    # A1: direct exposure (patient with a surviving full name or phone/aadhaar/uhid of a registry-known person)
    direct = 0
    for rid in patient_rids:
        person = next(p for p in reg.people if p["rid"] == rid)
        full = norm(person["name"])
        ph = person["phone"]
        hit = False
        for r in labelled:
            if r["rid"] != rid:
                continue
            t = norm(r["text"])
            if full in t or (ph and ph in re.sub(r"\D", "", ascii_digits(r["text"]))):
                hit = True
                break
        direct += hit
    a1 = direct / max(1, len(patient_rids))
    print(f"[{label}] records {len(labelled)} patients {len(patient_rids)}  A1 {a1:.3f}  A3 {sum(a3) / max(1, len(a3)):.3f}  "
          f"A4 {a4:.3f}  A5 {a5:.3f} (targets {len(targets)}, shift recovered {shift})")
    return {"A1": a1, "A3": sum(a3) / max(1, len(a3)), "A4": a4, "A5": a5}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--kit", required=True)
    ap.add_argument("--release", required=True)
    ap.add_argument("--raw-cache", default=None)
    a = ap.parse_args()
    cache = Path(a.raw_cache) if a.raw_cache else Path(a.release).parent / ".raw_attack.json"
    if cache.exists():
        raw = json.loads(cache.read_text())
    else:
        raw = run(a.kit, None, True, "raw")
        cache.write_text(json.dumps(raw))
    res = run(a.kit, a.release, False, "release")
    rel = {k: (res[k] / raw[k] if raw[k] else 0.0) for k in ("A1", "A3", "A4", "A5")}
    print("vs raw: " + "  ".join(f"{k} {v:.3f}" for k, v in rel.items()))
    print("ATTACK " + json.dumps({"release": res, "raw": raw, "ratio": rel}))


if __name__ == "__main__":
    main()
