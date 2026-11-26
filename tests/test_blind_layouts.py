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


def test_odd_punctuation_ids_are_learned_from_labels_and_found_everywhere(tmp_path):
    out = run(tmp_path, {
        "a.txt": "Patient chart\nMRN   NC~4137~Q   Phone 9814402217\n",
        "b.sql": "INSERT INTO t VALUES ('NC~4137~Q','Dr note','x'); -- ref TR{26}.4211 ; ZC@4248/26\n",
        "c.txt": "Reg no: TR{26}.4211\nUHID: ZC@4248/26\n"})
    blob = "\n".join(out.values())
    for v in ("NC~4137~Q", "TR{26}.4211", "ZC@4248/26"):
        assert v not in blob, v


def test_pins_in_quotes_zones_and_caret_separated_fields(tmp_path):
    out = run(tmp_path, {"a.txt": 'reach = ["Nizpurax", "401307"]\nresidence="Velmorax" zone=401101\n'
                                  "returning to Puthenvelix, postal zone 401822.\nPID|1|Tilmorax^402852\n"})
    blob = out["a.txt"]
    for pin in ("401307", "401101", "401822", "402852"):
        assert pin not in blob, pin


def test_place_before_a_pin_is_learned_as_a_village_everywhere(tmp_path):
    out = run(tmp_path, {"a.txt": "Seen: Qazrabadi 402543 near the school.\n", "b.txt": "Patient is a farmer from Qazrabadi, stable.\n"})
    assert "Qazrabadi" not in out["a.txt"] and "Qazrabadi" not in out["b.txt"]


def test_base64_values_inside_plain_text_are_decoded_and_scrubbed(tmp_path):
    import base64
    b = lambda s: base64.b64encode(s.encode()).decode()
    text = (f"callback.b64={b('7300212927')}\nuid.b64={b('6200 0407 2123')}\nwho.b64={b('Thanglenmoi Zeliangru')}\n"
            f"note.b64={b('Creatinine 2.1 mg/dL')}\n")
    out = run(tmp_path, {"e.txt": text}, {"rare_dx_max_patients": 0})["e.txt"]
    for plain in ("7300212927", "6200 0407 2123", "Thanglenmoi"):
        assert b(plain) not in out and plain not in out
    assert b("Creatinine 2.1 mg/dL") in out  # nothing sensitive in it: left as written


def test_unlabelled_registration_numbers_with_punctuation_are_ids(tmp_path):
    out = run(tmp_path, {"a.txt": "slip VL/26/OP:4100; born later. also NC~4137~Q and TR{26}.4211 plus ZC@4248/26\n"
                                  "BP 148/92 mmHg, ICU-12/B, 1-0-1 daily, HbA1c-6.5/7\n"})["a.txt"]
    for v in ("VL/26/OP:4100", "NC~4137~Q", "TR{26}.4211", "ZC@4248/26"):
        assert v not in out, v
    assert "BP 148/92 mmHg" in out and "ICU-12/B" in out and "1-0-1" in out


def test_post_office_label_words_mark_pins(tmp_path):
    out = run(tmp_path, {"a.txt": "Gaon Quenzox, daak 401513.\nडाक ४०१४१०\nP1N : 401307\n"})["a.txt"]
    for pin in ("401513", "401410", "401307"):
        assert pin not in out, pin


def test_devanagari_patient_cue_and_vcard_birthday(tmp_path):
    out = run(tmp_path, {"a.txt": "रोगी क़ाज़िरवी मिहिलेश बरुआ को बुखार है।\nBDAY:1974-07-07\n"})["a.txt"]
    assert "क़ाज़िरवी" not in out and "1974-07-07" not in out


def test_bare_six_digit_pin_in_prose_but_not_lab_counts_or_amounts(tmp_path):
    out = run(tmp_path, {"a.txt": "Mail goes through 402955 for the hamlet.\nPlatelet count 150000 per cumm.\n"
                                  "Bill total Rs 245000 paid. WBC 110000 noted.\n"})["a.txt"]
    assert "402955" not in out
    assert "150000" in out and "245000" in out and "110000" in out


def test_unknown_first_name_next_to_a_known_given_name_is_a_name(tmp_path):
    out = run(tmp_path, {"a.txt": "C7 | Qwenzitha Neeraj / Mohan (mother) | Iron deficiency anaemia\n",
                         "Attach_Qwenzitha Neeraj Vadakil_VL-26-OP-447012.txt": "ok\n"})
    assert "Qwenzitha" not in out["a.txt"]
    assert not any("Qwenzitha" in k for k in out)


def test_name_continued_on_unlabelled_lines_is_redacted(tmp_path):
    out = run(tmp_path, {"a.txt": "Clinic header\nName begins below, continuation has no label:\nElarosa\nMinetta\nDovarkar\nNext of kin: Lucien Dovarkar (father)\nPulse 96 beats/min\n"})["a.txt"]
    assert "Elarosa" not in out and "Minetta" not in out and "Pulse 96" in out


def test_sentence_initial_verbs_do_not_make_clinical_phrases_into_names(tmp_path):
    out = run(tmp_path, {"a.txt": "Reports TSH 8.6 mIU/L. Requested Thyroid function review; routed to nurse. Advised Peripheral blood smear.\n"})["a.txt"]
    assert "Thyroid function review" in out and "Peripheral blood smear" in out


def test_long_prose_label_is_not_an_address_field(tmp_path):
    out = run(tmp_path, {"a.txt": "Mobile: 9814402217\nघर पर मुलाकात की। दवा का पत्ता देखा: Nitrofurantoin 100 mg.\n"})["a.txt"]
    assert "Nitrofurantoin 100 mg" in out


def test_devanagari_words_next_to_a_redacted_name_belong_to_it(tmp_path):
    out = run(tmp_path, {"a.txt": "Re: Mrinmay Deshmule मृण्मय देशमुले\nलाभार्थी: ध्रुवज्योति Dhruvjyoti Phadke\nMrinmay Deshmule को बुखार है, बहुत कमज़ोरी।\n"})["a.txt"]
    for w in ("मृण्मय", "देशमुले", "ध्रुवज्योति"):
        assert w not in out
    assert "बुखार" in out


INDIC_NAMES = ["మధుకర్ వెలగంటి", "ਜਸਵਿੰਦਰ ਖੁਰਮਾਣੀ", "നിരഞ്ജിത സോമൻ വെള്ളൂരൻ", "অরূপ কাঞ্জিল", "ಶಶಿಧರ ಬೆಳವಡಿ",
               "ବିଶ୍ୱଜିତ ବରାଳିକା", "சோமன் வெள்ளூரன்", "રમેશ પટેલ", "محمد عرفان خان"]


def test_names_in_every_indian_script_are_redacted_in_unknown_columns_and_prose(tmp_path):
    rows = "\n".join(f"{i + 1},{n},{n.split()[-1]} {n.split()[0]},ग्राम{i}" for i, n in enumerate(INDIC_NAMES))
    out = run(tmp_path, {"a.csv": "no,col_a,col_b,col_c\n" + rows + "\n",
                         "b.txt": "Visit note: " + " ; ".join(INDIC_NAMES) + " came today.\n"})
    blob = "\n".join(out.values())
    for name in INDIC_NAMES:
        for tok in name.split():
            assert tok not in blob, tok


def test_latin_name_learned_matches_its_bengali_and_gurmukhi_spelling_in_prose(tmp_path):
    csv = "uhid,patient name,age\nZZH-000001,Arup Kanjilal,40\nZZH-000002,Jaswinder Khurmani,52\nZZH-000003,Sita Mehra,33\n"
    out = run(tmp_path, {"r.csv": csv, "n.txt": "রোগী অরূপ কাঞ্জিল এবং ਜਸਵਿੰਦਰ ਖੁਰਮਾਣੀ ਆਏ।\n"})["n.txt"]
    for tok in ("অরূপ", "কাঞ্জিল", "ਜਸਵਿੰਦਰ", "ਖੁਰਮਾਣੀ"):
        assert tok not in out, tok


def test_marathi_month_names_are_dates(tmp_path):
    out = run(tmp_path, {"a.txt": "D.O.B : 13 जानेवारी 1999\nभेट 12 डिसेंबर 2023 रोजी\n"})["a.txt"]
    assert "जानेवारी 1999" not in out and "डिसेंबर 2023" not in out


def test_line_with_endless_whitespace_is_not_quadratic():
    import time
    from cloak.detect.engine import _LABEL
    line = "x" + " " * 60000 + "y"
    t0 = time.monotonic()
    list(_LABEL.finditer(line))
    assert time.monotonic() - t0 < 2.0
    m = _LABEL.search("Ward 4" + " " * 80 + "Phone: 9876501234")
    assert m and m.group(1) == "Phone"


def test_ocr_digit_for_letter_typos_of_a_known_name_are_removed(tmp_path):
    csv = "Name,Phone,Age\nPhilomena Quarrington,9876512340,41\nGarnet Oyelaran,9812345670,35\n"
    note = ("Scanned note: patient Ph1lomena Quarrington was seen; her bro G4rnet 0yelaran waited. "
            "Quarr1ngton family informed. BP 130/80, Metformin 500 mg.\n")
    out = run(tmp_path, {"reg/a.csv": csv, "scan/n.txt": note})
    blob = "\n".join(out.values()).lower()
    for leak in ("ph1lomena", "quarrington", "g4rnet", "0yelaran", "quarr1ngton"):
        assert leak not in blob, leak
    assert "130/80" in blob and "metformin 500 mg" in blob


def test_unknown_header_column_of_repeating_six_digit_codes_is_a_pin(tmp_path):
    rows = ["Tag,Zq,Visits"] + [f"Pt{i},{pin},{i + 2}" for i, pin in
                                 enumerate(["411045", "411045", "560066", "411045", "560066", "700091", "560066"])]
    out = run(tmp_path, {"x/a.csv": "\n".join(rows) + "\n"})
    text = out["x/a.csv"]
    for pin in ("411045", "560066", "700091"):
        assert pin not in text, pin
    assert "411***" in text or "[PIN]" in text



def test_unknown_header_column_of_repeating_place_names_is_a_village(tmp_path):
    places = ["Quenzo", "Mettupalli", "Quenzo", "Rumtekk", "Mettupalli", "Quenzo", "Rumtekk", "Mettupalli", "Quenzo", "Rumtekk"]
    rows = ["Tag,Zq,Dx"] + [f"Pt{i},{p},Fever" for i, p in enumerate(places)]
    out = run(tmp_path, {"x/c.csv": "\n".join(rows) + "\n"})
    text = out["x/c.csv"]
    for p in ("Quenzo", "Mettupalli", "Rumtekk"):
        assert p not in text, p
    assert text.count("Fever") == 10


def test_unknown_header_column_of_clinical_words_is_kept(tmp_path):
    vals = ["Cardiology", "Neurology", "Cardiology", "Orthopedics", "Neurology", "Cardiology", "Orthopedics", "Neurology", "Cardiology", "Orthopedics"]
    rows = ["Tag,Zq"] + [f"Pt{i},{v}" for i, v in enumerate(vals)]
    out = run(tmp_path, {"x/d.csv": "\n".join(rows) + "\n"})
    assert out["x/d.csv"].count("Cardiology") == 4 and "Neurology" in out["x/d.csv"]


def test_bare_first_and_last_headers_are_name_columns(tmp_path):
    csv = ("first,last,visit_note\nZanthippe,Okwuosa,stable\nBrondolyn,Vashisthra,improving\n"
           "Quillon,Tamarapalli,discharged\n")
    out = run(tmp_path, {"p/a.csv": csv, "p/n.txt": "Ward round: Zanthippe is better. Quillon went home.\n"})
    blob = "\n".join(out.values())
    for leak in ("Zanthippe", "Okwuosa", "Brondolyn", "Vashisthra", "Quillon", "Tamarapalli"):
        assert leak not in blob, leak
    assert "stable" in blob and "improving" in blob


def test_pipe_file_with_title_rows_above_the_header_is_a_table(tmp_path):
    body = ("EXTRACT|Zork Hospital|batch|32\nschema varies by source\n"
            "last|first|pin|phone|note\nOkwuosa|Zanthippe|421101|9876501234|ok\n"
            "Vashisthra|Brondolyn|421204|9876501235|ok\nTamarapalli|Quillon|421307|9876501236|ok\n")
    out = run(tmp_path, {"p/b.psv": body})
    blob = out["p/b.psv"]
    for leak in ("Zanthippe", "421101", "421204", "9876501234", "Okwuosa"):
        assert leak not in blob, leak


def test_base64_payload_that_is_only_a_pin_is_generalised(tmp_path):
    import base64
    b = lambda s: base64.b64encode(s.encode()).decode()
    doc = {"note": "stable", "frag": [{"title": "pin", "data": b("421101")}, {"title": "phone", "data": b("(784) 401-7364")}]}
    out = run(tmp_path, {"x/a.json": doc})
    text = out["x/a.json"]
    assert b("421101") not in text and b("(784) 401-7364") not in text
    assert b("421***") in text or "[PIN]" in text or b("[PIN]") in text


def test_name_whose_surname_is_also_a_village_keeps_its_given_names_removed(tmp_path):
    note = ("Review: Zuhairina Tasveen Barqoli explained the journey from Barqoli; letter via ;;Barqoli;;;422131. "
            "Accompanied by D/o Nafeer Barqoli. BP 120/80.\n")
    out = run(tmp_path, {"n/a.txt": note})
    text = out["n/a.txt"]
    for leak in ("Zuhairina", "Tasveen", "Nafeer", "Barqoli", "422131"):
        assert leak not in text, leak
    assert "120/80" in text


def test_padded_pipe_table_with_a_long_header_cell_is_still_a_table(tmp_path):
    t = ("Bill no | Reg | Name (as per ID) | Service | Amount\n"
         "B-1 | TC/KA/3391 | ZORBAK QUILLFEATHER S | Consultation | 300\n"
         "B-1 | TC/KA/3391 | ZORBAK QUILLFEATHER S | CBC + SGOT | 450\n"
         "B-2 | TC/KA/3418 | MIRELA T VANTHORP | Urine Copper | 1500\n")
    out = run(tmp_path, {"bills.psv": t})["bills.psv"]
    assert "QUILLFEATHER" not in out and "VANTHORP" not in out
    assert "Consultation" in out and "CBC + SGOT" in out
