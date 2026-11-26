"""Linkage behaviour on invented evidence: traps, constraints and determinism."""
import json
import random

from cloak.keys import Keys
from cloak.link import cluster as C
from cloak.link import evidence as E
from cloak.link import pseudonym as P
from conftest import run_main


def ev(*events):
    return E.build(list(events))


def partition(evs):
    roots, uf = C.cluster(evs)
    final = C.assign_fragments(evs, roots, uf)
    groups = {}
    for i, r in enumerate(final):
        if r is not None:
            groups.setdefault(r, set()).add(i)
    return {frozenset(g) for g in groups.values()}, final


def reg(name, village, age, dob=None, rel=None, gender="M", uhid=None):
    e = [("patient_name", name), ("village", village), ("age", str(age)), ("gender", gender), ("date_event", "10/03/2026")]
    if dob:
        e.append(("dob", dob))
    if rel:
        e.append(("relative_name", rel))
    if uhid:
        e.append(("mrn", uhid))
    return ev(*e)


def test_homonyms_with_different_village_age_relative_stay_apart():
    a = reg("Ramesh Kumar", "Fakepur", 30, "01/02/1996", "Gopal Kumar", uhid="ZZH-000001")
    b = reg("Ramesh Kumar", "Nowhere", 55, "05/06/1971", "Mohan Lal", uhid="YYH-000002")
    c = reg("Ramesh Kumar", "Elsewhere", 31, None, "Sita Devi")
    d = reg("Ramesh Kumar", "Faraway", 30, None, "Raju")
    parts, _ = partition([a, b, c, d])
    assert all(len(p) == 1 for p in parts)


def test_same_person_links_across_hospitals_by_dob_name_village():
    a = reg("Mohammad Shahid", "Mohanganj Kalan", 39, "30/05/1986", "Zubair", uhid="SNJ/26/000001")
    b = reg("Mohd. Shahid", "Mohanganj Kalan", 39, "05/30/1986", "S/O ZUBAIR", uhid="UHID-000002")
    parts, _ = partition([a, b])
    assert parts == {frozenset({0, 1})}


def test_cross_script_prose_record_links_by_name_age_village():
    a = reg("Mohammad Shahid", "Mohanganj Kalan", 39, "30/05/1986", "Zubair", uhid="SNJ/26/000001")
    h = ev(("patient_name", "मोहम्मद शाहिद"), ("age", "39 वर्ष"), ("village", "मोहनगंज कलां"))
    parts, _ = partition([a, h])
    assert parts == {frozenset({0, 1})}


def test_shared_id_with_incompatible_names_is_demoted_and_never_merges():
    a = ev(("patient_name", "Sita Devi Fakeperson"), ("phone", "9876501234"), ("gender", "F"))
    b = ev(("patient_name", "Ramesh Otherperson"), ("phone", "9876501234"), ("gender", "M"))
    parts, _ = partition([a, b])
    assert all(len(p) == 1 for p in parts)


def test_gender_and_birth_year_conflicts_block_a_shared_uhid():
    a = reg("Asha Verma", "Fakepur", 30, uhid="ZZH-000009", gender="F")
    b = reg("Asha Verma", "Fakepur", 30, uhid="ZZH-000009", gender="M")
    c = reg("Asha Verma", "Fakepur", 70, uhid="ZZH-000009", gender="F")
    parts, _ = partition([a, b])
    assert all(len(p) == 1 for p in parts)
    parts, _ = partition([a, c])
    assert all(len(p) == 1 for p in parts)


def test_fragment_links_only_when_exactly_one_cluster_matches():
    a = reg("Asha Gupta", "Fakepur", 48, uhid="ZZH-000010", gender="F", rel="Kamal Gupta")
    frag = ev(("name:subject", "Asha"), ("name:rel", "Kamal"))
    parts, final = partition([a, frag])
    assert final[1] == final[0] and final[0] is not None
    b = reg("Asha Verma", "Nowhere", 52, uhid="YYH-000011", gender="F", rel="Kamal Verma")
    parts, final = partition([a, b, frag])
    assert final[2] is None  # ambiguous: two Asha/Kamal clusters


def test_prose_only_record_without_identity_stays_unlinked():
    a = reg("Asha Gupta", "Fakepur", 48, uhid="ZZH-000010", gender="F")
    noise = ev(("name:subject", "Asha"))
    _, final = partition([a, noise])
    assert final[1] is None


def test_partition_and_psn_independent_of_record_order():
    base = [reg("Asha Gupta", "Fakepur", 48, uhid="ZZH-000010", gender="F"),
            reg("Asha Gupta", "Fakepur", 48, uhid="ZZH-000010", gender="F"),
            reg("Ramesh Verma", "Nowhere", 40, uhid="YYH-000011"),
            ev(("patient_name", "Ramesh Verma"), ("mrn", "YYH-000011"))]
    keys = Keys(b"s")

    def run(order):
        evs = [base[i] for i in order]
        roots, uf = C.cluster(evs)
        final = C.assign_fragments(evs, roots, uf)
        groups = {}
        for i, r in enumerate(final):
            groups.setdefault(r, []).append(evs[i])
        psn = P.assign(keys, groups)
        return {order[i]: psn[final[i]] for i in range(len(evs))}

    ref = run([0, 1, 2, 3])
    for _ in range(5):
        order = [0, 1, 2, 3]
        random.Random(_).shuffle(order)
        assert run(order) == ref


def test_cluster_key_prefers_strong_ids():
    a = reg("Asha Gupta", "Fakepur", 48, uhid="ZZH-000010")
    assert P.cluster_key([a]).startswith("mrn:")


def _make_input(root):
    (root / "r").mkdir(parents=True)
    (root / "r" / "reg.csv").write_text(
        "UHID,Patient Name,Age,Gender\nZZH-000010,Asha Gupta,48,F\nZZH-000011,Ramesh Verma,40,M\n", encoding="utf-8")
    (root / "r" / "visits.json").write_text(json.dumps({"visits": [
        {"patient_ref": "ZZH-000010", "patient": {"name": "Asha Gupta"}, "notes": "BP 120/80"},
        {"patient_ref": "ZZH-000011", "patient": {"name": "Ramesh Verma"}, "notes": "BP 130/80"}]}), encoding="utf-8")
    (root / "r" / "note.txt").write_text("Patient Name: Asha Gupta\nUHID: ZZH-000010\nBP 118/76\n", encoding="utf-8")
    (root / "r" / "nameless.txt").write_text("Visit note for ZZH-000011. BP 128/82\n", encoding="utf-8")


def test_end_to_end_psn_present_consistent_and_secret_dependent(tmp_path):
    inp = tmp_path / "in"
    _make_input(inp)
    assert run_main(inp, tmp_path / "o1", "secret-one").returncode == 0
    assert run_main(inp, tmp_path / "o2", "secret-two").returncode == 0
    recs = [json.loads(l) for l in (tmp_path / "o1" / "records.jsonl").read_text().splitlines()]
    by = {(r["file"], r["loc"]): r["patient"] for r in recs}
    asha = {by[("sanitized/r/reg.csv", "row:0")], by[("sanitized/r/visits.json", "/visits/0")], by[("sanitized/r/note.txt", "doc")]}
    assert len(asha) == 1 and None not in asha
    ramesh = {by[("sanitized/r/reg.csv", "row:1")], by[("sanitized/r/visits.json", "/visits/1")], by[("sanitized/r/nameless.txt", "doc")]}
    assert len(ramesh) == 1 and None not in ramesh and ramesh != asha
    assert by[("sanitized/r/visits.json", "doc")] is None  # items disagree
    # every claimed pseudonym really appears inside its exported file
    for r in recs:
        if r["patient"]:
            assert r["patient"] in (tmp_path / "o1" / r["file"]).read_text(encoding="utf-8"), r
    nameless = (tmp_path / "o1" / "sanitized/r/nameless.txt").read_text(encoding="utf-8")
    assert "BP 128/82" in nameless
    other = {json.loads(l)["patient"] for l in (tmp_path / "o2" / "records.jsonl").read_text().splitlines()}
    assert not (other & {p for p in asha | ramesh})


def test_devanagari_rendering_with_vowel_drift_is_still_a_candidate():
    """Latin 'Siddiqui' and Devanagari 'सिद्दीक़ी' skeletonise to different strings; blocking must still pair them."""
    a = reg("Rukhsana Siddiqui", "Amarganj Khurd", 74, "03/02/1952", gender="F", uhid="ZZH-000077")
    b = ev(("patient_name", "रुख़साना सिद्दीक़ी"), ("village", "अमरगंज खुर्द"), ("age", "74"), ("date_event", "10/03/2026"))
    parts, _ = partition([a, b])
    assert parts == {frozenset({0, 1})}
