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
