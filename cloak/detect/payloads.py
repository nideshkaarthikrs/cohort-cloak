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
