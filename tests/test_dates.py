import datetime as dt
import re

import pytest

from cloak.privacy.dates import find_dates, shift_text, OrderVotes


def parse_all(text, order="dmy"):
    out = []
    for t in find_dates(text, order):
        out.append(t.as_date(2026))
    return out


def test_formats_roundtrip_with_same_shape():
    cases = {
        "07/02/2026": "07/02/2026", "7/2/2026": "7/2/2026", "29-01-2026": "29-01-2026", "19.02.2026": "19.02.2026",
        "2026-02-15": "2026-02-15", "12-Apr-1977": "12-Apr-1977", "12 April 1977": "12 April 1977",
        "April 5, 2026": "April 5, 2026",
    }
    for text in cases:
        out = shift_text(text, 0, "dmy", ref_year=2026)
        assert out == text, (text, out)


def test_shift_moves_each_format_by_the_same_days():
    texts = {"10/05/2026": dt.date(2026, 5, 10), "2026-05-10": dt.date(2026, 5, 10), "10-May-2026": dt.date(2026, 5, 10),
             "10 May 2026": dt.date(2026, 5, 10), "10.05.2026": dt.date(2026, 5, 10)}
    for text, d in texts.items():
        out = shift_text(text, 37, "dmy", ref_year=2026)
        got = find_dates(out, "dmy")[0].as_date(2026)
        assert got == d + dt.timedelta(days=37), (text, out)


def test_stay_length_preserved_across_mixed_formats():
    a = "Date of Admission: 07/02/2026 ... Discharge 2026-02-19T10:30:00+05:30"
    out = shift_text(a, -123, "dmy", ref_year=2026)
    d1, d2 = [t.as_date(2026) for t in find_dates(out, "dmy")]
    assert (d2 - d1).days == 12
    assert "T10:30:00+05:30" in out


def test_month_first_order_and_unambiguous_parts():
    assert parse_all("01/13/2026", "dmy") == [dt.date(2026, 1, 13)]          # 13 cannot be a month
    assert parse_all("03/23/2026 and 23/03/2026", "dmy") == [dt.date(2026, 3, 23)] * 2
    assert parse_all("04/05/2026", "mdy") == [dt.date(2026, 4, 5)]
    assert parse_all("04/05/2026", "dmy") == [dt.date(2026, 5, 4)]


def test_no_year_date_shifts_within_reference_year_and_prints_day_month():
    out = shift_text("Visit: 5 September", 10, "dmy", ref_year=2026)
    assert out == "Visit: 15 September"
    out = shift_text("Visit: 28 December", 10, "dmy", ref_year=2026)
    assert out == "Visit: 7 January"


def test_hindi_months_and_devanagari_digits():
    out = shift_text("तारीख: 5 सितंबर 2026", 3, "dmy", ref_year=2026)
    assert "8 सितंबर 2026" in out
    from cloak.detect.normalize import normalize
    shadow, _ = normalize("०७/०२/२०२६")
    assert find_dates(shadow, "dmy")[0].as_date(2026) == dt.date(2026, 2, 7)


def test_not_dates():
    for t in ["1-0-1 x 5 days", "BP 150/90", "Hb 12.0-16.0", "IP/26/00130", "OPD/26/02/00085", "SNJ/26/064508",
              "2345-7", "Tab 1-1-1", "ratio 3/4/5"]:
        assert find_dates(t, "dmy") == [], t


def test_two_digit_year_whatsapp_stamp():
    out = shift_text("[30/05/26, 9:32 pm] Name: hi", 5, "dmy", ref_year=2026)
    assert out.startswith("[04/06/26, 9:32 pm]")


def test_order_votes_prefer_source_then_file_then_default():
    v = OrderVotes()
    v.vote(("f", "col:1"), "mdy", 3)
    v.vote(("f", "col:2"), "dmy", 2)
    assert v.order(("f", "col:1"), ("f",), "dmy") == "mdy"
    assert v.order(("f", "col:9"), ("f",), "dmy") in ("dmy", "mdy")
    assert v.order(("g", "x"), ("g",), "dmy") == "dmy"


def test_two_digit_year_dates_with_dash_or_dot_are_found_when_every_part_has_two_digits():
    from cloak.privacy.dates import find_dates
    for raw in ("08-08-65", "23-11-80", "12.03.26"):
        toks = find_dates(f"Birth was recalled as {raw}, age 46", "dmy")
        assert len(toks) == 1 and toks[0].kind == "num", raw
    for raw in ("1-0-1", "1-1-1", "10-10-5", "5-26", "2-2-10"):
        assert find_dates(f"Tab {raw} daily", "dmy") == [], raw
