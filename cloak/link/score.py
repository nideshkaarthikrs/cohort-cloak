"""Pairwise Fellegi-Sunter-style scoring with hard cannot-link constraints (weights hand-set, see README)."""
import re
from functools import lru_cache

from rapidfuzz import fuzz

W_STRONG_ID = 12
W_PHONE = 12
W_FULL_NAME = 6
W_GIVEN_ONLY = 2
W_DOB = 7
W_DOB_SWAP = 5
W_REL = 5
W_VILLAGE = 3
W_YEAR = 2
W_DEMOTED = 3

STRONG_KINDS = ("mrn", "aadhaar", "abha", "abhaaddr", "email", "insurance")


def _cons(t: str) -> str:
    return re.sub(r"[aeiou]", "", t)


@lru_cache(maxsize=200000)
def _tok_eq(a: str, b: str) -> bool:
    if a == b:
        return True
    if len(a) >= 5 and len(b) >= 5 and fuzz.ratio(a, b) >= 88:
        return True
    ca, cb = _cons(a), _cons(b)  # Devanagari renderings keep schwas Latin spellings drop
    return len(ca) >= 4 and ca == cb and a[0] == b[0]


@lru_cache(maxsize=200000)
def _tok_close(a: str, b: str) -> bool:
    """Loose equality used only for cannot-link: spelling variants must not be mistaken for different people."""
    return a == b or (len(a) >= 4 and len(b) >= 4 and a[0] == b[0] and fuzz.ratio(a, b) >= 75)


@lru_cache(maxsize=200000)
def name_relation(a: frozenset, b: frozenset, loose: bool = False) -> str:
    """'full' (same tokens), 'compat' (one contains the other), 'share' (conflicting overlap), 'none'."""
    if not a or not b:
        return "none"
    small, big = (a, b) if len(a) <= len(b) else (b, a)
    eq = _tok_close if loose else _tok_eq
    matched = sum(1 for t in small if any(eq(t, u) for u in big))
    if matched == len(small):
        return "full" if len(a) == len(b) else "compat"
    return "share" if matched else "none"


def name_conflict(a, b) -> bool:
    """Both full names present (>= 2 tokens each) and incompatible."""
    if len(a.tokens) < 2 or len(b.tokens) < 2:
        return False
    return name_relation(a.tokens, b.tokens, True) in ("share", "none")


def places_match(sa: set, sb: set) -> bool:
    return any(x == y or (len(x) >= 4 and len(y) >= 4 and fuzz.ratio(x, y) >= 85) for x in sa for y in sb)


def dob_relation(a, b):
    """'same', 'swap', 'diff' or None when either side has no DOB."""
    if not a.dobs or not b.dobs:
        return None
    if a.dob_raw & b.dob_raw:
        return "same"
    for ra in a.dobs:
        for rb in b.dobs:
            inter = ra & rb
            if inter:
                return "same" if (len(ra) == 1 or len(rb) == 1) else "swap"
    return "diff"


def birth_gap(a, b):
    if a.birth is None or b.birth is None:
        return 0
    return max(0, max(a.birth[0], b.birth[0]) - min(a.birth[1], b.birth[1]))


def cannot_link(a, b) -> bool:
    if a.gender and b.gender and a.gender != b.gender:
        return True
    if dob_relation(a, b) == "diff":
        return True
    if birth_gap(a, b) > 2:
        return True
    for kind in ("aadhaar", "abha"):
        sa, sb = a.ids.get(kind), b.ids.get(kind)
        if sa and sb and not (sa & sb):
            return True
    return name_conflict(a, b)


def score(a, b, demoted: set):
    """Return (weight, backed_by_hard_id). `demoted` holds ids/phones shared by incompatible records."""
    w, hard = 0, False
    for kind in STRONG_KINDS:
        shared = a.ids.get(kind, set()) & b.ids.get(kind, set())
        live = {s for s in shared if (kind, s) not in demoted}
        if live:
            w += W_STRONG_ID
            hard = hard or kind != "email"
        elif shared:
            w += W_DEMOTED
    phones = a.phones & b.phones
    if phones:
        w += W_PHONE if any(("phone", p) not in demoted for p in phones) else W_DEMOTED
    rel = name_relation(a.tokens, b.tokens)
    if rel == "full" and len(a.tokens) >= 2:
        w += W_FULL_NAME
    elif rel in ("full", "compat"):
        w += W_GIVEN_ONLY
    d = dob_relation(a, b)
    if d == "same":
        w += W_DOB
    elif d == "swap":
        w += W_DOB_SWAP
    if a.rel_tokens and b.rel_tokens and name_relation(a.rel_tokens, b.rel_tokens) in ("full", "compat"):
        w += W_REL
    if places_match(a.villages, b.villages):
        w += W_VILLAGE
    if a.birth and b.birth and birth_gap(a, b) <= 1 and not (a.dobs and b.dobs):
        w += W_YEAR
    return w, hard
