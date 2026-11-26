"""Synthetic canaries (invented name + phone) planted in every channel must not survive."""
import base64
import json
from urllib.parse import quote

from conftest import run_main

NAME_A, NAME_B = "Zorbek", "Quillfaster"
PHONE = "9876501234"


def _run(tmp_path, files):
    inp = tmp_path / "in"
    for rel, data in files.items():
        p = inp / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data if isinstance(data, bytes) else data.encode("utf-8"))
    out = tmp_path / "out"
    assert run_main(inp, out).returncode == 0
    blob = ""
    for p in sorted((out / "sanitized").rglob("*")):
        if p.is_file():
            blob += p.name + "\n" + p.read_text(encoding="utf-8")
            for tok in p.read_text(encoding="utf-8").replace('"', " ").split():
                try:
                    blob += base64.b64decode(tok + "=" * (-len(tok) % 4), validate=True).decode("utf-8", "ignore")
                except Exception:  # noqa: BLE001
                    pass
    return blob


def _clean(blob):
    return NAME_A not in blob and NAME_B not in blob and PHONE not in blob and "98765 01234" not in blob


def test_canary_in_text_cue_channels(tmp_path):
    blob = _run(tmp_path, {"n/visitor.txt": f"Visitor log\n{NAME_A} {NAME_B} (attendant, bed 12), mob {PHONE}\n"
                                            f"called by {NAME_A} {NAME_B} {PHONE[:5]} {PHONE[5:]}\n"})
    assert _clean(blob)


def test_canary_in_csv_free_text_and_json_meta(tmp_path):
    blob = _run(tmp_path, {
        "m/log.csv": f"trip,from,remarks\n1,A,\"called by {NAME_A} {NAME_B} {PHONE[:5]}-{PHONE[5:]}\"\n",
        "m/tickets.json": json.dumps({"meta": {"raised_by": f"{NAME_A} {NAME_B}", "callback": PHONE}, "tickets": [{"id": 1}]}),
    })
    assert _clean(blob)


def test_canary_base64_percent_unicode_entities(tmp_path):
    b64 = base64.b64encode(f"Visitor: {NAME_A} {NAME_B} mob {PHONE}".encode()).decode()
    pct = quote(f"called by {NAME_A} {NAME_B} {PHONE}")
    uni = "".join(f"\\u{ord(c):04x}" for c in f"called by {NAME_A} {NAME_B} {PHONE}")
    ent = "".join(f"&#{ord(c)};" for c in f"called by {NAME_A} {NAME_B} {PHONE}")
    blob = _run(tmp_path, {"c/f.json": json.dumps({"scan": {"data": b64}, "note": pct, "n2": ent}),
                           "c/raw.txt": f"x {uni} y\n"})
    assert _clean(blob)


def test_canary_homoglyph_and_zero_width(tmp_path):
    t = f"called by Zоrbek Qui​llfaster {PHONE}\n"  # Cyrillic o, zero-width space
    blob = _run(tmp_path, {"c/h.txt": t})
    assert "Quillfaster" not in blob.replace("​", "") and PHONE not in blob
    assert "rbek" not in blob and "Qui" not in blob


def test_canary_in_filename_and_key_and_header(tmp_path):
    blob = _run(tmp_path, {
        f"x/note_{NAME_A}_{NAME_B}_{PHONE}.txt": "BP 120/80\n",
        "x/idx.json": json.dumps({"by_name": {f"{NAME_A} {NAME_B}": 1}}),
        "x/w.csv": f"time,{PHONE} {NAME_A}\n10:00,120/80\n",
    })
    assert _clean(blob)
