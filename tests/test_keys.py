from cloak.keys import Keys


def test_pseudonym_stable_and_secret_dependent():
    a, a2, b = Keys(b"s1"), Keys(b"s1"), Keys(b"s2")
    assert a.pseudonym("k") == a2.pseudonym("k")
    assert a.pseudonym("k") != b.pseudonym("k")
    assert a.pseudonym("k") != a.pseudonym("k2")
    p = a.pseudonym("k")
    assert p.startswith("PSN-") and len(p) == 10


def test_subkeys_are_independent():
    k = Keys(b"s1")
    assert len({k.psn_key, k.shift_key, k.at_rest_key}) == 3


def test_shift_never_zero_and_in_range():
    k = Keys(b"s1")
    for i in range(500):
        d = k.date_shift_days(f"PSN-{i}", 180)
        assert d != 0 and -180 <= d <= 180


def test_repr_does_not_leak_secret():
    assert "supersecretvalue" not in repr(Keys(b"supersecretvalue"))
    assert "supersecretvalue" not in str(Keys(b"supersecretvalue"))
