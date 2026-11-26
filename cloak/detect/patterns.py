"""Hard-identifier finders: phones, Aadhaar, ABHA, PAN, email, insurance, label-anchored IDs.

Operates on text whose Indic digits are folded to ASCII one-for-one, so offsets map back
to the original string unchanged.
"""
import bisect
import re

from cloak.detect.validators import ascii_digits, phone_core
from cloak.model import Span

_PHONE_RUN = re.compile(r"(?<![\w.])(?:\+|00)?(?:\d(?:[ \-]?\d){9,13}|\(\d{3}\)[ \-]?\d{3}[ \-]?\d{4})(?![\w]|[ \-]?\d)")
_AADHAAR = re.compile(r"(?<![\w])[2-9]\d{3}[ \-]?\d{4}[ \-]?\d{4}(?![\w]|[ \-]?\d)")
# after an Aadhaar label: 12 digits with scanner look-alikes (O, l, I) and stray spaces between them
_AADHAAR_FUZZY = re.compile(r"(?:aadh?a+r|uid|आधार)\W{0,4}((?:[0-9OolI] {0,3}){11}[0-9OolI])(?![A-Za-z0-9])", re.I)
_AADHAAR_MASK = re.compile(r"(?<![\w])[Xx*•]{4}[ \-]?[Xx*•]{4}[ \-]?\d{4}(?!\d)")
_ABHA = re.compile(r"(?<![\w])\d{2}-\d{4}-\d{4}-\d{4}(?!\d)|(?<![\w])\d{14}(?!\d)")
_ABHA_ADDR = re.compile(r"(?<![\w.\-])[\w.\-]+@(?:abdm|sbx)\b", re.I)
_EMAIL = re.compile(r"(?<![\w.+\-])[\w.+\-]+@[\w\-]+(?:\.[\w\-]+)+")
_PAN = re.compile(r"(?<![A-Za-z0-9])[A-Z]{5}\d{4}[A-Z](?![A-Za-z0-9])")
_PMJAY = re.compile(r"(?<![\w])PMJAY[\-/ ]?[A-Z]{0,3}[\-/ ]?\d{6,}", re.I)
_POLICY = re.compile(r"(?<![\w])(?:POL|POLICY)[/\-][A-Z0-9/\-]*\d{5,}", re.I)

# Labels that anchor an identity-bearing ID. Transactional IDs (bill, sample, visit...) are not listed.
_ID_LABELS = (
    r"uhid", r"hospital\s*uhid", r"mrn", r"mr\s*no", r"reg(?:istration)?\.?\s*(?:no|number|#|id)", r"ipd\s*(?:no|number|#|id)",
    r"ip\s*(?:no|number|#)", r"adm(?:ission)?\s*(?:no|number|#|id)", r"patient\s*(?:id|no|number|#)", r"pt\.?\s*id",
    r"case\s*(?:no|number)", r"file\s*(?:no|number)", r"op\s*(?:no|number|d\s*no)", r"cr\s*no",
    r"पंजीकरण\s*(?:सं\.?|संख्या|नं\.?|नंबर)", r"आईपीडी\s*(?:सं\.?|संख्या|नं\.?)", r"रोगी\s*(?:आईडी|संख्या)",
)
_ID_LABEL_RX = re.compile(
    r"(?<![\w])(?:" + "|".join(_ID_LABELS) + r")\s*[:#\-]?\s*([A-Za-z0-9ऀ-ॿ][^\s,;|\"'<>\[\]]{3,})", re.I)

_CTX_AADHAAR = re.compile(r"(?:aadh?a+r|uid|आधार)", re.I)


def _digits_ok_phone(raw: str) -> bool:
    """A phone run is not a date/range: reject runs whose separators form many tiny groups."""
    groups = re.split(r"[ \-]", raw.lstrip("+"))
    return len(groups) <= 4 or all(len(g) >= 2 for g in groups)


def find_hard(text: str) -> list:
    """Return non-overlapping Spans for hard identifiers, sorted by start."""
    t = ascii_digits(text)
    found = []
    taken = []

    def free(s, e):  # taken never overlaps itself, so only a candidate's two neighbours matter
        i = bisect.bisect_left(taken, (s, e))
        return not ((i > 0 and taken[i - 1][1] > s) or (i < len(taken) and taken[i][0] < e))

    def add(s, e, kind, conf=1.0):
        if free(s, e):
            bisect.insort(taken, (s, e))
            found.append(Span(s, e, kind, conf))

    for m in _PMJAY.finditer(t):
        add(m.start(), m.end(), "INSURANCE")
    for m in _POLICY.finditer(t):
        add(m.start(), m.end(), "INSURANCE")
    for m in _ABHA_ADDR.finditer(t):
        add(m.start(), m.end(), "ABHA")
    for m in _EMAIL.finditer(t):
        add(m.start(), m.end(), "EMAIL")
    for m in _PAN.finditer(t):
        add(m.start(), m.end(), "PAN")
    for m in _AADHAAR_MASK.finditer(t):
        add(m.start(), m.end(), "AADHAAR")
    for m in _ABHA.finditer(t):
        add(m.start(), m.end(), "ABHA")
    for m in _PHONE_RUN.finditer(t):
        raw = m.group(0)
        d = re.sub(r"\D", "", raw)
        if len(d) == 12 and raw[0] != "+" and not raw.startswith("91") and _AADHAAR.fullmatch(raw):
            add(m.start(), m.end(), "AADHAAR")
        elif phone_core(raw) and _digits_ok_phone(raw):
            add(m.start(), m.end(), "PHONE")
    for m in _AADHAAR.finditer(t):
        ctx = t[max(0, m.start() - 12):m.start()]
        raw = m.group(0)
        spaced = bool(re.search(r"[ \-]", raw))
        if spaced or _CTX_AADHAAR.search(ctx):
            add(m.start(), m.end(), "AADHAAR")
    for m in _AADHAAR_FUZZY.finditer(t):
        v = m.group(1)
        if sum(c.isdigit() for c in v) >= 8 and v.replace(" ", "")[0] in "23456789OolI":
            add(m.start(1), m.end(1), "AADHAAR")
    for m in _ID_LABEL_RX.finditer(t):
        val = m.group(1).rstrip(".-_/:)(")
        if re.search(r"\d", val):
            add(m.start(1), m.start(1) + len(val), "ID")
    return sorted(found)
