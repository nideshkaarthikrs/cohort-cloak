from cloak.detect.names import NameDict
from cloak.rewrite.filenames import sanitize_path


def test_dictionary_redacts_variants_and_respects_guards():
    d = NameDict()
    d.add("Shahid Mohammad")
    d.add("RAMESH KUMAR", kind="relative")
    t = "Shahid sahab ka BP. MOHAMMAD SHAHID aaya. Dr. Ramesh Srivastava ne dekha. W/o Ramesh"
    out, n = d.scrub(t)
    assert "Shahid" not in out and "SHAHID" not in out and "Mohammad" not in out.replace("[NAME]", "")
    assert "Dr. Ramesh Srivastava" in out
    assert out.endswith("W/o [NAME]")
    assert n >= 3


def test_dictionary_ignores_tiny_and_title_tokens():
    d = NameDict()
    d.add("Mr. A Kumar")
    out, _ = d.scrub("Mr. A is here, Kumar present, a b c")
    assert "A is here" in out or "[NAME] is here" not in out
    assert "Kumar" not in out


def test_devanagari_names():
    d = NameDict()
    d.add("मोहम्मद शाहिद")
    out, _ = d.scrub("मोहम्मद शाहिद को 9 दिन से बुखार है।")
    assert "शाहिद" not in out and "9 दिन से बुखार है" in out


def test_filename_tokens_use_dictionary_and_ids():
    d = NameDict()
    d.add("Fatima Bano")
    p = sanitize_path("discharge/Discharge_Summary_Fatima_Bano_SNJ-26-064508.txt", names=d)
    assert "Fatima" not in p and "Bano" not in p and "064508" not in p
    assert p.endswith(".txt") and p.startswith("discharge/Discharge_Summary")
