#!/usr/bin/env python3
"""Generate a stress set of synthetic hospital exports with its own truth, built to differ from the dev data:
unseen names (invented syllables, foreign Faker names), renamed/translated headers, shifted columns, new ID shapes,
new date formats, ';'-delimited CSV, .dat/.log text, FHIR variants, hidden channels (base64, %-encoding, \\u escapes,
homoglyph/zero-width names), canaries in every channel, malformed and binary files.

    python tools/make_stress.py --out stress/in --truth stress/truth.json [--seed 7] [--scale 1]
Needs Faker (requirements-dev.txt). Names are NOT drawn from data/lexicons.
"""
import argparse
import base64
import csv
import datetime as dt
import io
import json
import random
from pathlib import Path
from urllib.parse import quote

from faker import Faker
from indic_transliteration import sanscript

ONSET = ["dh", "k", "t", "pr", "sh", "v", "m", "n", "r", "s", "b", "j", "g", "kh", "th", "ch", "l", "h", "d", "p"]
VOW = ["a", "i", "u", "e", "o", "aa", "ee"]
CODA = ["", "", "n", "r", "sh", "m", "l", "t", "j", "k"]
SUR_END = ["wal", "kar", "iya", "pal", "rao", "ani", "ey", "gar", "sen", "ji", "ude", "oor"]
DISTRICTS = ["Faizabad", "Gonda", "Basti", "Mau", "Ballia", "Deoria", "Etah", "Orai", "Jalaun", "Mirzapur"]
HOSPITALS = ["Lok Kalyan Hospital", "Navjeevan Clinic and Nursing Home", "Shree Ram Medical Centre"]
DRUGS = ["Tab Metformin 500 mg 1-0-1 x 30 days", "Tab Telmisartan 40 mg 1-0-0 x 15 days", "Cap Omeprazole 20 mg 1-0-0 x 7 days",
         "Tab Azithromycin 500 mg 1-0-0 x 3 days", "Syp Ambroxol 5 ml TDS x 5 days", "Tab Atorvastatin 10 mg 0-0-1 x 30 days"]
DX = [("J18.9", "Pneumonia, unspecified"), ("E11.9", "Type 2 diabetes mellitus without complications"),
      ("I10", "Essential (primary) hypertension"), ("N39.0", "Urinary tract infection, site not specified"),
      ("K29.7", "Gastritis, unspecified"), ("B54", "Unspecified malaria"), ("D50.9", "Iron deficiency anaemia, unspecified")]
MONTHS_HI = ["जनवरी", "फ़रवरी", "मार्च", "अप्रैल", "मई", "जून", "जुलाई", "अगस्त", "सितंबर", "अक्टूबर", "नवंबर", "दिसंबर"]
HOMO = {"a": "а", "e": "е", "o": "о", "p": "р", "c": "с"}


class Gen:
    def __init__(self, seed, scale):
        self.r = random.Random(seed)
        self.fk = Faker("en_US")
        self.fk.seed_instance(seed)
        self.scale = scale
        self.files = {}
        self.truth = {"files": {}, "canaries": [], "patients": {}, "preserve": []}
        self.used = set()

    # ---- primitives -------------------------------------------------------------------------
    def word(self, parts=2):
        r = self.r
        return "".join(r.choice(ONSET) + r.choice(VOW) + r.choice(CODA) for _ in range(parts))

    def name(self):
        r = self.r
        k = r.random()
        if k < 0.6:
            n = f"{self.word(2).title()} {self.word(1).title()}{r.choice(SUR_END)}"
        elif k < 0.8:
            n = self.fk.name().replace("Dr. ", "").replace("Mr. ", "").replace("Mrs. ", "").replace("Ms. ", "")
            n = " ".join(n.split()[:2])
        else:
            n = f"{self.word(2).title()} {self.word(2).title()}"
        if n in self.used:
            return self.name()
        self.used.add(n)
        return n

    def phone(self):
        return str(self.r.choice("6789")) + "".join(str(self.r.randint(0, 9)) for _ in range(9))

    def fmt_phone(self, p):
        return self.r.choice([p, f"{p[:5]} {p[5:]}", f"+91 {p[:5]}-{p[5:]}", f"0{p}", f"{p[:3]}-{p[3:6]}-{p[6:]}", f"+91{p}"])

    def aadhaar(self):
        return str(self.r.randint(2, 9)) + "".join(str(self.r.randint(0, 9)) for _ in range(11))

    def devanagari(self, text):
        return sanscript.transliterate(text.lower(), sanscript.ITRANS, sanscript.DEVANAGARI)

    def deva_digits(self, s):
        return s.translate({ord(str(i)): ord("०") + i for i in range(10)})

    def date_fmt(self, d, style=None):
        style = style or self.r.choice(["ord", "dot2", "slashy", "iso", "mon", "hindi", "us"])
        if style == "ord":
            n = d.day
            suf = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
            return f"{n}{suf} {d.strftime('%b')} {d.year}"
        if style == "dot2":
            return d.strftime("%d.%m.%y")
        if style == "slashy":
            return d.strftime("%d/%m/%Y")
        if style == "iso":
            return d.isoformat()
        if style == "mon":
            return d.strftime("%d-%b-%Y")
        if style == "hindi":
            return f"{self.deva_digits(str(d.day))} {MONTHS_HI[d.month - 1]} {self.deva_digits(str(d.year))}"
        return d.strftime("%m/%d/%Y")

    def emit(self, rel, content, ids=(), names=(), preserve=()):
        data = content.encode("utf-8") if isinstance(content, str) else content
        self.files[rel] = data
        self.truth["files"][rel] = {"ids": list(ids), "names": list(names)}
        for p in preserve:
            self.truth["preserve"].append({"file": rel, "text": p})


def build(g: Gen, n_patients):
    r = g.r
    pats = []
    for i in range(n_patients):
        age = r.randint(3, 88)
        dob = dt.date(2026 - age, r.randint(1, 12), r.randint(1, 28))
        hosp = r.choice(["A", "B", "C"])
        uhid = {"A": f"KMC/2026/{r.randint(10000, 99999)}", "B": f"MR-{r.randint(10, 99)}-{r.randint(1000, 9999)}",
                "C": f"PHC{r.randint(100000, 999999)}"}[hosp]
        p = dict(i=i, name=g.name(), rel=g.name(), age=age, dob=dob, sex=r.choice("MF"), hosp=hosp, uhid=uhid,
                 phone=g.phone(), aadhaar=g.aadhaar(), village=g.word(3).title(), district=r.choice(DISTRICTS),
                 pin=str(r.randint(200000, 285000)), dx=r.choice(DX), drug=r.choice(DRUGS),
                 adm=dt.date(2026, r.randint(1, 10), r.randint(1, 25)))
        p["dis"] = p["adm"] + dt.timedelta(days=r.randint(2, 12))
        pats.append(p)
        g.truth["patients"][str(i)] = {"name": p["name"], "uhid": uhid}
    return pats


def critical(p):
    return [p["uhid"], p["phone"], p["aadhaar"]]


def write_all(g: Gen, pats):
    r = g.r
    # 1. registration, comma CSV, renamed/translated headers, BOM
    rows = [["Rogi ka Naam", "Umra", "Mobile#", "Aadhaar/UID", "Gaon/Mohalla", "Jila", "Janmatithi", "Pita/Pati", "OPD No"]]
    sub = [p for p in pats if p["hosp"] == "A"] or pats[:5]
    for p in sub:
        rows.append([p["name"], p["age"], g.fmt_phone(p["phone"]), " ".join([p["aadhaar"][:4], p["aadhaar"][4:8], p["aadhaar"][8:]]),
                     p["village"], p["district"], g.date_fmt(p["dob"], "slashy"), p["rel"], p["uhid"]])
    buf = io.StringIO()
    csv.writer(buf, lineterminator="\n").writerows(rows)
    g.emit("reg/lokkalyan_rogi_register.csv", "﻿" + buf.getvalue(),
           ids=[x for p in sub for x in critical(p)], names=[n for p in sub for n in (p["name"], p["rel"])])
    # 2. semicolon CSV, cp1252-safe, shifted columns on some rows
    sub = [p for p in pats if p["hosp"] == "B"] or pats[5:10]
    rows = [["Patient's Full Name", "Contact No.", "DOB", "Sex", "Address", "Pincode", "Hosp. No.", "Remarks"]]
    for k, p in enumerate(sub):
        name_cell, ph = p["name"], g.fmt_phone(p["phone"])
        row = [name_cell, ph, g.date_fmt(p["dob"], "dot2" if False else "mon"), p["sex"],
               f"House {r.randint(1, 400)}, {p['village']}, Dist {p['district']}", p["pin"], p["uhid"], ""]
        if k % 4 == 3:
            row[0], row[1] = row[1], row[0]  # shifted values: phone under the name header
        rows.append(row)
    buf = io.StringIO()
    csv.writer(buf, delimiter=";", lineterminator="\n").writerows(rows)
    g.emit("reg/navjeevan_reg.csv", buf.getvalue(), ids=[x for p in sub for x in (p["uhid"], p["phone"])],
           names=[p["name"] for p in sub])
    # 3. UTF-16 TSV, Hinglish headers
    sub = [p for p in pats if p["hosp"] == "C"] or pats[10:15]
    lines = ["Patient ka naam\tLing\tPhone no\tGrah/Gaon\tTarikh\tAadhar Card"]
    for p in sub:
        lines.append(f"{g.devanagari(p['name']) if p['i'] % 2 else p['name']}\t{'पुरुष' if p['sex'] == 'M' else 'महिला'}\t{g.deva_digits(p['phone'])}\t"
                     f"{g.devanagari(p['village'])}\t{g.date_fmt(p['adm'], 'hindi')}\t{p['aadhaar']}")
    g.emit("reg/shree_ram_patients.tsv", ("\r\n".join(lines) + "\r\n").encode("utf-16"),
           ids=[x for p in sub for x in (p["phone"], p["aadhaar"])], names=[p["name"] for p in sub])
    # 4. OPD JSON, new structure
    for m in range(1, 4):
        sub = pats[m::3][:12]
        enc = []
        for p in sub:
            enc.append({"pt": {"fullname": p["name"], "ph": g.fmt_phone(p["phone"]), "yrs": p["age"], "sex": p["sex"]},
                        "mrn": p["uhid"], "dt": g.date_fmt(p["adm"], "ord"), "dx": {"icd": p["dx"][0], "label": p["dx"][1]},
                        "rx": [p["drug"]], "remarks": f"Accompanied by {p['rel']} ({g.fmt_phone(g.phone())}). Advised rest."})
        doc = {"export": {"by": "front.desk", "at": "2026-0%d-28T18:00:00+05:30" % m}, "encounters": enc}
        g.emit(f"opd/encounters_{m:02d}.json", json.dumps(doc, indent=1, ensure_ascii=False),
               ids=[x for p in sub for x in (p["uhid"], p["phone"])], names=[n for p in sub for n in (p["name"], p["rel"])],
               preserve=[p["drug"] for p in sub] + [p["dx"][0] for p in sub])
    # 5. lab csv, 2-digit-year dates
    rows = [["Pt Name", "UHID No", "Test", "Result", "Unit", "Collected"]]
    sub = pats[:20]
    for p in sub:
        for t, v, u in (("Haemoglobin", round(r.uniform(8, 15), 1), "g/dL"), ("Random Blood Sugar", r.randint(80, 300), "mg/dL")):
            rows.append([p["name"].upper(), p["uhid"], t, v, u, g.date_fmt(p["adm"], "dot2")])
    buf = io.StringIO()
    csv.writer(buf, lineterminator="\n").writerows(rows)
    g.emit("lab/city_path_lab.csv", buf.getvalue(), ids=[p["uhid"] for p in sub], names=[p["name"] for p in sub])
    # 6. discharge text, three templates, filenames carrying names and IDs
    for k, p in enumerate(pats[:30]):
        tpl = k % 3
        if tpl == 0:
            text = (f"{r.choice(HOSPITALS).upper()}\nDISCHARGE CARD\nPt Name: {p['name']}   Sex/Age: {p['sex']}/{p['age']}\n"
                    f"Hosp No: {p['uhid']}\nS/D/W of: {p['rel']}\nResident of: {p['village']}, Dist {p['district']} - {p['pin']}\n"
                    f"Ph: {g.fmt_phone(p['phone'])}\nDOA: {g.date_fmt(p['adm'], 'mon')}   DOD: {g.date_fmt(p['dis'], 'mon')}\n"
                    f"Final Diagnosis: {p['dx'][1]} ({p['dx'][0]})\nTreatment: {p['drug']}\nAttendant: {p['rel']} {g.fmt_phone(g.phone())}\n")
            names, ids = (p["name"], p["rel"]), critical(p)[:2]
        elif tpl == 1:
            text = (f"रोगी का नाम: {g.devanagari(p['name'])}   आयु: {g.deva_digits(str(p['age']))} वर्ष\nपंजीकरण सं.: {p['uhid']}\n"
                    f"पति/पिता: {g.devanagari(p['rel'])}\nग्राम: {g.devanagari(p['village'])}\nमोबाइल: {g.deva_digits(p['phone'])}\n"
                    f"भर्ती: {g.date_fmt(p['adm'], 'hindi')}\nनिदान: {p['dx'][1]} ({p['dx'][0]})\n{p['drug']}\n")
            names, ids = (p["name"], p["rel"]), critical(p)[:2]
        else:
            text = (f"Mr. {p['name']}, aged {p['age']} yrs, resident of {p['village']}, was admitted on {g.date_fmt(p['adm'], 'ord')} "
                    f"with complaints of fever x 3 days. Contact number {g.fmt_phone(p['phone'])}. UHID {p['uhid']}. "
                    f"His relative {p['rel']} signed the consent. Diagnosis {p['dx'][1]} ({p['dx'][0]}). {p['drug']}.\n")
            names, ids = (p["name"], p["rel"]), critical(p)[:2]
        fname = f"summary_{p['name'].replace(' ', '_')}_{p['uhid'].replace('/', '-')}.txt"
        g.emit(f"discharge/{fname}", text, ids=ids, names=names, preserve=[p["drug"], p["dx"][0]])
    # 7. nursing notes .log / .dat with cue-only names
    for k, p in enumerate(pats[30:45]):
        text = (f"Ward round {g.date_fmt(p['adm'], 'dot2')}\n"
                f"06:00 - Shri {p['name']} ji ka BP 128/84, pulse 88. Attendant {p['rel']} ({g.fmt_phone(p['phone'])}) informed.\n"
                f"Bed 4, ref {p['uhid']}\n")
        g.emit(f"notes/ward_{k:03d}.{'log' if k % 2 else 'dat'}", text, ids=[p["uhid"], p["phone"]], names=[p["name"], p["rel"]],
               preserve=["BP 128/84"])
    # 8. FHIR variants
    for k, p in enumerate(pats[45:55] if len(pats) >= 55 else pats[:6]):
        patient = {"resourceType": "Patient", "id": f"p{k}", "name": [{"text": p["name"]}],
                   "telecom": [{"system": "phone", "value": g.fmt_phone(p["phone"])}], "birthDate": p["dob"].isoformat(),
                   "identifier": [{"system": "https://lokkalyan.example/mr", "value": p["uhid"]}],
                   "address": [{"line": [f"{r.randint(1, 99)}, {p['village']}"], "district": p["district"], "postalCode": p["pin"]}],
                   "contact": [{"relationship": [{"text": "Guardian"}], "name": {"text": p["rel"]}}]}
        att = base64.b64encode(f"Patient {p['name']} Hosp No {p['uhid']} Mobile {p['phone']}".encode()).decode()
        bundle = {"resourceType": "Bundle", "type": "document", "entry": [
            {"fullUrl": f"urn:uuid:00000000-0000-4000-8000-{k:012d}", "resource": patient},
            {"resource": {"resourceType": "Condition", "code": {"coding": [{"system": "http://hl7.org/fhir/sid/icd-10", "code": p["dx"][0],
                                                                         "display": p["dx"][1]}]}, "subject": {"reference": f"urn:uuid:00000000-0000-4000-8000-{k:012d}"}}},
            {"resource": {"resourceType": "DocumentReference", "status": "current", "content": [{"attachment": {"contentType": "text/plain", "data": att}}]}}]}
        g.emit(f"fhir/doc_{k:02d}.json", json.dumps(bundle, indent=1, ensure_ascii=False),
               ids=critical(p)[:2], names=[p["name"], p["rel"]], preserve=[p["dx"][0]])
    # 9. hidden channels: percent, \u escapes, homoglyph, zero-width
    for k, p in enumerate(pats[55:60] if len(pats) >= 60 else pats[:3]):
        nm = p["name"]
        homo = "".join(HOMO.get(c, c) if c in HOMO and j % 2 == 0 else c for j, c in enumerate(nm))
        zw = nm[:2] + "​" + nm[2:]
        uesc = "".join(f"\\u{ord(c):04x}" for c in f"{nm} {p['phone']}")
        g.emit(f"misc/obfuscated_{k}.json", json.dumps({"a": quote(f"called by {nm} {p['phone']}"), "b": f"visitor {homo} {p['phone']}",
                                                      "c": f"visitor {zw} {g.fmt_phone(p['phone'])}"}, ensure_ascii=False) .replace('"c"', '"c"'),
               ids=[p["phone"]], names=[nm])
        g.emit(f"misc/escaped_{k}.txt", f"note: {uesc}\n", ids=[p["phone"]], names=[nm])
    # 10. canaries in every channel
    for c in range(5):
        nm, ph = g.name(), g.phone()
        g.truth["canaries"].append(nm)
        g.truth["canaries"].append(ph)
        if c == 0:
            g.emit("misc/visitor_log.txt", f"Visitor log\n{nm} (attendant, bed 3), mob {g.fmt_phone(ph)}\n", ids=[ph], names=[nm])
        elif c == 1:
            g.emit("misc/tickets.json", json.dumps({"meta": {"raised_by": nm, "callback": ph}, "tickets": [{"id": 1}]}), ids=[ph], names=[nm])
        elif c == 2:
            g.emit("misc/ambulance.csv", f"trip,from,remarks\n1,Gate,called by {nm} {g.fmt_phone(ph)}\n", ids=[ph], names=[nm])
        elif c == 3:
            att = base64.b64encode(f"Consent signed by {nm}, contact {ph}".encode()).decode()
            g.emit("misc/consent.json", json.dumps({"form": "consent", "scan": att}), ids=[ph], names=[nm])
        else:
            g.emit(f"misc/call_{nm.replace(' ', '_')}_{ph}.txt", "Call back requested.\n", ids=[ph], names=[nm])
    # 11. clean documents (must survive unchanged)
    g.emit("clean/protocol.txt", "Hypertension protocol: check BP 140/90, start Tab Amlodipine 5 mg 1-0-0, review after 2 wks.\n",
           preserve=["BP 140/90", "Tab Amlodipine 5 mg 1-0-0"])
    g.emit("clean/formulary.csv", "drug,form,strength\nMetformin,Tablet,500 mg\nOmeprazole,Capsule,20 mg\n")
    # 12. malformed / unsupported
    g.emit("misc/truncated.json", '{"encounters": [{"pt": {"fullname": "Cut Off"', ids=[], names=[])
    g.emit("misc/deep.json", "[" * 1500 + "]" * 1500)
    g.emit("misc/binary.dat", bytes(range(256)) * 4)
    g.emit("misc/empty.csv", b"")
    g.emit("misc/report.xml", "<?xml version='1.0'?><doc><name>Xml Person</name></doc>")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--truth", required=True)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--scale", type=int, default=1)
    a = ap.parse_args()
    out = Path(a.out)
    total = 0
    truth = {"files": {}, "canaries": [], "preserve": []}
    for s in range(a.scale):
        g = Gen(a.seed + s * 1000, a.scale)
        pats = build(g, 70)
        write_all(g, pats)
        prefix = f"s{s:02d}/" if a.scale > 1 else ""
        for rel, data in g.files.items():
            p = out / (prefix + rel)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(data)
            total += 1
        for rel, v in g.truth["files"].items():
            truth["files"][prefix + rel] = v
        truth["canaries"] += g.truth["canaries"]
        truth["preserve"] += [{"file": prefix + x["file"], "text": x["text"]} for x in g.truth["preserve"]]
    Path(a.truth).write_text(json.dumps(truth, ensure_ascii=False), encoding="utf-8")
    print(f"stress files {total}")


if __name__ == "__main__":
    main()
