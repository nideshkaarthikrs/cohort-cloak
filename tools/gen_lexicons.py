#!/usr/bin/env python3
"""Generate the name gazetteers under data/lexicons/ from Faker (en_IN, hi_IN) plus hand-written lists.

Dev data is never read. Run:  python tools/gen_lexicons.py   (needs Faker from requirements-dev.txt)
Outputs (sorted, one token per line): given_latin.txt surname_latin.txt given_deva.txt surname_deva.txt
"""
import re
from pathlib import Path

from faker import Faker

LEX = Path(__file__).resolve().parent.parent / "data" / "lexicons"
TOKEN = re.compile(r"[A-Za-z]+|[\u0900-\u0963\u0971-\u097f]+")


def provider_lists(locale):
    f = Faker(locale)
    p = next(x for x in f.providers if "person" in x.__module__)
    first = list(getattr(p, "first_names", []))
    last = list(getattr(p, "last_names", []))
    return first, last


def tokens(names, deva):
    out = set()
    for n in names:
        for t in TOKEN.findall(n):
            t = t.casefold() if not deva else t
            if len(t) >= 3 or (deva and len(t) >= 2):
                out.add(t)
    return out


def hand(name):
    p = LEX / name
    return set(re.findall(r"[^\s#]+", "\n".join(l for l in p.read_text(encoding="utf-8").splitlines() if not l.startswith("#"))))


def write(name, items):
    (LEX / name).write_text("\n".join(sorted(items)) + "\n", encoding="utf-8")
    print(name, len(items))


def main():
    en_first, en_last = provider_lists("en_IN")
    hi_first, hi_last = provider_lists("hi_IN")
    write("given_latin.txt", tokens(en_first, False) | {t.casefold() for t in hand("hand_given.txt")})
    write("surname_latin.txt", tokens(en_last, False) | {t.casefold() for t in hand("hand_surnames.txt")})
    write("given_deva.txt", tokens(hi_first, True) | hand("hand_given_deva.txt"))
    write("surname_deva.txt", tokens(hi_last, True) | hand("hand_surnames_deva.txt"))


if __name__ == "__main__":
    main()
