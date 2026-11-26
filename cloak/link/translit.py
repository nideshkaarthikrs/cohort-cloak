"""Cross-script, cross-spelling name keys (shared by detection and, in Phase 4, linking)."""
import re
import unicodedata
from functools import lru_cache

from indic_transliteration import sanscript

from cloak.detect.lexicon import STOP, TITLES, variant_groups

_DEVA = re.compile(r"[ऀ-ൿ]")
_SPLIT = re.compile(r"[^A-Za-zऀ-ൿء-ٟٱ-ۓ']+")


@lru_cache(maxsize=50000)
def to_latin(text: str) -> str:
    if not _DEVA.search(text):
        return text
    return "".join(_run(m.group(0)) for m in _RUNS.finditer(text)) if _DEVA.search(text) else text


_SCHEMES = ((0x0900, 0x097F, sanscript.DEVANAGARI), (0x0980, 0x09FF, sanscript.BENGALI), (0x0A00, 0x0A7F, sanscript.GURMUKHI),
            (0x0A80, 0x0AFF, sanscript.GUJARATI), (0x0B00, 0x0B7F, sanscript.ORIYA), (0x0B80, 0x0BFF, sanscript.TAMIL),
            (0x0C00, 0x0C7F, sanscript.TELUGU), (0x0C80, 0x0CFF, sanscript.KANNADA), (0x0D00, 0x0D7F, sanscript.MALAYALAM))
_RUNS = re.compile(r"[ऀ-ൿ]+|[^ऀ-ൿ]+")


def _run(chunk: str) -> str:
    if not _DEVA.match(chunk):
        return chunk
    cp = ord(chunk[0])
    for lo, hi, scheme in _SCHEMES:
        if lo <= cp <= hi:
            return sanscript.transliterate(chunk, scheme, sanscript.ITRANS)
    return chunk


@lru_cache(maxsize=50000)
def skeleton(token: str) -> str:
    """Phonetic skeleton: equal for common spelling variants and for Latin/Devanagari renderings."""
    t = unicodedata.normalize("NFKD", to_latin(token).replace("M", "n").replace("~N", "n")).casefold()
    t = re.sub(r"[^a-z]", "", t)
    if not t:
        return ""
    for a, b in (("sh", "s"), ("ph", "f"), ("ck", "k"), ("ee", "i"), ("ii", "i"), ("oo", "u"), ("uu", "u"),
                 ("aa", "a"), ("w", "v"), ("z", "j"), ("q", "k"), ("x", "ks")):
        t = t.replace(a, b)
    t = re.sub(r"(?<=[bcdfgjklmnpqrstvy])h", "", t)  # aspirate after a consonant (th, dh, kh, bh...)
    t = re.sub(r"(.)\1+", r"\1", t)
    if len(t) >= 4 and t.endswith("a"):
        t = t[:-1]
    return t


@lru_cache(maxsize=None)
def _canon_map() -> dict:
    m = {}
    for g in variant_groups():
        for t in g:
            m[t] = g[0]
    return m


def canonical_token(tok: str) -> str:
    t = unicodedata.normalize("NFKC", tok).casefold().strip("'.")
    return _canon_map().get(t, t)


def name_tokens_for_key(name: str) -> list:
    out = []
    for raw in _SPLIT.split(name):
        t = canonical_token(raw)
        if not t or t in TITLES or t in STOP or len(t) < 2:
            continue
        out.append(t)
    return out


_GENERIC_PLACE = frozenset({"khurd", "kalan", "kala", "nagar", "pur", "ganj"})


def consonants(token: str) -> str:
    """Vowel-free skeleton for place names, where schwa deletion makes vowels unreliable across scripts."""
    return re.sub(r"[aeiou]", "", skeleton(token))


def place_key(text: str) -> str:
    toks = [consonants(t) for t in name_tokens_for_key(text)]
    return " ".join(sorted(t for t in toks if len(t) >= 2))


def name_key(name: str) -> str:
    """Order-insensitive key: canonical spelling variants, skeletons, sorted."""
    return " ".join(sorted(skeleton(t) for t in name_tokens_for_key(name) if skeleton(t)))
