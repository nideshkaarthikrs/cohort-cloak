from cloak.detect.normalize import normalize, map_span


def test_homoglyphs_zero_width_and_diacritics_fold():
    t = "Rаvi Ra​vi Rávi"  # Cyrillic a, zero-width space, acute a
    shadow, offs = normalize(t)
    assert shadow == "Ravi Ravi Ravi"


def test_indic_digits_fold_and_length_preserved_for_ascii():
    shadow, _ = normalize("फोन ७८८८०२३९२३")
    assert "7888023923" in shadow


def test_span_maps_back_to_original_offsets():
    t = "x Ra​vi y"
    shadow, offs = normalize(t)
    s = shadow.index("Ravi")
    a, b = map_span(offs, s, s + 4, len(t))
    assert t[a:b] == "Ra​vi"


def test_devanagari_marks_survive():
    shadow, _ = normalize("मोहम्मद शाहिद")
    assert shadow == "मोहम्मद शाहिद"


def test_scanner_letters_inside_a_number_read_as_digits_without_touching_words():
    from cloak.detect.normalize import normalize
    s, _ = normalize("call 794l2 9879l or UID 643I3O 9O7O8O now")
    assert "79412 98791" in s and "643130 907080" in s
    for word in ("Illness", "Olivia", "Hello Ilo", "lOO3"):
        assert normalize(word)[0] == word
    assert len(normalize("a 9O7O8O b")[0]) == len("a 9O7O8O b")


def test_scanner_letters_after_an_id_prefix_read_as_digits():
    s, _ = normalize("note PL/26/lOO4 and QR::lO5l:M and RL-26-lOl4-OP end")
    assert "PL/26/1004" in s and "QR::1051:M" in s and "RL-26-1014-OP" in s
    for keep in ("see Dr/lol", "a:Ill", "x-Olive", "Hi/Ola", "Take/Ill", "lOO3"):
        assert normalize(keep)[0] == keep
    assert len(normalize("PL/26/lOO4 /A")[0]) == len("PL/26/lOO4 /A")
