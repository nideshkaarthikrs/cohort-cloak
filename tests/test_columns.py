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
