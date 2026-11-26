"""Name knowledge: the run-time known-name dictionary and the Faker/hand-written gazetteer."""
import re
import unicodedata
from functools import lru_cache

from cloak.detect.guards import guard_spans, guarded, overlaps_guard
from cloak.detect.lexicon import LEX_DIR, STOP, TITLES, medical_words, variant_groups, words
from cloak.link.translit import skeleton

_TITLES = TITLES
_STOP = STOP
_TOKEN_SPLIT = re.compile(r"[^\wऀ-ॿ']+")
_WORD = re.compile(r"[A-Za-z]+(?:'[A-Za-z]+)?|[ऀ-ॣॱ-ॿ]+")
_GAP = re.compile(r"[ \t.,]{1,2}")


NOT_NAME_CAPS = frozenset({
    "Mobile", "Mob", "Phone", "Ph", "Attendant", "Visitor", "Bed", "Ward", "Patient", "Tab", "Cap", "Inj", "Syp", "Rx",
    "Next", "Review", "Advice", "Diagnosis", "History", "Address", "Name", "Age", "Sex", "Date", "Time", "Consultant",
    "Doctor", "Hospital", "Medicine", "Surgery", "Dr", "Contact", "Called", "Informed", "Raised", "Reported", "Guardian",
    "The", "Fever", "Cough", "Gate", "Sample", "Report", "Received", "Mr", "Mrs", "Ms", "Shri", "Smt", "Visit", "Treated",
    "Continue", "Discharge", "Discharged", "Admitted", "Presenting", "Course", "Medications", "Essential", "Review",
    "Low", "Salt", "Diet", "Patient", "Nursing", "Notes", "Note", "Today", "Next", "Morning", "Evening", "Night"})


def is_non_name(tok: str) -> bool:
    t = tok.strip(".,'").casefold()
    return (not t or tok.strip(".,") in NOT_NAME_CAPS or t in medical_words() or t in words("hinglish_stopwords.txt")
            or t in _STOP or t in _TITLES)


def norm_token(t: str) -> str:
    return unicodedata.normalize("NFKC", t).casefold().strip("'.")


def name_tokens(name: str) -> list:
    out = []
    for raw in _TOKEN_SPLIT.split(name):
        t = norm_token(raw)
        if not t or t in _TITLES or t in _STOP or any(ch.isdigit() for ch in t) or "_" in t:
            continue
        if len(t) < 3 and not re.search(r"[ऀ-ॿ]", t):
            continue
        if len(t) < 2:
            continue
        out.append(t)
    return out


def _is_capitalised(w: str) -> bool:
    return w[:1].isupper() or bool(re.match(r"[ऀ-ॿ]", w))


def iter_words(text: str):
    """Yield (start, end, word) for letter-word tokens (apostrophes kept, underscores/digits split)."""
    for m in _WORD.finditer(text):
        yield m.start(), m.end(), m.group(0)


def merge_spans(spans, text: str):
    """Merge overlapping spans and spans separated only by a short whitespace/punctuation gap on one line."""
    out = []
    for s, e in sorted(spans):
        if out and (s <= out[-1][1] or (_GAP.fullmatch(text[out[-1][1]:s] or "") and "\n" not in text[out[-1][1]:s])):
            out[-1] = (out[-1][0], max(e, out[-1][1]))
        else:
            out.append((s, e))
    return out


class NameDict:
    """Every name seen in a structured role, matched across spellings and scripts."""

    def __init__(self):
        self._tokens = set()
        self._skels = set()

    def __len__(self):
        return len(self._tokens)

    def add(self, name: str, kind: str = "patient") -> None:
        for t in name_tokens(name):
            self._tokens.add(t)
            for g in variant_groups():
                if t in g:
                    self._tokens.update(x for x in g if len(x) >= 3)  # 'md' is also a credential
        self._skels = {s for s in (skeleton(t) for t in self._tokens) if len(s) >= 3}

    def has_token(self, tok: str) -> bool:
        return norm_token(tok) in self._tokens

    def matches_word(self, w: str) -> bool:
        n = norm_token(w)
        if n in self._tokens:
            if n in medical_words() and not _is_capitalised(w):
                return False
            return True
        if len(n) >= 4 and n not in medical_words() and n not in words("hinglish_stopwords.txt"):
            s = skeleton(w)
            return len(s) >= 3 and s in self._skels
        return False

    def find(self, text: str, guards=None) -> list:
        if not self._tokens:
            return []
        guards = guard_spans(text) if guards is None else guards
        spans = [(s, e) for s, e, w in iter_words(text) if self.matches_word(w) and not overlaps_guard(guards, s, e)]
        return merge_spans(spans, text)

    def scrub(self, text: str):
        spans = self.find(text)
        for s, e in reversed(spans):
            text = text[:s] + "[NAME]" + text[e:]
        return text, len(spans)


@lru_cache(maxsize=None)
def _gaz_sets():
    g = {"given": set(), "surname": set()}
    for kind, files in (("given", ("given_latin.txt", "given_deva.txt")), ("surname", ("surname_latin.txt", "surname_deva.txt"))):
        for f in files:
            g[kind] |= words(f)
    for grp in variant_groups():  # spelling variants (mohd, muhammad...) count as given names
        g["given"].update(x for x in grp if len(x) >= 3)
    skel = {k: {s for s in (skeleton(t) for t in v) if len(s) >= 3} for k, v in g.items()}
    return g, skel


class Gazetteer:
    """Given-name and surname lists (Faker en_IN/hi_IN plus hand lists) in Latin and Devanagari."""

    @staticmethod
    def kind(w: str):
        """'given', 'surname', 'both' or None for a word."""
        n = norm_token(w)
        if len(n) < 3 and not re.match(r"[ऀ-ॿ]", n):
            return None
        if n in medical_words() or n in words("hinglish_stopwords.txt") or n in _STOP or n in _TITLES:
            return None
        sets, skels = _gaz_sets()
        s = skeleton(w)
        hit = {k for k in sets if n in sets[k] or (len(n) >= 4 and len(s) >= 3 and s in skels[k])}
        if not hit:
            return None
        return "both" if len(hit) == 2 else next(iter(hit))

    @classmethod
    def known(cls, w: str) -> bool:
        return cls.kind(w) is not None

    @classmethod
    def runs(cls, text: str, guards=None) -> list:
        """Spans of likely personal names (medium confidence), outside protected spans:
        two adjacent list words, a list given name + an unknown capitalised word, or an unknown
        capitalised word + a list surname. Devanagari words need no capitalisation."""
        guards = guard_spans(text) if guards is None else guards
        toks = [(s, e, w, cls.kind(w) if _is_capitalised(w) else None) for s, e, w in iter_words(text)]
        free = [not overlaps_guard(guards, s, e) for s, e, _w, _k in toks]
        adj = [bool(re.fullmatch(r"[ \t]|\.[ \t]", text[toks[i][1]:toks[i + 1][0]] or "x")) for i in range(len(toks) - 1)]

        def plain(i):  # unknown capitalised word that could be part of a name
            w = toks[i][2]
            return (toks[i][3] is None and free[i] and _is_capitalised(w) and w[:1].isupper() and len(w) >= 3
                    and not is_non_name(w) and w.casefold() not in words("filename_words.txt"))

        out = []
        for i in range(len(toks) - 1):
            if not adj[i]:
                continue
            a, b = toks[i][3], toks[i + 1][3]
            if a and b and free[i] and free[i + 1]:
                out.append((toks[i][0], toks[i + 1][1]))
            elif a in ("given", "both") and free[i] and plain(i + 1):
                out.append((toks[i][0], toks[i + 1][1]))
            elif b in ("surname", "both") and free[i + 1] and plain(i):
                out.append((toks[i][0], toks[i + 1][1]))
        return merge_spans(out, text)
