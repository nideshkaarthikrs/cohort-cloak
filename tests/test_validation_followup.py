"""Independent-set regressions, using newly invented values rather than corpus identities."""
from cloak.detect.ids import IdSet
from cloak.rewrite.filenames import sanitize_path
from cloak.detect.engine import Scrubber
from cloak.policy import DEFAULTS
from cloak.rewrite.structured import scrub_unknown


def test_known_segmented_id_is_removed_before_filename_token_splitting():
    ids=IdSet();ids.add("ZX24-Q07-5836")
    out=sanitize_path("register_Zorvila_Kelmari_ZX24-Q07-5836.csv",ids=ids)
    assert "ZX24-Q07-5836" not in out


def test_date_only_report_filename_is_preserved():
    assert sanitize_path("reports/OPD_2026_05.json",ids=IdSet())=="reports/OPD_2026_05.json"


def test_medical_institute_and_referral_centre_are_not_patient_names():
    for value in ["Linden Star Medical Institute","Azure Fern Referral Centre","Azure Fern Referral Center"]:
        scrubber=Scrubber(dict(DEFAULTS))
        assert scrub_unknown(scrubber,value)[0]==value


def test_cr_only_case_notes_do_not_swallow_later_clinical_lines():
    text="Patient Name: Zorvila Kelmari\rMetformin 500 mg PO twice daily\rBP 122/78 mmHg\r"
    scrubber=Scrubber(dict(DEFAULTS))
    result,_=scrubber.scrub_text(text,doc_labels=True)
    assert "Zorvila" not in result and "Metformin 500 mg PO twice daily" in result and "BP 122/78 mmHg" in result
    assert result.count("\r")==text.count("\r")


def test_multi_identity_unit_is_not_claimed_as_one_patient():
    from cloak.keys import Keys
    from cloak.link.units import link_units
    result=[("batch.txt","synthetic",b"data",["doc"],None)]
    events=[(0,"doc","patient_name","Zorvila Kelmari"),(0,"doc","aadhaar","734522667891"),(0,"doc","aadhaar","845633778902")]
    mapping,_,stats=link_units(result,events,Keys(b"synthetic-test"),dict(DEFAULTS))
    assert mapping[(0,"doc")] is None and stats["ambiguous_units"]==1


def test_repeated_format_of_same_unique_id_does_not_block_linking():
    from cloak.keys import Keys
    from cloak.link.units import link_units
    result=[("case.txt","synthetic",b"data",["doc"],None)]
    events=[(0,"doc","patient_name","Zorvila Kelmari"),(0,"doc","aadhaar","734522667891"),(0,"doc","aadhaar","7345 2266 7891")]
    mapping,_,stats=link_units(result,events,Keys(b"synthetic-test"),dict(DEFAULTS))
    assert mapping[(0,"doc")] and stats["ambiguous_units"]==0


def test_multi_patient_bundle_is_exported_without_a_false_single_patient_claim(tmp_path):
    import json
    from conftest import run_main
    inp=tmp_path/"in";inp.mkdir()
    bundle={"resourceType":"Bundle","type":"collection","entry":[
        {"resource":{"resourceType":"Patient","id":"p1","name":[{"text":"Zorvila Kelmari"}]}},
        {"resource":{"resourceType":"Patient","id":"p2","name":[{"text":"Talriva Dorneli"}]}}]}
    (inp/"batch.json").write_text(json.dumps(bundle),encoding="utf-8")
    out=tmp_path/"out";assert run_main(inp,out).returncode==0
    records=[json.loads(x) for x in (out/"records.jsonl").read_text().splitlines()]
    assert all(r["patient"] is None for r in records)
    text=(out/"sanitized/batch.json").read_text(encoding="utf-8")
    assert "Zorvila" not in text and "Talriva" not in text


def test_valid_r4_fixture_preserves_references_clinical_fields_and_stay(tmp_path):
    import base64,datetime,json
    from pathlib import Path
    from conftest import run_main
    inp=tmp_path/"in";inp.mkdir()
    fixture=Path(__file__).parent/"fixtures/fhir_r4_valid_collection.json"
    raw=json.loads(fixture.read_text(encoding="utf-8"))
    (inp/"case.json").write_bytes(fixture.read_bytes())
    out=tmp_path/"out";assert run_main(inp,out).returncode==0
    data=json.loads((out/"sanitized/case.json").read_text(encoding="utf-8"))
    original={r["resource"]["resourceType"]:r["resource"] for r in raw["entry"]}
    resources={r["resource"]["resourceType"]:r["resource"] for r in data["entry"]}
    assert resources["Observation"]["valueQuantity"]==original["Observation"]["valueQuantity"]
    assert resources["MedicationRequest"]["dosageInstruction"]==original["MedicationRequest"]["dosageInstruction"]
    assert resources["Practitioner"]["name"]==original["Practitioner"]["name"]
    assert "birthDate" not in resources["Patient"] and resources["Patient"]["_birthDate"]["extension"][0]["valueCode"]=="masked"
    for kind in ["Encounter","Condition","Observation","MedicationRequest","Procedure","DocumentReference"]:
        assert resources[kind]["subject"]==original[kind]["subject"]
    period=resources["Encounter"]["period"]
    assert (datetime.datetime.fromisoformat(period["end"])-datetime.datetime.fromisoformat(period["start"])).days==4
    attachment=resources["DocumentReference"]["content"][0]["attachment"]["data"]
    text=base64.b64decode(attachment).decode()
    assert "Keralin" not in text and "WQ-47-91027" not in text and "Metformin 500 mg twice daily" in text
