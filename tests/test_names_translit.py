from cloak.detect.names import NameDict
from cloak.link.translit import name_key, skeleton, to_latin


def test_skeleton_variants_equal():
    assert skeleton("Rina") == skeleton("Reena") == skeleton("रीना")
    assert skeleton("Hareesh") == skeleton("Harish") == skeleton("हरीश")
    assert skeleton("Kavitha") == skeleton("Kavita")
    assert skeleton("Kamal") != skeleton("Kamla")


def test_name_key_variants_orders_and_scripts():
    keys = {name_key(n) for n in ["Mohammad Shahid", "Mohd. Shahid", "Md Shahid", "SHAHID MOHAMMAD",
                                  "मोहम्मद शाहिद", "Shahid Mohammed"]}
    assert len(keys) == 1


def test_different_people_keep_different_keys():
    assert name_key("Ramesh Kumar") != name_key("Rakesh Kumar")


def test_to_latin():
    assert to_latin("मोहम्मद").lower().startswith("moham")


def test_dictionary_matches_across_scripts_and_spellings():
    d = NameDict()
    d.add("Harish Chauhan")
    out, n = d.scrub("हरीश जी आए। Hareesh ka BP 120/80. CHAUHAN saab")
    assert "हरीश" not in out and "Hareesh" not in out and "CHAUHAN" not in out
    assert "BP 120/80" in out
