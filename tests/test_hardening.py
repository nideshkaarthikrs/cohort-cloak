"""Synthetic regressions for temporal and platform hardening."""
import datetime as dt
from cloak.privacy.dates import find_dates
from cloak.privacy.timeline import resolve_dates
from cloak.report import peak_rss_mb
from cloak.privacy.suppress import escalate


def entry(raw, known=False):
    tok = find_dates(raw)[0]
    tok.order_known = known
    return (0, "doc", "date", raw, (tok, 2026))


def test_ambiguous_date_uses_only_own_patient_anchor():
    t = entry("10/11/2026")
    anchor = entry("2026-10-11", True)
    result = resolve_dates([t, anchor], {(0,"doc"):"P"}, {"P":10})
    assert result[0][0].as_date(result[0][1]) == dt.date(2026,10,11)
    other = (1,"doc",*anchor[2:])
    result = resolve_dates([t, other], {(0,"doc"):"P",(1,"doc"):"Q"}, {"P":10,"Q":20})
    assert result[0][0].as_date(result[0][1]) == dt.date(2026,11,10)


def test_source_order_evidence_beats_cross_patient_and_candidate_votes():
    a = entry("10/11/2026", True)
    b = entry("2026-10-11", True)
    got=resolve_dates([a,b],{(0,"doc"):"P"},{"P":5})
    assert got[0][0].layout == "dmy"


def test_yearless_rollover_adds_resolved_year():
    got=resolve_dates([entry("2026-12-28",True),entry("30 December")],{(0,"doc"):"P"},{"P":10})
    tok,year=got[1]
    assert tok.render(10,year)=="9 January 2027"


def test_yearless_shape_kept_without_rollover():
    got=resolve_dates([entry("2026-04-01",True),entry("5 April")],{(0,"doc"):"P"},{"P":10})
    tok,year=got[1]
    assert tok.render(10,year)=="15 April"


def test_missing_year_without_anchor_is_explicitly_unresolved():
    got=resolve_dates([entry("5 April")],{(0,"doc"):"P"},{"P":10})
    assert got[0][0].year_resolved is False


def test_peak_memory_is_positive():
    assert peak_rss_mb()>0


def test_anonymity_counts_exported_cross_boundary_bands():
    groups={"a":{"gender":"F","age_min":49,"ages":[49,50],"district":"X"},
            "b":{"gender":"F","age_min":48,"ages":[48],"district":"X"}}
    levels=escalate(groups,2,3,base_width=10)
    assert levels["a"]>0 and levels["b"]>0


def test_leap_day_hindi_and_ordinal_rollover():
    from cloak.privacy.dates import shift_text
    assert shift_text("28 February 2024",1)=="29 February 2024"
    assert shift_text("1st March 2026",1)=="2nd March 2026"
    assert shift_text("28 फ़रवरी 2024",1)=="29 फ़रवरी 2024"


def test_procedure_generalisation_reaches_unlabelled_prose(tmp_path):
    from conftest import run_main
    import json
    inp=tmp_path/"in";inp.mkdir()
    (inp/"a.json").write_text(json.dumps({"patient_name":"Zorvila Kelmari","uhid":"ZZR-26001","procedure":"Luminalectomy"}))
    (inp/"b.txt").write_text("Patient Name: Zorvila Kelmari\nUHID: ZZR-26001\nFollow up after Luminalectomy. BP 120/80.\n")
    out=tmp_path/"out"
    assert run_main(inp,out,"synthetic-test",{"rare_dx_max_patients":3,"rare_proc_mode":"generalise"}).returncode==0
    text="\n".join(p.read_text(encoding="utf-8") for p in (out/"sanitized").rglob("*") if p.is_file())
    assert "Luminalectomy" not in text and "Excision procedure" in text and "120/80" in text


def test_birth_year_cannot_anchor_a_yearless_encounter():
    birthday=entry("1976-04-01",True)
    birthday[4][0].is_birth=True
    got=resolve_dates([birthday,entry("5 April")],{(0,"doc"):"P"},{"P":10})
    assert got[1][1]==2026 and not got[1][0].year_resolved


def test_yearless_leap_day_without_anchor_does_not_crash():
    got=resolve_dates([entry("29 February")],{(0,"doc"):"P"},{"P":1})
    tok,year=got[0]
    assert not tok.year_resolved and tok.render(1,year)=="1 March"


def test_generalisation_can_be_disabled_by_policy(tmp_path):
    from cloak.policy import load_policy
    p=tmp_path/"policy.yaml";p.write_text("rare_proc_mode: keep\n")
    assert load_policy(p)["rare_proc_mode"]=="keep"


def test_negative_age_is_not_reinterpreted_as_a_positive_age():
    from cloak.detect.engine import Scrubber
    from cloak.policy import DEFAULTS
    scrubber=Scrubber(dict(DEFAULTS));scrubber.sink=[];scrubber.table=[]
    assert scrubber.scrub_value("age","-2 वर्ष")[0]=="[AGE]"
    assert not scrubber.sink and not scrubber.table
