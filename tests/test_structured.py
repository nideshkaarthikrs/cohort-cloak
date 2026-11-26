"""Role-based rewriting on invented records: CSV, JSON/FHIR, text, hidden channels."""
import base64
import json
import re

from conftest import run_main

CSV_REG = (
    "Reg No,Naam,Umar,Janm Tithi,Mobile No,Pata,Gaon,Jila,Notes\n"
    "ZZH-0012345,Ravi Testkumar,41,12-04-1984,98765 43210,"
    "\"H.No. 7, near Test Mandir, Vill. Fakepur, Tehsil Sadar, Distt. Faketown - 229001\","
    "Fakepur,Faketown,Pt allergic to sulfa\n"
)


NO_K = {"k_min": 1, "rare_dx_max_patients": 0, "dob_mode": "shift", "village_mode": "redact", "tehsil_mode": "keep"}


def _run(tmp_path, files, policy=None):
    inp = tmp_path / "in"
    for rel, data in files.items():
        p = inp / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data if isinstance(data, bytes) else data.encode("utf-8"))
    out = tmp_path / "out"
    res = run_main(inp, out, policy=NO_K if policy is None else policy)
    assert res.returncode == 0, res.stderr
    return out


def _only(out, sub):
    files = [p for p in (out / "sanitized" / sub).rglob("*") if p.is_file()]
    assert len(files) == 1, files
    return files[0].read_text(encoding="utf-8")


def test_csv_hinglish_headers_roles_and_clinical_kept(tmp_path):
    out = _run(tmp_path, {"reg/p.csv": CSV_REG})
    text = _only(out, "reg")
    for leaked in ("Testkumar", "ZZH-0012345", "98765", "43210", "Fakepur", "Test Mandir", "229001", "12-04-1984"):
        assert leaked not in text, leaked
    assert "Naam" in text and "Umar" in text and "40-44" in text
    assert "Tehsil Sadar" in text and "Distt. Faketown" in text and "229***" in text
    assert "sulfa" in text and re.search(r"\d\d-\d\d-198[34]", text)


def test_csv_unknown_column_with_phone_values_is_caught_by_value_profile(tmp_path):
    out = _run(tmp_path, {"x/a.csv": "Qq,Zz\n9876543210,ok\n8081120924,fine\n7286490658,fine\n"})
    text = _only(out, "x")
    assert "9876543210" not in text and "8081120924" not in text and "ok" in text


def test_names_propagate_to_free_text_filenames_and_keys(tmp_path):
    out = _run(tmp_path, {
        "reg/p.csv": "UHID,Patient Name\nZZH-0099001,Ravi Testkumar\n",
        "notes/Note_Ravi_Testkumar_ZZH-0099001.txt": "Ravi sahab ka BP 120/80. Testkumar ji aaye.\n",
        "misc/idx.json": json.dumps({"by_name": {"Ravi Testkumar": {"visits": 2}}}),
    })
    notes = _only(out, "notes")
    assert "Ravi" not in notes and "Testkumar" not in notes and "BP 120/80" in notes
    names = [p.name for p in (out / "sanitized").rglob("*") if p.is_file()]
    assert not any("Ravi" in n or "Testkumar" in n or "0099001" in n for n in names)
    idx = json.loads(_only(out, "misc"))
    assert "Ravi Testkumar" not in json.dumps(idx) and idx["by_name"] is not None


def test_text_discharge_template(tmp_path):
    doc = ("DISCHARGE SUMMARY\n\n"
           "Patient Name: Sita Fakeperson        Age/Sex: 52 Yrs/F\n"
           "UHID: ZZH/26/123456        IPD No: IPD-2026-99999\n"
           "W/o Gopal\n"
           "Address: Makan No. 9, Vill. Nowhere, Tehsil Sadar, Distt. Faketown - 229001\n"
           "Mobile: +91 98765 43210\n"
           "Consultant: Dr. Anil Docname (MD Medicine)\n"
           "Ward/Bed: Ward 4 (Medicine) / Bed 29\n"
           "Diagnosis: Urinary tract infection (N39.0);\n"
           "Medications: Tab Paracetamol 650 mg 1-0-1 x 5 days\n"
           "Attendant: Gopal, Mob. 9876543210\n")
    out = _run(tmp_path, {"d/doc.txt": doc})
    text = _only(out, "d")
    for leaked in ("Sita", "Fakeperson", "123456", "99999", "Gopal", "Nowhere", "98765", "9876543210", "229001"):
        assert leaked not in text, leaked
    assert re.search(r"50-54 Yrs/F", text)
    for kept in ("Dr. Anil Docname (MD Medicine)", "Ward 4 (Medicine) / Bed 29", "N39.0",
                 "650 mg 1-0-1 x 5 days", "Tehsil Sadar"):
        assert kept in text, kept


def test_c_o_trap_complaint_vs_relative(tmp_path):
    doc = "Name: Sita Fakeperson\nC/O fever x 7 days. K/C/O DM. C/O Gopal Testrel, Ward 1\n"
    text = _only(_run(tmp_path, {"d/a.txt": doc}), "d")
    assert "C/O fever x 7 days" in text and "K/C/O DM" in text
    assert "Gopal" not in text and "Testrel" not in text


def test_fhir_patient_fields_and_base64_attachment(tmp_path):
    payload = base64.b64encode("Name: Ravi Testkumar UHID ZZH-0099001 Mobile 9876543210".encode()).decode()
    bundle = {"resourceType": "Bundle", "type": "document", "entry": [
        {"fullUrl": "urn:uuid:123e4567-e89b-12d3-a456-426614174000", "resource": {
            "resourceType": "Patient",
            "identifier": [{"system": "urn:x", "value": "ZZH-0099001", "type": {"coding": [{"code": "MR", "display": "Medical record number"}]}}],
            "name": [{"use": "official", "family": "Testkumar", "given": ["Ravi"], "text": "Ravi Testkumar"}],
            "telecom": [{"system": "phone", "value": "+91 98765 43210"}],
            "birthDate": "1984-04-12",
            "address": [{"line": ["House 5, Ward 3, Mohalla Fake Nagar"], "city": "Fakepur", "district": "Faketown",
                         "state": "UP", "postalCode": "229001"}],
            "contact": [{"relationship": [{"text": "Husband"}], "name": {"text": "Gopal Testrel"}}],
            "extension": [{"url": "https://x.example/StructureDefinition/mothers-name", "valueString": "Asha Testmother"}],
        }},
        {"resource": {"resourceType": "Practitioner", "name": [{"text": "Dr. Anil Docname"}]}},
        {"resource": {"resourceType": "DocumentReference", "content": [{"attachment": {"contentType": "text/plain", "data": payload}}]}},
    ]}
    out = _run(tmp_path, {"f/b.json": json.dumps(bundle)})
    text = _only(out, "f")
    for leaked in ("Ravi", "Testkumar", "ZZH-0099001", "98765", "Gopal", "Testrel", "Asha", "Testmother", "House 5",
                   "Fake Nagar", "229001", "1984-04-12"):
        assert leaked not in text, leaked
    doc = json.loads(text)
    assert doc["resourceType"] == "Bundle"
    assert doc["entry"][0]["fullUrl"] == "urn:uuid:123e4567-e89b-12d3-a456-426614174000"
    assert "Dr. Anil Docname" in text and "Husband" in text
    att = doc["entry"][2]["resource"]["content"][0]["attachment"]["data"]
    decoded = base64.b64decode(att).decode("utf-8")
    assert "Ravi" not in decoded and "9876543210" not in decoded and "ZZH-0099001" not in decoded


def test_json_numeric_pii_becomes_zero_and_key_names_replaced(tmp_path):
    out = _run(tmp_path, {"j/a.json": json.dumps({"patient": {"name": "Ravi Testkumar", "aadhar_no": 826573307111, "age": 41}})})
    doc = json.loads(_only(out, "j"))
    assert doc["patient"]["aadhar_no"] == 0 and doc["patient"]["age"] == "40-44"


def test_clean_documents_unchanged(tmp_path):
    clean = "category,drug,form,strength\nAntibiotic,Amoxicillin,Capsule,500 mg\n"
    out = _run(tmp_path, {"clean/f.csv": clean, "clean/c.json": json.dumps({"wards": [{"ward": "Ward 4", "beds": 30}]}),
                          "clean/p.txt": "Dengue protocol: fluids, monitor platelets 137130 daily.\n"})
    assert (out / "sanitized/clean/f.csv").read_text() == clean
    assert json.loads((out / "sanitized/clean/c.json").read_text()) == {"wards": [{"ward": "Ward 4", "beds": 30}]}
    assert "platelets 137130 daily" in (out / "sanitized/clean/p.txt").read_text()


def test_patient_name_key_inside_clinical_container_is_still_a_patient(tmp_path):
    doc = {"results": [{"patient_name": "Zxq Unseenperson", "uhid": "ZZH-0077001", "test": "Hb", "value": 11.0}]}
    out = _run(tmp_path, {"lab/bulk.json": json.dumps(doc)})
    text = _only(out, "lab")
    assert "Unseenperson" not in text and "ZZH-0077001" not in text and "Hb" in text
