"""Hidden channels: base64 attachments. Decoded text is scrubbed and re-encoded in place."""
import base64
import binascii
import re

_B64 = re.compile(r"^[A-Za-z0-9+/]{16,}={0,2}$")
ATTACHMENT_PLACEHOLDER = "[REDACTED ATTACHMENT]"


def looks_b64(s: str) -> bool:
    t = s.strip()
    return len(t) >= 24 and bool(_B64.match(t))


def decode_b64_text(s: str):
    """Return decoded UTF-8 text if `s` is base64 of printable text, else None."""
    t = s.strip()
    try:
        raw = base64.b64decode(t + "=" * (-len(t) % 4), validate=True)
        text = raw.decode("utf-8")
    except (binascii.Error, ValueError, UnicodeDecodeError):
        return None
    printable = sum(ch.isprintable() or ch in "\n\r\t" for ch in text)
    return text if text and printable / len(text) >= 0.95 else None


def encode_b64_text(text: str) -> str:
    return base64.b64encode(text.encode("utf-8")).decode("ascii")


# ---- other hidden encodings: percent-encoding, \uXXXX escapes, HTML entities -------------------------
import html
import re as _re
from collections import namedtuple
from urllib.parse import quote, unquote

_PCT = _re.compile(r"(?:%[0-9A-Fa-f]{2}){2,}")
_UESC = _re.compile(r"(?:\\u[0-9a-fA-F]{4}){2,}")
_ENT = _re.compile(r"(?:&#(?:x[0-9a-fA-F]+|\d+);){2,}")
_Layer = namedtuple("_Layer", "detect run")


def _enc_uesc(text: str) -> str:
    return "".join(c if ord(c) < 128 and c.isalnum() is False and c not in "\\" else f"\\u{ord(c):04x}"
                   if ord(c) > 127 or c.isalnum() else c for c in text)


def _enc_ent(text: str) -> str:
    return "".join(f"&#{ord(c)};" if (c.isalnum() or ord(c) > 127) else c for c in text)


def _dec_uesc(text: str) -> str:
    return _re.sub(r"\\u([0-9a-fA-F]{4})", lambda m: chr(int(m.group(1), 16)), text)


ENCODINGS = (
    (_Layer(lambda t: bool(_PCT.search(t)), unquote), lambda t: quote(t, safe="")),
    (_Layer(lambda t: bool(_UESC.search(t)), _dec_uesc), _enc_uesc),
    (_Layer(lambda t: bool(_ENT.search(t)), html.unescape), _enc_ent),
)
