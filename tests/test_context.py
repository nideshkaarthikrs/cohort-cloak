"""Meaning traps and context cues, run with an EMPTY known-name dictionary (generalisation view)."""
import pytest

from cloak.detect.engine import Scrubber
from cloak.policy import load_policy
from pathlib import Path

POLICY = load_policy(Path(__file__).resolve().parent.parent / "config" / "policy.yaml")


def scrub(text, doc=False):
    out, _ = Scrubber(POLICY).scrub_text(text, doc_labels=doc)
    return out


def test_c_o_relative_vs_complaint():
    assert "Ramesh" not in scrub("C/O Ramesh Kumar, Ward 20")
    assert "C/O fever x 7 days" in scrub("C/O fever x 7 days")
    assert "C/O headache and giddiness x 9 days" in scrub("C/O headache and giddiness x 9 days")


def test_doctor_kept_relative_removed():
    out = scrub("Seen by Dr. Ramesh Srivastava. W/o Ramesh Gupta")
    assert "Dr. Ramesh Srivastava" in out and "Gupta" not in out


def test_relation_markers_remove_names():
    assert "Zubair" not in scrub("Attendant (S/o Zubair) informed")
    assert "Zubair" not in scrub("Attendant (S/o zubair) informed")
    assert "Naseem" not in scrub("W/o Naseem")


def test_history_and_eponyms_kept():
    out = scrub("K/C/O addison's disease. Parkinson's disease on follow up. H/O TB 8 yrs back")
    assert "addison's disease" in out and "Parkinson's disease" in out and "TB 8 yrs back" in out


def test_ward_and_asha():
    assert "Ward 4 (Medicine) / Bed 29" in scrub("Ward/Bed: Ward 4 (Medicine) / Bed 29", doc=True)
    assert "ASHA worker" in scrub("ASHA worker visited the home")
    out = scrub("Address: Makan No. 5, Ward 20, Gandhi Nagar, Distt. Hardoi - 241001", doc=True)
    assert "Ward 20" not in out and "Distt. Hardoi" in out


def test_honorific_and_hinglish_cues():
    assert "Shahid" not in scrub("Shahid sahab ka BP 117/82, pulse 106")
    assert "117/82" in scrub("Shahid sahab ka BP 117/82")
    assert "Asha" not in scrub("Asha ji 48 Y / F, Dolo 650 BD x 5 days")
    assert "Dolo 650 BD x 5 days" in scrub("Asha ji 48 Y / F, Dolo 650 BD x 5 days")
    assert "Kamal" not in scrub("Kamal Bhaiya ne bataya")


def test_whatsapp_sender_and_near_phone():
    out = scrub("[30/05/26, 9:32 pm] Kamal Bhaiya: report bhej do\n[30/05/26, 9:40 pm] Sunil Testsurname: ok")
    assert "Kamal" not in out and "Testsurname" not in out
    out = scrub("called by Kaveri Nambiar 94054-71434 at gate")
    assert "Kaveri" not in out and "Nambiar" not in out and "94054" not in out
    out = scrub("Zorawar Qadri (attendant, bed 12), mob 98765 43210")
    assert "Zorawar" not in out and "Qadri" not in out and "98765" not in out


def test_gazetteer_two_tokens_and_particle():
    assert "Meena" not in scrub("Meena Verma was admitted with fever")
    assert "Meena" not in scrub("Meena ko bukhar hai")
    assert "Verma" not in scrub("Meena Verma was admitted with fever")
    # single capitalised gazetteer word without context stays (could be a common word)
    assert "fever" in scrub("Meena Verma was admitted with fever")


def test_medical_words_not_names():
    for t in ["Tab Paracetamol 650 mg BD", "Diagnosis: Type 2 Diabetes Mellitus", "Rx Amlodipine 5 mg",
              "Patient presented with Chest Pain and Shortness of breath", "Urinary Tract Infection treated"]:
        assert scrub(t) == t, t


def test_devanagari_names_by_cue_and_gazetteer():
    assert "रमेश" not in scrub("श्री रमेश कुमार को भर्ती किया गया")
    assert "श्याम" not in scrub("पुत्र श्याम लाल")
    out = scrub("सुनीता देवी को 9 दिन से बुखार है।")
    assert "सुनीता" not in out and "9 दिन से बुखार है" in out


def test_unseen_names_caught_by_cues_only():
    cases = {
        "Patient Dhruvan Mehrotra admitted with fever x 3 days.": ("Dhruvan", "Mehrotra"),
        "Dhruvan ko bukhar hai.": ("Dhruvan",),
        "Dhruvan's mother called from 9876501234.": ("Dhruvan", "9876501234"),
        "Visitor: Tanvir Quasimi (bed 4) 98765-01234": ("Tanvir", "Quasimi"),
        "Rahul ne bataya ki sugar 140 hai": ("Rahul",),
        "Next of kin Ishaan Trivedi to collect reports.": ("Ishaan", "Trivedi"),
    }
    for text, leaked in cases.items():
        out = scrub(text)
        assert not any(w in out for w in leaked), (text, out)
    assert "fever x 3 days" in scrub("Patient Dhruvan Mehrotra admitted with fever x 3 days.")
    assert "sugar 140 hai" in scrub("Rahul ne bataya ki sugar 140 hai")


def test_generic_words_after_patient_and_particles_kept():
    t = "Review after 2 weeks. Patient ne dawai li. Doctor ne dekha. Mother ko bataya."
    assert scrub(t) == t
    assert scrub("Referred to Dr. Anil Kapoor for opinion") == "Referred to Dr. Anil Kapoor for opinion"
