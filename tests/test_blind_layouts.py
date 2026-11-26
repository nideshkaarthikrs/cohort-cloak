"""Regressions from the blind layout test (a set written by a separate agent that never saw the detectors).
All strings below are invented."""
import json

from cloak.detect.columns import looks_like_id
from conftest import run_main


def run(tmp_path, files, policy=None):
    inp = tmp_path / "in"
    for rel, content in files.items():
        p = inp / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content if isinstance(content, str) else json.dumps(content), encoding="utf-8")
    out = tmp_path / "o"
    res = run_main(inp, out, "s", policy)
    assert res.returncode == 0, res.stderr
    return {str(p.relative_to(out / "sanitized")): p.read_text(encoding="utf-8")
            for p in (out / "sanitized").rglob("*") if p.is_file()}


def test_colon_prefixed_reference_numbers_look_like_ids():
    assert looks_like_id("reg:QX2208b41") and looks_like_id("ZV.2031.B-7781")


def test_json_rows_with_unusual_keys_are_profiled_like_a_table(tmp_path):
    rows = [{"⟨who⟩": "Tarkeshwar Zinta Ohri", "№": "reg:QX2208b41", "kin_": "Dhaniram Ohri"},
            {"⟨who⟩": "Fenella Quibell Dsouza", "№": "ZV.2031.B-7781", "kin_": "Orlan Dsouza"},
            {"⟨who⟩": "Imranuddin Valsala Beigh", "№": "QQ/77/2210044", "kin_": "Valsala Beigh"}]
    out = run(tmp_path, {"a.json": {"rows": rows},
                         "b.txt": "Ward note: Tarkeshwar Zinta Ohri, ref reg:QX2208b41 stable. Beigh sahab ka BP 120/80.\n"})
    blob = "\n".join(out.values())
    for leak in ("Tarkeshwar", "Fenella", "Imranuddin", "QX2208b41", "ZV.2031.B-7781", "Dhaniram", "Beigh"):
        assert leak not in blob, leak
    assert "120/80" in blob


def test_pin_codes_in_prose_and_after_places_are_generalised(tmp_path):
    out = run(tmp_path, {"a.txt": "Village Quenzo  PIN 412356 near the road.\nपिन: 229403\n"
                                  "Door: Mettupalli 641034  seen today.\nGhar Rumtekk me hai (pin 737135).\n"
                                  "Platelets 150000 per cumm.\n"})
    blob = out["a.txt"]
    for pin in ("412356", "229403", "641034", "737135"):
        assert pin not in blob, pin
    assert "150000" in blob


def test_learned_village_is_redacted_in_prose(tmp_path):
    csv = "uhid,patient name,village,age\nZZH-000001,Qintara Vellore,Pandriyur,40\nZZH-000002,Yamuna Quill,Kotharpet,52\n"
    out = run(tmp_path, {"r.csv": csv, "n.txt": "Hinglish note: ghar Pandriyur me hai, aur Kotharpet se aaye.\n"})
    assert "Pandriyur" not in out["n.txt"] and "Kotharpet" not in out["n.txt"]


def test_json_lines_files_are_processed_not_quarantined(tmp_path):
    lines = [{"ev": "visit", "patient": "Tarkeshwar Zinta Ohri", "mobile": "9814402217", "dx": "E11.9"},
             {"ev": "visit", "patient": "Fenella Quibell Dsouza", "mobile": "9814402218", "dx": "I10"}]
    out = run(tmp_path, {"e.jsonl": "\n".join(json.dumps(x) for x in lines) + "\n"}, {"rare_dx_max_patients": 0})
    text = out["e.jsonl"]
    assert "Tarkeshwar" not in text and "9814402217" not in text and "E11.9" in text
    assert len(text.strip().splitlines()) == 2 and all(json.loads(l) for l in text.strip().splitlines())


def test_text_after_a_labelled_phone_on_the_same_line_is_kept_and_scanned(tmp_path):
    out = run(tmp_path, {"f.txt": "Mobile: 9814402217  Reg ZV.2031.B-7781  J18.9 Atorvastatin 20 mg HS Creatinine 2.1 mg/dL\n"},
              {"rare_dx_max_patients": 0})
    t = out["f.txt"]
    assert "Atorvastatin 20 mg HS" in t and "Creatinine 2.1 mg/dL" in t
    assert "9814402217" not in t


def test_key_value_log_with_quoted_commas_is_not_mistaken_for_csv(tmp_path):
    log = ('2025-08-01T09:00:00 INFO user=nurse1 action=view name="Ohri, Tarkeshwar Zinta" mobile=9814402217 rx="Aspirin 75 mg OD"\n'
           '2025-08-01T09:00:00 INFO user=nurse1 action=view name="Dsouza, Fenella Quibell" mobile=9814402218 rx="Aspirin 75 mg OD"\n'
           '2025-08-01T09:00:01 INFO user=nurse1 action=view name="Beigh, Imranuddin" mobile=9814402219 rx="Aspirin 75 mg OD"\n')
    out = run(tmp_path, {"audit.log": log})
    t = out["audit.log"]
    assert t.count("Aspirin 75 mg OD") == 3 and "Tarkeshwar" not in t and "9814402217" not in t


def test_village_cues_and_surname_first_commas(tmp_path):
    out = run(tmp_path, {"n.txt": "Phone [x], ghar Quenzoli me hai. Please see Shabnam Ansari, from Mubarakpuri (276404).\n"
                                  "Row: Qaisarganj, Tsering Dolmaa   BP 140/90 mmHg\n"})
    t = out["n.txt"]
    assert "Quenzoli" not in t and "276404" not in t and "Qaisarganj" not in t and "140/90 mmHg" in t
