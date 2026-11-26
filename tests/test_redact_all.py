from cloak.rewrite.apply import redact_json, redact_csv_rows, redact_text, safe_key


def test_json_strings_redacted_numbers_kept():
    out, n = redact_json({"name": "Invented Person", "age": 41, "ok": True, "x": None,
                          "tags": ["a", "b"], "phone": 9876543210, "f": 1.5})
    assert out == {"name": "[REDACTED]", "age": 41, "ok": True, "x": None,
                   "tags": ["[REDACTED]", "[REDACTED]"], "phone": 0, "f": 1.5}
    assert n >= 4


def test_json_pii_keys_replaced_and_collisions_suffixed():
    out, _ = redact_json({"Vikas Kumar": 1, "Zainab Bi": 2, "visits": 3, "JJH-0077112": 4})
    assert "Vikas Kumar" not in out and "JJH-0077112" not in out
    assert out["visits"] == 3
    assert len(out) == 4


def test_fhir_structure_preserved():
    out, _ = redact_json({"resourceType": "Bundle", "entry": [
        {"fullUrl": "urn:uuid:123e4567-e89b-12d3-a456-426614174000",
         "resource": {"resourceType": "Patient", "name": [{"text": "Invented Person"}]}}]})
    assert out["resourceType"] == "Bundle"
    assert out["entry"][0]["fullUrl"] == "urn:uuid:123e4567-e89b-12d3-a456-426614174000"
    assert out["entry"][0]["resource"]["resourceType"] == "Patient"
    assert out["entry"][0]["resource"]["name"][0]["text"] == "[REDACTED]"


def test_csv_header_kept_unless_pii_shaped():
    header, rows, _ = redact_csv_rows(["Patient Name", "JJH-0077112 Zainab", "Age"],
                                      [["Invented Person", "x", ""], ["a"]])
    assert header[0] == "Patient Name" and header[2] == "Age"
    assert "0077112" not in header[1]
    assert rows[0] == ["[REDACTED]", "[REDACTED]", ""]
    assert rows[1] == ["[REDACTED]"]


def test_text_lines_redacted_structure_kept():
    out, n = redact_text("Name: Invented Person\n\nline two\n")
    assert out == "[REDACTED]\n\n[REDACTED]\n"
    assert n == 2


def test_safe_key():
    assert safe_key("visit_date") and safe_key("resourceType") and safe_key("_export_meta")
    assert not safe_key("Vikas Kumar") and not safe_key("9876543210")
