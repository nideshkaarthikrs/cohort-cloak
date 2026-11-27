import pytest

from cloak.detect.patterns import find_hard
from cloak.detect.validators import verhoeff_ok, phone_core, ascii_digits


def kinds(text):
    return [(text[s.start:s.end], s.kind) for s in find_hard(text)]


@pytest.mark.parametrize("text", [
    "Dolo 650 BD x 5 days", "Tab X 1-0-1 x 2 wks", "BP 150/90 mmHg", "Dose 5 mg", "Range 70-140 mg/dL",
    "Platelets 137130 /cumm", "LOINC 2345-7", "Hb 12.0-16.0 g/dL", "Temp 98.3 F", "SpO2 97%",
    "Dated 07/02/2026 and 2026-02-19", "N39.0 and E27.1", "Visit 5 September",
])
def test_doses_vitals_dates_are_not_identifiers(text):
    assert find_hard(text) == []


@pytest.mark.parametrize("text,surface", [
    ("Mobile: 060062-72163", "060062-72163"),
    ("call +91 72864 90658 now", "+91 72864 90658"),
    ("ph 8081120924.", "8081120924"),
    ("+91-6886287537", "+91-6886287537"),
    ("by Kaveri 94054-71434", "94054-71434"),
    ("75600-10034", "75600-10034"),
    ("फोन ७८८८०२३९२३ पर", "७८८८०२३९२३"),
])
def test_phone_forms(text, surface):
    assert (surface, "PHONE") in kinds(text)


def test_aadhaar_forms():
    assert ("8265 7330 7111", "AADHAAR") in kinds("Aadhaar 8265 7330 7111")
    assert ("826573307111", "AADHAAR") in kinds("id 826573307111")
    assert ("XXXX XXXX 5866", "AADHAAR") in kinds("Aadhaar XXXX XXXX 5866")
    assert ("९७९५ ९९७३ ०१३१", "AADHAAR") in kinds("आधार ९७९५ ९९७३ ०१३१")


def test_abha_pan_email_insurance():
    assert ("91-7938-3729-8403", "ABHA") in kinds("ABHA 91-7938-3729-8403")
    assert ("DCSPS3454E", "PAN") in kinds("PAN DCSPS3454E")
    assert ("a.b@example.org", "EMAIL") in kinds("mail a.b@example.org ok")
    assert ("rahul@abdm", "ABHA") in kinds("addr rahul@abdm")
    assert ("PMJAY-UP-1234567890", "INSURANCE") in kinds("id PMJAY-UP-1234567890")


def test_labelled_ids():
    got = kinds("UHID: SNJ/26/064508  IPD No: IPD-2026-00461 Reg No: 0077305")
    assert ("SNJ/26/064508", "ID") in got
    assert ("IPD-2026-00461", "ID") in got
    assert ("0077305", "ID") in got
    assert ("पंजीकरण सं.: JJH-77", "ID") not in got
    assert any(k == "ID" for _, k in kinds("पंजीकरण सं.: JJH-0077305"))


def test_transactional_ids_kept():
    assert find_hard("Bill No: B-2026-00456 sample S-001234") == []


def test_ascii_digits_and_core():
    assert ascii_digits("७८८८०२३९२३") == "7888023923"
    assert phone_core("+91 72864-90658") == "7286490658"
    assert phone_core("060062-72163") == "6006272163"
    assert phone_core("12345") is None


def test_verhoeff():
    assert verhoeff_ok("2363")
    assert not verhoeff_ok("2364")


def test_induced_shapes_do_not_match_words_plus_year():
    from cloak.detect.ids import IdSet
    ids = IdSet()
    for v in ["DCSPS3454E", "ABHA-ABDM-1234", "SNJ/26/064127", "UHID-010610"]:
        ids.add(v)
    assert ids.find("extracts for January-November 2026.") == []
    assert ids.find("file SNJ-26-099999 here") != []


def test_find_hard_is_linear_on_a_very_long_token():
    import time
    from cloak.detect.patterns import find_hard
    text = "Contact ravi.k@abdm and x@example.org " + "a" * 150000 + " 9876501234"
    t0 = time.monotonic()
    spans = find_hard(text)
    assert time.monotonic() - t0 < 2.0
    kinds = sorted(s.kind for s in spans)
    assert kinds == ["ABHA", "EMAIL", "PHONE"]


def test_parenthesised_area_code_phone_is_found_but_a_range_is_not():
    from cloak.detect.patterns import find_hard
    for raw in ("(784) 401-7364", "(784)401-7364", "(784) 4017364"):
        spans = find_hard(f"call {raw} today")
        assert [s.kind for s in spans] == ["PHONE"], raw
    assert find_hard("BP (120) 80-90 mmHg") == []


def test_labelled_aadhaar_with_stray_scanner_spaces_and_letters():
    for raw in ("UID 6435 I  969 989O", "Aadhaar: 6484 8  2I4 7676", "UID 64II I  456 335I"):
        spans = find_hard("A note carried " + raw + ", then more")
        assert [s.kind for s in spans] == ["AADHAAR"], raw
    assert find_hard("UID 1234 5") == []  # too short
    assert find_hard("dose 6435 I 969 989O mg") == []  # no Aadhaar label nearby


def test_explicit_country_code_makes_any_ten_digits_a_phone_but_bare_numbers_still_need_6_to_9():
    assert phone_core("+91 55518 03410") == "5551803410"
    assert phone_core("+91-55518-03410") == "5551803410"
    assert phone_core("0091 55518 03410") == "5551803410"
    assert phone_core("55518 03410") is None
    assert phone_core("0 55518 03410") is None
    assert phone_core("+91 98765 43210") == "9876543210"
    assert [s.kind for s in find_hard("Contact +91 55518 03720 today")] == ["PHONE"]


def test_ten_digits_after_a_phone_label_are_a_phone_whatever_the_first_digit():
    for t in ("D/o Renu   Mob 55518-03410", "Contact: 55518 03410", "Tel 05551803410", "Phone no. 5551803410 ok", "whatsapp 55518-03410"):
        assert [s.kind for s in find_hard(t)] == ["PHONE"], t
    for t in ("Lot no 5551803410", "Dose 5551803410", "Ref 55518 03410", "Bill 5551803410 paid"):
        assert find_hard(t) == [], t


def test_insurance_and_card_labels_in_hindi_and_english_anchor_an_id():
    for t in ("आयुष्मान कार्ड: K7R2M94PX", "आयुष्मान आई.डी.: W2F6K9N3D", "आयुष्मान आईडी K7R2M94PX",
              "PM-JAY : M3T8K5Q2W", "PMJAY ID: M3T8K5Q2W", "Ayushman Card No: K7R2M94PX", "Beneficiary ID K7R2M94PX",
              "Insurance No: K7R2M94PX", "Policy No: K7R2M94PX", "Member ID: K7R2M94PX", "बीमा आईडी: K7R2M94PX",
              "पंजीयन क्र. CHC3471X", "भर्ती क्र.: IPD24X1187"):
        assert [s.kind for s in find_hard(t)] == ["ID"], t
    for t in ("आयुष्मान योजना में भर्ती", "Insurance covered the stay", "Policy review done", "card given to patient"):
        assert find_hard(t) == [], t
