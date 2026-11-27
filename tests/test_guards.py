from cloak.detect.guards import guard_spans, guarded


def kinds(text):
    return {k for _, _, k in guard_spans(text)}


def covered(text, needle):
    i = text.index(needle)
    return guarded(guard_spans(text), i, i + len(needle))


def test_doctor_names_protected_but_relative_not():
    t = "Dr. Ramesh Srivastava (MD Medicine). W/o Ramesh"
    assert covered(t, "Ramesh Srivastava")
    assert not covered(t, "W/o Ramesh")
    assert covered("डॉ. रमेश श्रीवास्तव ने देखा", "रमेश श्रीवास्तव")


def test_clinical_patterns_protected():
    t = "Tab Amlodipine 5 mg 1-0-1 x 2 wks. BP 150/90, Hb 12.0-16.0 g/dL, ICD N39.0"
    for needle in ["5 mg", "1-0-1", "x 2 wks", "150/90", "12.0-16.0", "N39.0"]:
        assert covered(t, needle), needle


def test_hospital_and_ward_protected():
    assert covered("Sanjeevani Multispeciality Hospital, Lucknow", "Sanjeevani Multispeciality Hospital")
    assert covered("Ward 4 (Medicine) / Bed 29", "Ward 4 (Medicine)")
    assert not covered("Address: Ward 20, Gandhi Nagar", "Ward 20")


def test_history_and_complaint_prefixes():
    assert covered("K/C/O addison's disease", "addison's disease")
    assert covered("H/O TB 8 yrs back", "TB 8 yrs back")
    assert covered("C/O fever x 7 days", "fever x 7 days")
    assert not covered("C/O Ramesh Kumar", "Ramesh Kumar")


def test_asha_worker_protected():
    assert covered("ASHA worker visited", "ASHA worker")


def test_unknown_brand_drug_names_after_a_dosage_form_or_before_a_dose_are_kept():
    from cloak.detect.engine import Scrubber
    from cloak.policy import load_policy
    from pathlib import Path
    sc = Scrubber(load_policy(Path("config/policy.yaml")))
    for t in ("Plan:\n  1. Inj Human Actrapid 4 units before lunch",
              "  Tab Syndopa Plus 1-1-1 (Levodopa 100 mg), 30 min before meals",
              "insulin khud laga rahi hain - Mixtard 18-0-12 daily",
              "Syp Zorbexal Forte 5 ml TDS",
              "Inj. Carboprost 250 mcg IM",
              "Cap Vorlanex Duo 1-0-1"):
        assert sc.scrub_text(t, doc_labels=True)[0] == t, t
    out = sc.scrub_text("Patient Zorbak Quillfeather was given Tab Metformin 500 mg", doc_labels=True)[0]
    assert "Quillfeather" not in out and "Tab Metformin 500 mg" in out
