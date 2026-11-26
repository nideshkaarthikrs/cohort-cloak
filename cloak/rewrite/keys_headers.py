"""Keys and headers: kept only when they are schema-like and mention no known name or ID."""
import re

from cloak.detect.names import _TOKEN_SPLIT

_SAFE_KEY = re.compile(r"^[a-z_@$][A-Za-z0-9_@$.:\-]*$")
_HEADER_OK = re.compile(r"^[^\W\d][\w ./()#%'\-&?:+]*$", re.UNICODE)


def _mentions_known(text: str, scrubber) -> bool:
    for tok in _TOKEN_SPLIT.split(text):
        if tok and len(tok) >= 3 and (scrubber.names.has_token(tok)):
            return True
    return bool(scrubber.ids.find(text))


def safe_key(key: str, scrubber) -> bool:
    return (bool(_SAFE_KEY.match(key)) and not re.search(r"\d{4,}", key) and not _mentions_known(key, scrubber))


def safe_header(h: str, scrubber) -> bool:
    if not h.strip():
        return True
    if re.search(r"\d{3,}", h) or not _HEADER_OK.match(h.strip()) or len(h) > 60:
        return False
    return not _mentions_known(h, scrubber)
