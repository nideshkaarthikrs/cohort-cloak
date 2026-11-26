"""Blocking: candidate pairs from shared IDs, phones, DOB and name-token skeletons."""
import re
from itertools import combinations

MAX_BLOCK = 400


def _cons(t: str) -> str:
    return re.sub(r"[aeiou]", "", t)


def blocks(evidences: list) -> dict:
    index = {}
    for i, ev in enumerate(evidences):
        keys = set()
        for kind, vals in ev.ids.items():
            keys.update(("id", kind, v) for v in vals)
        keys.update(("phone", p) for p in ev.phones)
        keys.update(("dob", raw) for raw in ev.dob_raw)
        for t in ev.tokens:
            if len(t) >= 3:
                keys.add(("tok", t))
            c = _cons(t)  # Devanagari keeps schwas Latin spellings drop, so vowel-free keys catch those pairs
            if len(c) >= 3:
                keys.add(("ctok", t[0], c))
        for k in keys:
            index.setdefault(k, []).append(i)
    return index


def candidate_pairs(evidences: list) -> list:
    pairs = set()
    for key in sorted(blocks(evidences).items(), key=lambda kv: repr(kv[0])):
        members = key[1]
        if len(members) < 2 or len(members) > MAX_BLOCK:
            continue
        pairs.update(combinations(members, 2))
    return sorted(pairs)
