"""Column/key role inference: header synonyms plus a value profile. Values win for hard roles."""
import re
import unicodedata
from functools import lru_cache

from rapidfuzz import fuzz, process

from cloak.detect.lexicon import header_roles
from cloak.detect.patterns import find_hard

HARD_KIND_ROLE = {"PHONE": "phone", "AADHAAR": "aadhaar", "ABHA": "abha", "PAN": "pan", "EMAIL": "email",
                  "INSURANCE": "insurance"}
PII_ROLES = {"patient_name", "person_name", "relative_name", "phone", "email", "aadhaar", "abha", "pan", "mrn",
             "insurance", "address", "house", "locality", "landmark", "village", "pin", "dob"}

_CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
_NAME_LATIN = re.compile(r"^(?:[A-Z][A-Za-z'.\-]+|[A-Z]\.)(?:\s+(?:[A-Z][A-Za-z'.\-]+|[A-Z]\.)){0,3}$")
_NAME_DEVA = re.compile(r"^[ऀ-ൿء-ٟٱ-ۓ]+(?:\s+[ऀ-ൿء-ٟٱ-ۓ]+){0,3}$")


def norm_header(h: str) -> str:
    h = _CAMEL.sub(" ", h)
    out = []
    for ch in unicodedata.normalize("NFKC", h).casefold():
        out.append(ch if unicodedata.category(ch)[0] in "LNM" else " ")
    return " ".join("".join(out).split())


@lru_cache(maxsize=None)
def _phrase_table():
    table = {}
    for role, phrases in header_roles().items():
        for p in phrases:
            table.setdefault(p, role)
    return table


def _contains(tokens, phrase_tokens) -> bool:
    n = len(phrase_tokens)
    return any(tokens[i:i + n] == phrase_tokens for i in range(len(tokens) - n + 1))


@lru_cache(maxsize=100000)
def header_role(header: str):
    """Return (role, score) for a header/label/key, or (None, 0.0)."""
    h = norm_header(header)
    if not h:
        return None, 0.0
    table = _phrase_table()
    if h in table:
        return table[h], 1.0
    tokens = h.split()
    best = None
    for phrase, role in table.items():
        pt = phrase.split()
        if _contains(tokens, pt):
            key = (len(pt), len(phrase))
            if best is None or key > best[0]:
                best = (key, role)
    if best:
        return best[1], 0.9
    if len(h) >= 5:
        cutoff = 86 if len(tokens) == 1 else 93  # multi-word headers need a near-exact match
        hit = process.extractOne(h, list(table), scorer=fuzz.ratio, score_cutoff=cutoff)
        if hit:
            return table[hit[0]], 0.8
    return None, 0.0


def whole_cell_kind(cell: str):
    """Kind of the hard identifier covering >= 80% of the cell, else None."""
    c = cell.strip()
    if not c:
        return None
    for s in find_hard(c):
        if (s.end - s.start) >= 0.8 * len(c) and s.kind != "ID":
            return s.kind
    return None


_ID_MIXED = re.compile(r"^(?=(?:.*\d){4})(?=.*[A-Za-z])[A-Za-z0-9][A-Za-z0-9/\-_.:]{3,28}$")
_DATEISH = re.compile(r"^\d{1,4}[/\-.]\d{1,2}[/\-.]\d{1,4}$")


def looks_like_id(cell: str) -> bool:
    """A reference number: letters+digits (UHID-style) or a 6-12 digit string; never a date."""
    c = cell.strip()
    if _DATEISH.match(c):
        return False
    return bool(_ID_MIXED.match(c)) or bool(re.fullmatch(r"\d{6,12}", c))


def looks_like_name(cell: str) -> bool:
    c = cell.strip()
    return bool(_NAME_LATIN.match(c) or _NAME_DEVA.match(c))


def infer_roles(header, rows, sample: int = 300) -> list:
    """Role per column (None when unknown)."""
    roles = []
    for j, h in enumerate(header):
        role, score = header_role(h)
        cells = [r[j].strip() for r in rows[:sample] if j < len(r) and r[j].strip()]
        n = len(cells)
        if n:
            counts = {}
            for c in cells:
                k = whole_cell_kind(c)
                if k:
                    counts[k] = counts.get(k, 0) + 1
            if counts:
                kind = sorted(counts, key=lambda k: (-counts[k], k))[0]
                if counts[kind] / n >= 0.5:
                    role = HARD_KIND_ROLE[kind]
            if role is None and n >= 2:
                ids = [c for c in cells if looks_like_id(c)]
                if len(ids) / n >= 0.8 and len(set(cells)) / n >= 0.7:
                    role = "mrn"  # unknown header, values are reference numbers: fail closed
            if role is None and n >= 5:
                pins = [c for c in cells if re.fullmatch(r"[1-8]\d{5}", c)]
                if len(pins) / n >= 0.9 and len(set(pins)) / len(pins) <= 0.7:
                    role = "pin"  # unknown header, repeating 6-digit codes: postal codes repeat, amounts and references do not
            if role is None and n >= 3:
                names = [c for c in cells if looks_like_name(c)]
                multi = sum(1 for c in names if " " in c)
                if len(names) / n >= 0.8 and multi / n >= 0.5 and len(set(cells)) / n >= 0.5:
                    role = "patient_name"
        roles.append(role)
    return roles
