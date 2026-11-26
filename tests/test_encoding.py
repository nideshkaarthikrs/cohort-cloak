import pytest

from cloak.ingest.encoding import decode_bytes
from cloak.errors import Quarantine


def test_utf8_bom():
    assert decode_bytes("﻿Naam,Umar\n".encode("utf-8")) == "Naam,Umar\n"


def test_utf16le_with_bom_and_crlf():
    raw = "Naam\tUmar\r\nA\t5\r\n".encode("utf-16")
    assert decode_bytes(raw) == "Naam\tUmar\r\nA\t5\r\n"


def test_utf16_without_bom_detected_by_nul_pattern():
    raw = "Naam\tUmar\r\n".encode("utf-16-le")
    assert decode_bytes(raw) == "Naam\tUmar\r\n"


def test_utf8_devanagari():
    assert decode_bytes("नाम: टेस्ट".encode("utf-8")) == "नाम: टेस्ट"


def test_cp1252_accepted_when_clean():
    assert decode_bytes("Caf\xe9 €5".encode("cp1252")) == "Café €5"


def test_mojibake_stray_bytes_rejected():
    with pytest.raises(Quarantine) as ei:
        decode_bytes(b"note \xff\xfe\xc3( text")
    assert ei.value.code == "invalid_encoding"


def test_binary_with_nuls_unsupported():
    with pytest.raises(Quarantine) as ei:
        decode_bytes(b"abc\x00\x01\x02\x00def\x00\x00\x00ghi" * 10)
    assert ei.value.code in {"unsupported_format", "invalid_encoding"}
