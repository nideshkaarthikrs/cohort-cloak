"""Behaviours added after the unseen-layout run: layouts and cues the first detectors missed (invented names)."""
import json

from cloak.detect.engine import Scrubber
from cloak.policy import load_policy
from conftest import run_main
from pathlib import Path

POLICY = load_policy(Path(__file__).resolve().parent.parent / "config" / "policy.yaml")


def scrub(text, doc=False):
    return Scrubber(POLICY).scrub_text(text, doc_labels=doc)[0]


def run(tmp_path, files):
    inp = tmp_path / "in"
    for rel, data in files.items():
        (inp / rel).parent.mkdir(parents=True, exist_ok=True)
        (inp / rel).write_text(data, encoding="utf-8")
    out = tmp_path / "out"
    assert run_main(inp, out, "s", {"k_min": 1, "rare_dx_max_patients": 0}).returncode == 0
    return {p.name: p.read_text(encoding="utf-8") for p in (out / "sanitized").rglob("*") if p.is_file()}


def test_equals_labels_and_unseen_label_words():
    out = scrub("[PATIENT]\nApplicant = Zorbek Quillfaster\nGuardian = Tanvir Plimsoll\nCard = ZZH-0001234\nBorn = 5th Mar 1980",
                doc=True)
    assert "Zorbek" not in out and "Tanvir" not in out and "ZZH-0001234" not in out and "1980" not in out or "Mar 1980" not in out


def test_csv_with_title_rows_above_the_header(tmp_path):
    csv = ("REGISTER - Some Hospital\nMonth: March 2026,,\nBeneficiary,Medicine,Contact\n"
           "Zorbek Quillfaster,Tab Metformin 500 mg 1-0-1,9876501234\nTanvir Plimsoll,Cap Omeprazole 20 mg,9876501235\nTOTAL,2,\n")
    out = run(tmp_path, {"p/reg.csv": csv})["reg.csv"]
    assert "Zorbek" not in out and "Plimsoll" not in out and "9876501234" not in out
    assert "Tab Metformin 500 mg 1-0-1" in out and "Beneficiary" in out


def test_hinglish_letter_and_cue_only_names():
    out = scrub("Zorbek Quillfaster ji ko 40 saal ki umar mein bukhar hai. Unke bete Tanvir Plimsoll ne phone kiya.")
    assert "Zorbek" not in out and "Quillfaster" not in out and "Tanvir" not in out and "Plimsoll" not in out
    assert "bukhar" in out


def test_two_unknown_capitalised_words_fail_closed_but_clinical_phrases_survive():
    assert "Zorbek" not in scrub("appt for Zorbek Quillfaster on 5 March")
    for t in ["Urinary Tract Infection treated", "Chronic Kidney Disease stage 3", "Acute Bronchitis", "Review After Two Weeks",
              "Type 2 Diabetes Mellitus Without Complications", "Gastroenteritis Unspecified"]:
        assert scrub(t) == t, t


def test_array_of_arrays_json_with_header_row(tmp_path):
    doc = {"data": [["name", "phone", "dx"], ["Zorbek Quillfaster", "9876501234", "I10"]]}
    out = run(tmp_path, {"j/m.json": json.dumps(doc)})["m.json"]
    assert "Zorbek" not in out and "9876501234" not in out


def test_devanagari_labels_without_any_latin_names(tmp_path):
    out = run(tmp_path, {"h/p.txt": "मरीज: ज़ोरबेक क्विलफ़ास्टर\nअभिभावक: तनवीर प्लिमसोल\nफोन: ९८७६५०१२३४\nदवा: Tab Metformin 500 mg\n"})["p.txt"]
    assert "ज़ोरबेक" not in out and "तनवीर" not in out and "९८७६५०१२३४" not in out and "Tab Metformin 500 mg" in out
