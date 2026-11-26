"""Phase 1 redact-all transform. Every string leaf, cell and line becomes [REDACTED].

Keys and headers survive only when they are not PII-shaped. Numbers keep their type,
except long integers (phone/Aadhaar-sized) which become 0.
"""
import re

REDACTED = "[REDACTED]"
_SAFE_KEY = re.compile(r"^[a-z_@$][A-Za-z0-9_@$.:\-]*$")
_DIGITS4 = re.compile(r"\d{4,}")
_UUID = re.compile(r"^(urn:uuid:)?[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
_HEADER_OK = re.compile(r"^[^\W\d][\w ./()#%'\-&?:+]*$", re.UNICODE)
_STRUCT_VALUE_KEYS = {"resourceType"}


def safe_key(key: str) -> bool:
    return bool(_SAFE_KEY.match(key)) and not _DIGITS4.search(key)


def safe_header(h: str) -> bool:
    if not h.strip():
        return True
    if re.search(r"\d{3,}", h) or not _HEADER_OK.match(h.strip()):
        return False
    return len(h) <= 60


def redact_json(data, _count=None):
    """Return (redacted_copy, number_of_redactions). Iterative, safe for deep inputs."""
    count = [0]

    def leaf(v, key=None):
        if isinstance(v, str):
            if v == "" or (key in _STRUCT_VALUE_KEYS) or _UUID.match(v):
                return v
            count[0] += 1
            return REDACTED
        if isinstance(v, bool) or v is None or isinstance(v, float):
            return v
        if isinstance(v, int):
            if len(str(abs(v))) >= 9:
                count[0] += 1
                return 0
            return v
        return v

    def walk(v, key=None):
        if isinstance(v, dict):
            bad = sorted(k for k in v if not safe_key(k))
            rank = {k: i for i, k in enumerate(bad)}
            out = {}
            for k, x in v.items():
                if k in rank:
                    nk = "[KEY]" if rank[k] == 0 else f"[KEY]-{rank[k] + 1}"
                    count[0] += 1
                else:
                    nk = k
                out[nk] = walk(x, k)
            return out
        if isinstance(v, list):
            return [walk(x, key) for x in v]
        return leaf(v, key)

    return walk(data), count[0]


def redact_csv_rows(header, rows):
    """Return (new_header, new_rows, redaction_count)."""
    n = 0
    new_header = []
    seen = {}
    for h in header:
        if not safe_header(h):
            n += 1
            c = seen.get("[COLUMN]", 0) + 1
            seen["[COLUMN]"] = c
            new_header.append("[COLUMN]" if c == 1 else f"[COLUMN]-{c}")
        else:
            new_header.append(h)  # duplicate safe headers stay exactly as the input had them
    new_rows = []
    for row in rows:
        out = []
        for cell in row:
            if cell.strip():
                out.append(REDACTED)
                n += 1
            else:
                out.append(cell)
        new_rows.append(out)
    return new_header, new_rows, n


def redact_text(text: str):
    n = 0
    out = []
    for line in text.split("\n"):
        if line.strip():
            out.append(REDACTED)
            n += 1
        else:
            out.append("")
    return "\n".join(out), n
