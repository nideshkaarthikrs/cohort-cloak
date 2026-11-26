from cloak.detect.columns import header_role, infer_roles, norm_header


def test_norm_header():
    assert norm_header("Patient's Name") == "patient s name"
    assert norm_header("PatientID") == "patient id"
    assert norm_header("aadhar_no") == "aadhar no"
    assert norm_header("DOB (MM/DD/YYYY)") == "dob mm dd yyyy"


def test_header_roles_across_vocabularies():
    cases = {
        "Patient Name": "patient_name", "Patient's Name": "patient_name", "Naam": "patient_name",
        "Name": "patient_name", "नाम": "patient_name", "FirstName": "patient_name", "LastName": "patient_name",
        "Mobile No": "phone", "Contact#": "phone", "Phone": "phone", "Mob": "phone",
        "Aadhar": "aadhaar", "aadhar_no": "aadhaar", "Aadhaar No": "aadhaar", "UID": "aadhaar",
        "ABHA No": "abha", "UHID": "mrn", "Reg No": "mrn", "PatientID": "mrn", "hospital_uhid": "mrn",
        "Relative Name": "relative_name", "Guardian": "relative_name", "Pita/Pati ka Naam": "relative_name",
        "Address": "address", "Pata": "address", "Street": "address",
        "Village/Mohalla": "village", "Gaon": "village", "Gram/Mohalla": "village", "City": "village",
        "PIN": "pin", "Pin Code": "pin", "Zip": "pin",
        "DOB": "dob", "Janm Tithi": "dob", "DOB (MM/DD/YYYY)": "dob", "Date of Birth": "dob",
        "Age": "age", "Umar": "age", "age_sex": "age_sex", "Gender": "gender", "Ling": "gender", "Sex": "gender",
        "District": "district", "Jila": "district", "Tehsil": "tehsil",
        "payer_pan": "pan", "pmjay_id": "insurance", "policy_no": "insurance", "Email": "email",
        "ref_doctor": "doctor", "doctor": "doctor", "referred_by": "doctor",
        "complaints": "clinical", "diagnosis": "clinical", "result": "clinical", "Notes": "free_text",
        "remarks": "free_text", "bill_no": "id_txn", "sample_id": "id_txn", "Relation": "relation",
    }
    for h, role in cases.items():
        assert header_role(h)[0] == role, (h, header_role(h))


def test_unknown_header_has_no_role():
    assert header_role("Zxqv")[0] is None


def test_value_profile_overrides_header_for_hard_roles():
    header = ["Col A", "Col B", "Col C"]
    rows = [["9876543210", "Invented Person", "x"], ["8081120924", "Another Person", "y"],
            ["+91 72864 90658", "Third Person", "z"]]
    roles = infer_roles(header, rows)
    assert roles[0] == "phone"
    assert roles[1] == "patient_name"


def test_shifted_name_values_stay_name_role():
    header = ["LastName", "FirstName"]
    rows = [["Patel", "Ashok"], ["", "Mohammad Shahid"], ["Lodhi", "Dinesh"]]
    assert infer_roles(header, rows) == ["patient_name", "patient_name"]


def test_header_says_notes_but_values_are_phones():
    rows = [["9876543210"], ["8081120924"], ["7286490658"]]
    assert infer_roles(["Notes"], rows) == ["phone"]


def test_c_o_and_k_c_o_labels_are_clinical_not_relative():
    assert header_role("C/O")[0] != "relative_name" and header_role("K/C/O")[0] != "relative_name"
    assert header_role("S/D/W of")[0] == "relative_name"


def test_a_name_header_with_a_non_person_qualifier_is_not_a_person_column():
    from cloak.detect.columns import header_role
    for h in ("Generic name", "Drug name", "Test name", "Item name", "Service name", "Brand name", "Ward name",
              "Product name", "Name of drug", "Name of test", "Tablet name", "Vendor name", "Panel name"):
        assert header_role(h)[0] != "patient_name", h
    for h in ("Name", "Patient name", "Name (as per ID)", "Full name", "Applicant name", "Name of patient", "Beneficiary name"):
        assert header_role(h)[0] == "patient_name", h


def test_unknown_header_column_of_repeating_record_numbers_is_an_id_column():
    from cloak.detect.columns import infer_roles
    body = [["x", "TC/KA/3391"], ["y", "TC/KA/3391"], ["z", "TC/KA/3418"], ["w", "TC/KA/3418"], ["v", "TC/KA/3418"]]
    assert infer_roles(["a", "ಕ್ರ.ಸಂ."], body)[1] == "mrn"
    wards = [["x", "ICU-4"], ["y", "ICU-4"], ["z", "W-12"], ["w", "W-12"], ["v", "ICU-4"]]
    assert infer_roles(["a", "b"], wards)[1] is None
    batch = [["x", "B2026"], ["y", "B2026"], ["z", "B2026"], ["w", "B2026"], ["v", "B2026"]]
    assert infer_roles(["a", "b"], batch)[1] is None
