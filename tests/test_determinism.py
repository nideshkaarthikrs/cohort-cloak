import json
import subprocess

from conftest import ROOT, run_main


def _make_input(root):
    (root / "reg").mkdir(parents=True)
    (root / "reg" / "a.csv").write_text("UHID,Patient Name,Age\nSNJ/26/000001,Invented Person,41\n", encoding="utf-8")
    (root / "reg" / "b.json").write_text(json.dumps({"visits": [{"patient_ref": "X-1", "n": 1}, {"patient_ref": "X-2", "n": 2}]}), encoding="utf-8")
    (root / "notes").mkdir()
    (root / "notes" / "n_01234567.txt").write_text("Patient: Invented Person\nBP 120/80\n", encoding="utf-8")


def _tree(p):
    return {x.relative_to(p).as_posix(): x.read_bytes() for x in sorted(p.rglob("*")) if x.is_file()}


def test_same_secret_byte_identical(tmp_path):
    inp = tmp_path / "in"
    _make_input(inp)
    for name in ("o1", "o2"):
        assert run_main(inp, tmp_path / name, "s-one").returncode == 0
    a, b = _tree(tmp_path / "o1" / "sanitized"), _tree(tmp_path / "o2" / "sanitized")
    assert a == b and a
    assert (tmp_path / "o1" / "records.jsonl").read_bytes() == (tmp_path / "o2" / "records.jsonl").read_bytes()


def test_secret_never_written_anywhere(tmp_path):
    inp = tmp_path / "in"
    _make_input(inp)
    secret = "TopSecretValue-9f3a"
    res = run_main(inp, tmp_path / "o", secret)
    assert res.returncode == 0
    blob = res.stdout + res.stderr
    for p in (tmp_path / "o").rglob("*"):
        if p.is_file():
            blob += p.read_text(encoding="utf-8", errors="replace") + p.name
    assert secret not in blob


def test_records_jsonl_locators(tmp_path):
    inp = tmp_path / "in"
    _make_input(inp)
    run_main(inp, tmp_path / "o")
    recs = [json.loads(l) for l in (tmp_path / "o" / "records.jsonl").read_text().splitlines()]
    locs = {(r["file"], r["loc"]) for r in recs}
    assert ("sanitized/reg/a.csv", "row:0") in locs
    assert ("sanitized/reg/b.json", "/visits/0") in locs and ("sanitized/reg/b.json", "/visits/1") in locs
    assert ("sanitized/reg/b.json", "doc") in locs
    assert ("sanitized/notes/n_ID.txt", "doc") in locs or any(l[0].startswith("sanitized/notes/") and l[1] == "doc" for l in locs)
    assert all(r["patient"] is None for r in recs)


def test_missing_secret_fails_closed(tmp_path):
    import os, sys
    inp = tmp_path / "in"
    _make_input(inp)
    env = {k: v for k, v in os.environ.items() if k != "RAKSHA_SECRET"}
    res = subprocess.run([sys.executable, str(ROOT / "main.py"), "--input", str(inp), "--output", str(tmp_path / "o")],
                         capture_output=True, text=True, env=env)
    assert res.returncode != 0
