"""Run-time known-name dictionary: every structured name is propagated to every channel."""
import re
import unicodedata
from functools import lru_cache

from cloak.detect.guards import guard_spans, guarded
from cloak.detect.lexicon import LEX_DIR

_TITLES = {"mr", "mrs", "ms", "miss", "shri", "shree", "smt", "sri", "km", "late", "dr", "prof", "master",
           "baby", "ji", "sahab", "sahib", "bhai", "didi", "श्री", "श्रीमती", "सुश्री", "कुमारी", "स्व", "डॉ"}
_STOP = {"ka", "ki", "ke", "ko", "ne", "hai", "aur", "the", "and", "of", "for", "with", "से", "का", "की", "के",
         "को", "है", "और", "w/o", "s/o", "d/o", "c/o", "na", "nil", "none", "unknown"}
_WORD = r"[^\W_]|[\u0900-\u097f]"
_TOKEN_SPLIT = re.compile(r"[^\w\u0900-\u097f']+")


def norm_token(t: str) -> str:
    return unicodedata.normalize("NFKC", t).casefold().strip("'.")


@lru_cache(maxsize=None)
def _variant_groups():
    groups = []
    try:
        for line in (LEX_DIR / "name_variants.tsv").read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                groups.append(tuple(line.split("|")))
    except OSError:
        pass
    return groups


def name_tokens(name: str) -> list:
    out = []
    for raw in _TOKEN_SPLIT.split(name):
        t = norm_token(raw)
        if not t or t in _TITLES or t in _STOP or any(ch.isdigit() for ch in t):
            continue
        if len(t) < 3 and not re.search(r"[\u0900-\u097f]", t):
            continue
        if len(t) < 2:
            continue
        out.append(t)
    return out


class NameDict:
    def __init__(self):
        self._tokens = set()
        self._rx = None

    def __len__(self):
        return len(self._tokens)

    def add(self, name: str, kind: str = "patient") -> None:
        for t in name_tokens(name):
            self._tokens.add(t)
            for g in _variant_groups():
                if t in g:
                    self._tokens.update(x for x in g if len(x) >= 3)  # 'md' is also a credential
        self._rx = None

    def has_token(self, tok: str) -> bool:
        return norm_token(tok) in self._tokens

    def _regex(self):
        if self._rx is None:
            if not self._tokens:
                self._rx = re.compile(r"(?!x)x")
            else:
                alts = "|".join(re.escape(t) for t in sorted(self._tokens, key=lambda x: (-len(x), x)))
                self._rx = re.compile(r"(?<!(?:" + _WORD + r"))(?:" + alts + r")(?!(?:" + _WORD + r"))", re.I)
        return self._rx

    def find(self, text: str, guards=None) -> list:
        """Return (start, end) spans of dictionary tokens outside protected spans, adjacent ones merged."""
        if not self._tokens:
            return []
        guards = guard_spans(text) if guards is None else guards
        spans = [(m.start(), m.end()) for m in self._regex().finditer(text) if not guarded(guards, m.start(), m.end())]
        merged = []
        for s, e in spans:
            if merged and re.fullmatch(r"[\s.,]{0,2}", text[merged[-1][1]:s]) and "\n" not in text[merged[-1][1]:s]:
                merged[-1] = (merged[-1][0], e)
            else:
                merged.append((s, e))
        return merged

    def scrub(self, text: str):
        spans = self.find(text)
        for s, e in reversed(spans):
            text = text[:s] + "[NAME]" + text[e:]
        return text, len(spans)
