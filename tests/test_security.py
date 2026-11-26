"""At-rest encryption, temp-file hygiene, signals, and PII-free failure paths."""
import json
import os
import signal
import subprocess
import sys
import textwrap

import pytest

from cloak import cli
from cloak.security.store import SpillStore
from conftest import ROOT, run_main

PII = "Invented Person 9876543210"


def _input(root):
    (root / "a").mkdir(parents=True)
    (root / "a" / "reg.csv").write_text("UHID,Patient Name,Age\nZZH-000001,Invented Person,41\n", encoding="utf-8")
    (root / "a" / "note.txt").write_text(f"Patient Name: Invented Person\nMob: 9876543210\nBP 120/80\n", encoding="utf-8")
    (root / "a" / "v.json").write_text(json.dumps({"visits": [{"patient_ref": "ZZH-000001", "n": 1}]}), encoding="utf-8")


def _tree(p):
    return {x.relative_to(p).as_posix(): x.read_bytes() for x in sorted(p.rglob("*")) if x.is_file()}


def test_store_encrypts_on_disk_and_cleans_up(tmp_path, monkeypatch):
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    store = SpillStore(b"k" * 32, 0)
    h = store.put(b"Invented Person 9876543210 plaintext marker")
    assert store.spilled == 1 and store.get(h) == b"Invented Person 9876543210 plaintext marker"
    blobs = [p for p in tmp_path.rglob("*.bin")]
    assert blobs and all(b"plaintext marker" not in p.read_bytes() for p in blobs)
    store.close()
    assert list(tmp_path.iterdir()) == []


def test_spilled_run_is_identical_and_leaves_no_temp_files(tmp_path):
    inp = tmp_path / "in"
    _input(inp)
    tmp = tmp_path / "tmp"
    tmp.mkdir()
    env_tmp = dict(os.environ, TMPDIR=str(tmp))
    out_a, out_b = tmp_path / "a", tmp_path / "b"
    for out, pol in ((out_a, {"spill_threshold_mb": 0}), (out_b, {"spill_threshold_mb": 1000})):
        pol_file = tmp_path / (out.name + ".yaml")
        pol_file.write_text("\n".join(f"{k}: {v}" for k, v in pol.items()) + "\n")
        res = subprocess.run([sys.executable, str(ROOT / "main.py"), "--input", str(inp), "--output", str(out)],
                             capture_output=True, text=True, cwd=str(ROOT),
                             env=dict(env_tmp, RAKSHA_SECRET="s", COHORT_POLICY=str(pol_file)))
        assert res.returncode == 0, res.stderr
    assert list(tmp.iterdir()) == []
    assert _tree(out_a / "sanitized") == _tree(out_b / "sanitized")
    assert (out_a / "records.jsonl").read_bytes() == (out_b / "records.jsonl").read_bytes()
    assert "spilled=3" in (out_a / "logs" / "run.log").read_text()


@pytest.mark.skipif(sys.platform == "win32", reason="Windows cannot catch SIGTERM: os.kill terminates the process outright")
def test_sigterm_removes_spill_directory(tmp_path):
    code = textwrap.dedent(f"""
        import os, signal, sys
        sys.path.insert(0, {str(ROOT)!r})
        from cloak.security.store import SpillStore
        s = SpillStore(b"k" * 32, 0)
        s.put(b"secret-ish bytes")
        print(os.listdir(os.environ["TMPDIR"]), flush=True)
        os.kill(os.getpid(), signal.SIGTERM)
        import time; time.sleep(5)
    """)
    res = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                         env=dict(os.environ, TMPDIR=str(tmp_path)))
    assert res.returncode == 128 + signal.SIGTERM
    assert "cc_" in res.stdout            # the spill dir existed while running
    assert list(tmp_path.iterdir()) == []  # and is gone after SIGTERM


def test_exception_inside_a_file_quarantines_without_content(tmp_path, monkeypatch, capsys):
    inp = tmp_path / "in"
    _input(inp)

    def boom(text, scrubber):
        raise ValueError(PII)

    monkeypatch.setattr(cli, "transform_text", boom)
    monkeypatch.setenv("RAKSHA_SECRET", "s")
    rc = cli.main(["--input", str(inp), "--output", str(tmp_path / "o")])
    cap = capsys.readouterr()
    assert rc == 0
    blob = cap.out + cap.err + (tmp_path / "o" / "report.json").read_text() + (tmp_path / "o" / "logs" / "run.log").read_text()
    assert "Invented" not in blob and "9876543210" not in blob
    rep = json.loads((tmp_path / "o" / "report.json").read_text())
    assert any(e.get("reason") == "error_value_error" for e in rep["files"])
    assert rep["counts"]["files_quarantined"] == 1
    assert not (tmp_path / "o" / "sanitized" / "a" / "note.txt").exists()


def test_fatal_excepthook_prints_type_and_frames_only(capsys):
    try:
        raise KeyError(PII)
    except KeyError:
        etype, value, tb = sys.exc_info()
    cli._excepthook(etype, value, tb)
    err = capsys.readouterr().err
    assert "KeyError" in err and "Invented" not in err and "9876543210" not in err


def test_linking_failure_falls_back_to_unlinked_but_complete(tmp_path, monkeypatch, capsys):
    inp = tmp_path / "in"
    _input(inp)

    def broken(*a, **k):
        raise RuntimeError(PII)

    monkeypatch.setattr(cli, "link_units", broken)
    monkeypatch.setenv("RAKSHA_SECRET", "s")
    assert cli.main(["--input", str(inp), "--output", str(tmp_path / "o")]) == 0
    out = capsys.readouterr()
    assert "Invented" not in out.out + out.err
    recs = [json.loads(l) for l in (tmp_path / "o" / "records.jsonl").read_text().splitlines()]
    assert recs and all(r["patient"] is None for r in recs)
    assert "Invented" not in (tmp_path / "o" / "sanitized" / "a" / "note.txt").read_text()


def test_input_is_never_modified(tmp_path):
    inp = tmp_path / "in"
    _input(inp)
    before = _tree(inp)
    assert run_main(inp, tmp_path / "o").returncode == 0
    assert _tree(inp) == before
