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


def test_cue_spans_stay_fast_and_correct_on_huge_single_lines():
    import time
    from cloak.detect.context import cue_name_spans_typed
    for junk in ("ABCDE" * 20000, "नमस्ते" * 20000, "QUJD" * 25000):
        text = "Patient Asha Verma came. " + junk + " S/o Ramesh Kumar seen."
        t0 = time.monotonic()
        spans = cue_name_spans_typed(text)
        assert time.monotonic() - t0 < 10.0
        found = {text[s:e] for s, e, _k in spans}
        assert "Asha Verma" in found
        assert "Ramesh Kumar" in found


def test_scrubbing_a_huge_line_with_thousands_of_spans_stays_fast():
    import time
    text = "Patient Zorbak Quillfeather. " + "Ram 9876 5012 34 ,PIN 411001 " * 7000
    t0 = time.monotonic()
    out = scrub(text)
    assert time.monotonic() - t0 < 6.0
    assert "9876" not in out and "Quillfeather" not in out


def test_banner_line_name_before_id_and_age_is_found_in_any_script():
    for banner, name in (("आँचल वायलकर   |   SV004810   |   71 वर्ष", "वायलकर"),
                         ("கவின் செல்வரொளி   |   26/VM/4823   |   68 வயது", "செல்வரொளி"),
                         ("Sahithi Vennuri   |   NC-26-4836   |   65 Yrs", "Vennuri"),
                         ("V. Khairuli    UHID SV004828    DOB 20 September 1993", "Khairuli")):
        out = scrub("Some Hospital\nWard record   03/11/2026\n" + banner + "\n\nNote follows.", doc=True)
        assert name not in out, banner


def test_banner_line_rule_leaves_lab_rows_and_hospital_headers_alone():
    for line in ("Serum creatinine      0.9 mg/dL       0.6-1.2 mg/dL",
                 "FINAL REPORT               Page 1 of 1",
                 "Saanvari Community Hospital   |   Laboratory Medicine",
                 "Hospital Billing   |   Ward 3   |   Bed 12",
                 "Admission date   12-Apr-2026   |   Discharge   15-Apr-2026"):
        assert scrub(line, doc=True) == line


def test_the_name_in_a_salutation_goes_even_as_surname_comma_given():
    out = scrub("Dear Mozhivel, Iniyan,\nYour follow-up is booked with Dr Harjit Nerwal.")
    assert "Mozhivel" not in out and "Iniyan" not in out
    assert scrub("Dear Sir,\nPlease find the report.") == "Dear Sir,\nPlease find the report."
    assert scrub("Dear Patient,\nYour visit is booked.") == "Dear Patient,\nYour visit is booked."


def test_a_name_found_by_a_cue_in_one_text_is_known_in_later_texts():
    sc = Scrubber(POLICY)
    sc.scrub_text("Dear Quillfeather,\nSee you soon.", doc_labels=True)
    out, _ = sc.scrub_text("the visit with quillfeather went well, said Quillfeather.", doc_labels=True)
    assert "uillfeather" not in out
    out2, _ = Scrubber(POLICY).scrub_text("the visit with quillfeather went well, said Quillfeather.", doc_labels=True)
    assert "Quillfeather" in out2  # a fresh scrubber knows nothing


def test_hindi_patient_noun_does_not_swallow_ordinary_words_but_still_cues_known_names():
    for t in ("सुबह की पाली में मरीज से बात हुई। रात में आराम मिला।",
              "उपरोक्त मरीज आज हमारे विभाग में जाँच के लिए आए थे।",
              "रोगी की हालत स्थिर है।"):
        assert scrub(t) == t
    assert "राम" not in scrub("मरीज राम को बुखार है।")
    assert "सुमन" not in scrub("श्रीमती सुमन वर्मा आज आईं।")  # an honorific still cues any name
