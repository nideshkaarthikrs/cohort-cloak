from cloak.rewrite.filenames import sanitize_path, sanitize_paths


def test_uhid_and_phone_tokens_removed():
    assert "064508" not in sanitize_path("discharge/Discharge_Summary_X_SNJ-26-064508.txt")
    assert "7148988804" not in sanitize_path("lab/7148988804_report_0047.json")


def test_plain_names_preserved_with_extension_and_dirs():
    assert sanitize_path("opd/sanjeevani_opd_2026_05.json") == "opd/sanjeevani_opd_2026_05.json"
    assert sanitize_path("clean/drug_formulary.csv") == "clean/drug_formulary.csv"


def test_collisions_made_unique_and_deterministic():
    paths = ["a/12345678_x.json", "a/87654321_x.json"]
    m1 = sanitize_paths(paths)
    m2 = sanitize_paths(list(reversed(paths)))
    assert len(set(m1.values())) == 2
    assert m1 == m2


def test_spaces_and_parens_in_ids():
    out = sanitize_path("registration/ADM000161 note (3).txt")
    assert "000161" not in out
