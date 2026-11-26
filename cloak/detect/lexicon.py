"""Loaders for the hand-written lexicons under data/lexicons/."""
from functools import lru_cache
from pathlib import Path

import yaml

LEX_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "lexicons"


@lru_cache(maxsize=None)
def header_roles() -> dict:
    """role -> list of normalised synonym phrases (file order is the priority order)."""
    from cloak.detect.columns import norm_header
    raw = yaml.safe_load((LEX_DIR / "header_roles.yaml").read_text(encoding="utf-8"))
    return {role: [norm_header(p) for p in phrases] for role, phrases in raw.items()}


TITLES = frozenset({"mr", "mrs", "ms", "miss", "shri", "shree", "smt", "sri", "km", "late", "dr", "prof", "master",
                    "baby", "ji", "sahab", "sahib", "bhai", "didi", "श्री", "श्रीमती", "सुश्री", "कुमारी", "स्व", "डॉ"})
STOP = frozenset({"ka", "ki", "ke", "ko", "ne", "hai", "aur", "the", "and", "of", "for", "with", "से", "का", "की", "के",
                  "को", "है", "और", "w/o", "s/o", "d/o", "c/o", "na", "nil", "none", "unknown"})


def _read_words(name: str, lower: bool = True) -> frozenset:
    try:
        text = (LEX_DIR / name).read_text(encoding="utf-8")
    except OSError:
        return frozenset()
    words = set()
    for line in text.splitlines():
        if line.startswith("#"):
            continue
        for w in line.split():
            words.add(w.casefold() if lower else w)
    return frozenset(words)


@lru_cache(maxsize=None)
def words(name: str) -> frozenset:
    """Word set from a lexicon file (one or many words per line, '#' comments)."""
    return _read_words(name)


@lru_cache(maxsize=None)
def medical_words() -> frozenset:
    out = set()
    for f in ("drugs.txt", "diseases.txt", "symptoms_en_hi.txt", "eponyms.txt", "lab_tests.txt", "units.txt",
              "departments.txt", "clinical_terms.txt"):
        out |= words(f)
    return frozenset(out)


@lru_cache(maxsize=None)
def variant_groups() -> tuple:
    groups = []
    try:
        for line in (LEX_DIR / "name_variants.tsv").read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                groups.append(tuple(line.split("|")))
    except OSError:
        pass
    return tuple(groups)
