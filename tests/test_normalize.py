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
