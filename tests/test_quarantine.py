"""Every file we cannot process is quarantined with a snake_case reason, never copied."""
import json

from conftest import entry_for, report_of

VALID_CSV = "Name,Phone\nInvented Person,9000000001\n".encode()


def _run(tmp_path, runner, files):
    inp = tmp_path / "in"
    inp.mkdir()
    for rel, data in files.items():
        p = inp / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
    out = tmp_path / "out"
    res = runner(inp, out)
    assert res.returncode == 0, res.stderr
    return inp, out, report_of(out)


def test_quarantine_reasons(tmp_path, runner):
    files = {
        "empty.csv": b"",
        "blank.txt": b"  \n\n",
        "doc.pdf": b"%PDF-1.4\n%binary stuff\n",
        "photo.jpg": b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01",
        "cda.xml": b"<?xml version='1.0'?><ClinicalDocument/>",
        "trunc.json": b'{"visits": [{"patient": {"name": "Invented Person"',
        "bad.txt": b"Patient note \xff\xfe\xc3( more text\n",
        "deep.json": b"[" * 1500 + b"]" * 1500,
        "ok.csv": VALID_CSV,
    }
    _, out, rep = _run(tmp_path, runner, files)
    want = {
        "empty.csv": "empty_file", "blank.txt": "empty_file", "doc.pdf": "unsupported_format",
        "photo.jpg": "unsupported_format", "cda.xml": "unsupported_format",
        "trunc.json": "malformed_json", "bad.txt": "invalid_encoding",
        "deep.json": "nesting_too_deep",
    }
    for rel, reason in want.items():
        e = entry_for(rep, files[rel])
        assert e["status"] == "quarantined", rel
        assert e["output"] is None
        assert e["reason"] == reason, rel
    assert entry_for(rep, VALID_CSV)["status"] == "sanitized"
    # nothing quarantined is exported
    exported = {p.name for p in (out / "sanitized").rglob("*") if p.is_file()}
    assert exported == {"ok.csv"}


def test_json_behind_csv_extension_is_processed_as_json(tmp_path, runner):
    data = b'{"patient": "Invented Person", "n": 3}'
    _, out, rep = _run(tmp_path, runner, {"x/mislabeled.csv": data})
    assert entry_for(rep, data)["status"] == "sanitized"
    obj = json.loads((out / "sanitized/x/mislabeled.csv").read_text(encoding="utf-8"))
    assert obj == {"patient": "[REDACTED]", "n": 3}


def test_duplicate_files_both_reported(tmp_path, runner):
    _, out, rep = _run(tmp_path, runner, {"a.csv": VALID_CSV, "b (1).csv": VALID_CSV})
    assert len(rep["files"]) == 2
    assert rep["counts"]["files_total"] == 2
    assert rep["counts"]["files_sanitized"] == 2


def test_stderr_has_no_content_on_forced_failure(tmp_path, runner, monkeypatch):
    # invalid encoding content must never surface in stdout or stderr
    inp = tmp_path / "in"
    inp.mkdir()
    (inp / "bad.txt").write_bytes(b"Invented Person \xff\xfe\xc3( 9000000001")
    res = runner(inp, tmp_path / "out")
    assert "Invented" not in res.stdout + res.stderr
    assert "9000000001" not in res.stdout + res.stderr
