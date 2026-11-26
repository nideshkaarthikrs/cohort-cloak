"""Decode bytes to text: utf-8-sig, utf-16, utf-8, then cp1252 only when it looks clean."""
import re

from cloak.errors import Quarantine

# Typical mojibake from stray bytes read as cp1252: BOM remnants and UTF-8 lead bytes before ASCII.
_MOJIBAKE = re.compile("ÿþ|þÿ|Ã[\\x20-\\x7e -¿‘-›]|Â[\\x20-\\x7e -¿]|â€")
_CTRL = re.compile("[\\x00-\\x08\\x0b\\x0c\\x0e-\\x1f\\x7f-\\x9f]")


def _check_text(text: str) -> str:
    if "\x00" in text or len(_CTRL.findall(text)) > max(2, len(text) // 100):
        raise Quarantine("unsupported_format")
    return text


def decode_bytes(raw: bytes) -> str:
    if raw.startswith(b"\xef\xbb\xbf"):
        try:
            return _check_text(raw[3:].decode("utf-8"))
        except UnicodeDecodeError:
            raise Quarantine("invalid_encoding")
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        try:
            return _check_text(raw.decode("utf-16"))
        except UnicodeDecodeError:
            raise Quarantine("invalid_encoding")
    nul = raw.count(b"\x00")
    if nul:
        # UTF-16 without BOM: NULs alternate in the high or low byte of ASCII-heavy text
        sample = raw[:4096]
        even = sample[0::2].count(0)
        odd = sample[1::2].count(0)
        half = max(1, len(sample) // 2)
        for enc, hits in (("utf-16-le", odd), ("utf-16-be", even)):
            if hits / half > 0.3:
                try:
                    return _check_text(raw.decode(enc))
                except UnicodeDecodeError:
                    break
        raise Quarantine("unsupported_format")
    try:
        return _check_text(raw.decode("utf-8"))
    except UnicodeDecodeError:
        pass
    try:
        text = raw.decode("cp1252")
    except UnicodeDecodeError:
        raise Quarantine("invalid_encoding")
    if _MOJIBAKE.search(text) or _CTRL.search(text):
        raise Quarantine("invalid_encoding")
    return text
