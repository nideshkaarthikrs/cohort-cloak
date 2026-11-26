#!/usr/bin/env python3
"""Unseen-layout set: document shapes the detectors were never tuned on (different from make_stress.py).

Title rows above CSV headers, pipe-delimited text, `Field = value` records, arrays-of-arrays JSON, FHIR with
`contained` patients and `Beneficiary`/`Applicant` labels, Hinglish narrative letters, Devanagari-only names,
claim forms, pharmacy dispensing sheets, SMS-style notes. Names/IDs come from make_stress.Gen (not the gazetteer).
Usage: python tools/make_stress2.py --out DIR --truth FILE [--seed 5]
"""
import argparse
import csv
import io
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from make_stress import DRUGS, DX, DISTRICTS, Gen, build, critical  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--truth", required=True)
    ap.add_argument("--seed", type=int, default=5)
    a = ap.parse_args()
    g = Gen(a.seed, 1)
    r = g.r
    pats = build(g, 60)
    # 1. CSV with two title rows before the header and a trailing totals row
    sub = pats[:15]
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["PHARMACY DISPENSING REGISTER - Lok Kalyan Hospital"])
    w.writerow(["Month: March 2026", "", "", ""])
    w.writerow(["Beneficiary", "Bill Ref", "Medicine", "Qty", "Contact"])
    for p in sub:
        w.writerow([p["name"], f"BL{r.randint(10000, 99999)}", p["drug"], r.randint(1, 30), g.fmt_phone(p["phone"])])
    w.writerow(["TOTAL", "", "", len(sub), ""])
    g.emit("pharmacy/dispense_register.csv", buf.getvalue(), ids=[p["phone"] for p in sub], names=[p["name"] for p in sub],
           preserve=[p["drug"] for p in sub])
    # 2. pipe-delimited text export
    lines = ["PATIENT|MOBILE|UHID|VISIT|DX"]
    sub = pats[15:30]
    for p in sub:
        lines.append(f"{p['name']}|{g.fmt_phone(p['phone'])}|{p['uhid']}|{g.date_fmt(p['adm'], 'slashy')}|{p['dx'][0]}")
    g.emit("export/visits.psv", "\n".join(lines) + "\n", ids=[x for p in sub for x in (p["phone"], p["uhid"])],
           names=[p["name"] for p in sub], preserve=[p["dx"][0] for p in sub])
    # 3. `Field = value` records (one file per patient, .rec extension)
    for p in pats[30:40]:
        g.emit(f"records/{p['i']:03d}.rec",
               f"[PATIENT]\nApplicant = {p['name']}\nGuardian = {p['rel']}\nContact = {g.fmt_phone(p['phone'])}\nCard = {p['uhid']}\n"
               f"Born = {g.date_fmt(p['dob'], 'ord')}\nLocality = {p['village']}, {p['district']}\n[CLINICAL]\nImpression = {p['dx'][1]}\nRx = {p['drug']}\n",
               ids=[p["phone"], p["uhid"]], names=[p["name"], p["rel"]], preserve=[p["drug"]])
    # 4. JSON arrays-of-arrays with a header row
    sub = pats[40:50]
    rows = [["name", "phone", "age", "dx"]] + [[p["name"], g.fmt_phone(p["phone"]), p["age"], p["dx"][0]] for p in sub]
    g.emit("export/matrix.json", json.dumps({"columns_first": True, "data": rows}, ensure_ascii=False),
           ids=[p["phone"] for p in sub], names=[p["name"] for p in sub], preserve=[p["dx"][0] for p in sub])
    # 5. FHIR with contained Patient and an Applicant-style RelatedPerson
    for k, p in enumerate(pats[50:56]):
        doc = {"resourceType": "Bundle", "type": "collection", "entry": [{"resource": {
            "resourceType": "Claim", "id": f"c{k}", "status": "active",
            "contained": [{"resourceType": "Patient", "id": "pat", "name": [{"family": p["name"].split()[-1], "given": p["name"].split()[:-1]}],
                           "telecom": [{"system": "phone", "value": g.fmt_phone(p["phone"])}]},
                          {"resourceType": "RelatedPerson", "id": "rp", "name": [{"text": p["rel"]}]}],
            "patient": {"reference": "#pat"}, "insurance": [{"sequence": 1, "focal": True, "coverage": {"display": f"Policy {p['uhid']}"}}],
            "diagnosis": [{"sequence": 1, "diagnosisCodeableConcept": {"coding": [{"code": p["dx"][0], "display": p["dx"][1]}]}}]}}]}
        g.emit(f"fhir/claim_{k}.json", json.dumps(doc, indent=1, ensure_ascii=False), ids=[p["phone"], p["uhid"]],
               names=[p["name"], p["rel"]], preserve=[p["dx"][0]])
    # 6. Hinglish narrative letters and SMS notes
    for k, p in enumerate(pats[:12]):
        g.emit(f"letters/ref_{k:02d}.txt",
               f"Dear Dr Sahab,\n{p['name']} ji ko {p['age']} saal ki umar mein bukhar aur khansi hai. Unke bete {p['rel']} ne phone kiya "
               f"({g.fmt_phone(p['phone'])}). Card number {p['uhid']}. Kripya jaanch karein. {p['drug']}.\nRegards\n",
               ids=[p["phone"], p["uhid"]], names=[p["name"], p["rel"]], preserve=[p["drug"]])
        g.emit(f"sms/msg_{k:02d}.txt", f"SMS from {g.fmt_phone(p['phone'])}: appt for {p['name']} on {g.date_fmt(p['adm'], 'dot2')} confirmed",
               ids=[p["phone"]], names=[p["name"]])
    # 7. Devanagari-only names with Devanagari labels (no Latin anywhere)
    for k, p in enumerate(pats[12:20]):
        g.emit(f"hindi/parcha_{k}.txt",
               f"मरीज: {g.devanagari(p['name'])}\nअभिभावक: {g.devanagari(p['rel'])}\nफोन: {g.deva_digits(p['phone'])}\nरोग: {p['dx'][1]}\nदवा: {p['drug']}\n",
               ids=[p["phone"]], names=[p["name"], p["rel"]], preserve=[p["drug"]])
    truth = {"files": g.truth["files"], "canaries": [], "preserve": g.truth["preserve"]}
    out = Path(a.out)
    for rel, data in g.files.items():
        p = out / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
    Path(a.truth).write_text(json.dumps(truth, ensure_ascii=False), encoding="utf-8")
    print(f"unseen-layout files {len(g.files)}")


if __name__ == "__main__":
    main()
