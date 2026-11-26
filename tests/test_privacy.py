"""Privacy layer end to end on invented patients: date shifts, bands, rare diagnoses, location, DOB."""
import datetime as dt
import json
import re

from cloak.privacy.dates import find_dates
from conftest import run_main

POLICY = {"k_min": 1, "rare_dx_max_patients": 0, "dob_mode": "shift", "village_mode": "redact", "tehsil_mode": "keep",
          "pin_mode": "prefix3", "age_band_years": 5}

PEOPLE = [  # name, uhid, age, gender, village, dx code, dx text
    ("Asha Gupta", "ZZH-000001", 48, "F", "Fakepur", "E11.9", "Type 2 diabetes"),
    ("Ramesh Verma", "ZZH-000002", 61, "M", "Nowhere", "E11.9", "Type 2 diabetes"),
    ("Sita Devi", "ZZH-000003", 33, "F", "Elsewhere", "E11.9", "Type 2 diabetes"),
    ("Mohan Lal", "ZZH-000004", 52, "M", "Faraway", "E11.9", "Type 2 diabetes"),
    ("Kavita Rao", "ZZH-000005", 40, "F", "Fakepur", "E27.1", "Adrenocortical insufficiency"),
]


def make(root, adm=("07/02/2026", "19/02/2026")):
    (root / "r").mkdir(parents=True)
    rows = ["UHID,Patient Name,Age,Gender,Village,District,Tehsil,PIN,DOB,Reg Date"]
    for i, (n, u, age, g, v, _c, _t) in enumerate(PEOPLE):
        rows.append(f"{u},{n},{age},{g},{v},Faketown,Sadar,229001,12/04/{2026 - age},0{i + 1}/03/2025")
    (root / "r" / "reg.csv").write_text("\n".join(rows) + "\n", encoding="utf-8")
    visits = [{"patient_ref": u, "patient": {"name": n, "age_sex": f"{age + 1}/{g}"}, "visit_date": f"2026-0{i + 2}-15",
               "diagnosis": [{"code": c, "display": t}]} for i, (n, u, age, g, _v, c, t) in enumerate(PEOPLE)]
    (root / "r" / "visits.json").write_text(json.dumps({"visits": visits}), encoding="utf-8")
    for i, (n, u, age, g, _v, c, t) in enumerate(PEOPLE):
        (root / "r" / f"ds_{i}.txt").write_text(
            f"Patient Name: {n}   Age/Sex: {age} Yrs/{g}\nUHID: {u}\nDate of Admission: {adm[0]}\nDate of Discharge: {adm[1]}\n"
            f"Diagnosis: {t} ({c});\nVisit: 5 September\n", encoding="utf-8")


def run(tmp_path, policy=None, secret="s1", name="o"):
    inp = tmp_path / "in"
    if not inp.exists():
        make(inp)
    out = tmp_path / name
    res = run_main(inp, out, secret, policy or POLICY)
    assert res.returncode == 0, res.stderr
    return out


def read(out, rel):
    return (out / "sanitized" / rel).read_text(encoding="utf-8")


def first_dates(text, order="dmy"):
    return [t.as_date(2026) for t in find_dates(text, order)]


def test_stay_length_and_shift_consistent_per_patient_and_distinct_across_patients(tmp_path):
    out = run(tmp_path)
    shifts = {}
    for i in range(5):
        d = first_dates(read(out, f"r/ds_{i}.txt"))
        assert (d[1] - d[0]).days == 12  # stay length exact
        shifts[i] = (d[0] - dt.date(2026, 2, 7)).days
        assert shifts[i] != 0
        # the registration row of the same patient moved by the same amount
        reg = read(out, "r/reg.csv").splitlines()[i + 1]
        regd = first_dates(reg)[-1]
        assert (regd - dt.date(2025, 3, i + 1)).days == shifts[i], i
        # and the OPD visit, in ISO format
        v = json.loads(read(out, "r/visits.json"))["visits"][i]["visit_date"]
        assert (dt.date.fromisoformat(v) - dt.date(2026, i + 2, 15)).days == shifts[i]
    assert len(set(shifts.values())) > 1


def test_different_secret_changes_shifts(tmp_path):
    a, b = run(tmp_path, secret="s1", name="oa"), run(tmp_path, secret="s2", name="ob")
    da, db = first_dates(read(a, "r/ds_0.txt")), first_dates(read(b, "r/ds_0.txt"))
    assert da != db


def test_no_year_date_stays_in_shape(tmp_path):
    out = run(tmp_path)
    assert re.search(r"Visit: \d{1,2} [A-Z][a-z]+\n", read(out, "r/ds_0.txt"))


def test_bands_truthful_and_cluster_consistent(tmp_path):
    out = run(tmp_path)
    reg = read(out, "r/reg.csv").splitlines()[1]          # age 48
    visit = json.loads(read(out, "r/visits.json"))["visits"][0]["patient"]["age_sex"]   # 49/F
    ds = read(out, "r/ds_0.txt")
    bands = set(re.findall(r"(\d+)-(\d+)", reg.split(",")[2])) | set(re.findall(r"(\d+)-(\d+)", visit)) \
        | set(re.findall(r"(\d+)-(\d+) Yrs", ds))
    assert len(bands) == 1
    lo, hi = map(int, next(iter(bands)))
    assert lo <= 48 and hi >= 49 and hi - lo >= 4


def test_dob_modes(tmp_path):
    shifted = read(run(tmp_path, dict(POLICY, dob_mode="shift"), name="o1"), "r/reg.csv").splitlines()[1]
    assert "12/04/1978" not in shifted and re.search(r"\d\d/\d\d/197[78]", shifted)
    year = read(run(tmp_path, dict(POLICY, dob_mode="year"), name="o2"), "r/reg.csv").splitlines()[1]
    assert ",1978," in year
    red = read(run(tmp_path, dict(POLICY, dob_mode="redact"), name="o3"), "r/reg.csv").splitlines()[1]
    assert "[DOB]" in red and "1978" not in red


def test_rare_diagnosis_generalised_everywhere_for_that_patient_only(tmp_path):
    out = run(tmp_path, dict(POLICY, rare_dx_max_patients=2), name="o4")
    rare = read(out, "r/ds_4.txt")
    assert "E27.1" not in rare and "Adrenocortical" not in rare and "E00-E90" in rare
    visit = json.loads(read(out, "r/visits.json"))["visits"][4]["diagnosis"][0]
    assert visit["code"] == "E00-E90" and "Adrenocortical" not in json.dumps(visit)
    common = read(out, "r/ds_0.txt")
    assert "E11.9" in common and "Type 2 diabetes" in common


def test_k_anonymity_widens_bands_and_hides_district_for_unique_people(tmp_path):
    out = run(tmp_path, dict(POLICY, k_min=3), name="o5")
    reg = read(out, "r/reg.csv").splitlines()[1:]
    widths = []
    for line in reg:
        m = re.search(r"(\d+)-(\d+)", line.split(",")[2])
        widths.append(int(m.group(2)) - int(m.group(1)) + 1)
    assert max(widths) >= 10
    joined = "".join(reg)
    assert "Faketown" not in joined and "[DISTRICT]" in joined  # 5 people cannot form cells of 3 by district


def test_location_modes(tmp_path):
    out = run(tmp_path, dict(POLICY, village_mode="district", tehsil_mode="district"), name="o6")
    row = read(out, "r/reg.csv").splitlines()[1].split(",")
    assert "Fakepur" not in ",".join(row) and "Faketown" in row  # village generalised to the record's district
    assert "229***" in ",".join(row)
    out = run(tmp_path, dict(POLICY, village_mode="redact", pin_mode="redact"), name="o7")
    row = read(out, "r/reg.csv").splitlines()[1]
    assert "[VILLAGE]" in row and "[PIN]" in row


def test_iso_week_and_vitamin_are_not_icd_codes(tmp_path):
    from cloak.privacy.suppress import ICD_RX
    for t in ["week 2026-W44", "Vitamin B12 low", "ref 2345-7", "SNJ-W12"]:
        assert not ICD_RX.search(t), t
    assert ICD_RX.search("Diagnosis: Pneumonia (J18.9);") and ICD_RX.search("E27.1")


def test_fhir_birthdate_redaction_keeps_the_bundle_valid(tmp_path):
    bundle = {"resourceType": "Bundle", "type": "document", "entry": [
        {"resource": {"resourceType": "Patient", "id": "p1", "name": [{"text": "Asha Gupta"}], "birthDate": "1978-04-12",
                      "identifier": [{"value": "ZZH-000001"}]}}]}
    inp = tmp_path / "in"
    (inp / "f").mkdir(parents=True)
    (inp / "f" / "b.json").write_text(json.dumps(bundle), encoding="utf-8")
    out = tmp_path / "o"
    assert run_main(inp, out, "s", dict(POLICY, dob_mode="redact")).returncode == 0
    pat = json.loads((out / "sanitized/f/b.json").read_text())["entry"][0]["resource"]
    assert "birthDate" not in pat and pat["_birthDate"]["extension"][0]["valueCode"] == "masked"
    assert run_main(inp, tmp_path / "o2", "s", dict(POLICY, dob_mode="year")).returncode == 0
    assert json.loads((tmp_path / "o2/sanitized/f/b.json").read_text())["entry"][0]["resource"]["birthDate"] == "1978"


def test_dates_inside_encoded_payloads_are_shifted_like_plain_dates(tmp_path):
    import base64
    from urllib.parse import quote, unquote
    inp = tmp_path / "in"
    make(inp)
    note = "Admitted 07/02/2026 and discharged 19/02/2026 for review."
    (inp / "r" / "att.json").write_text(json.dumps({"visits": [
        {"patient_ref": "ZZH-000001", "patient": {"name": "Asha Gupta"}, "visit_date": "2026-02-15",
         "attachment": base64.b64encode(note.encode()).decode(), "memo": quote(note, safe="")}]}), encoding="utf-8")
    out = tmp_path / "o"
    assert run_main(inp, out, "s1", POLICY).returncode == 0
    doc = json.loads((out / "sanitized" / "r" / "att.json").read_text(encoding="utf-8"))
    v = doc["visits"][0]
    for text in (base64.b64decode(v["attachment"]).decode(), unquote(v["memo"])):
        found = re.findall(r"\d\d/\d\d/\d{4}", text)
        assert len(found) == 2 and "07/02/2026" not in text and "19/02/2026" not in text
        a, b = (dt.datetime.strptime(x, "%d/%m/%Y") for x in found)
        assert (b - a).days == 12
