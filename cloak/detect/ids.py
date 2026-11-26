"""Known identifiers (UHID/MRN/insurance/phone...) and shape induction from ID-role columns."""
import re

from cloak.detect.validators import ascii_digits

_CAND = re.compile(r"(?<![A-Za-z0-9])(?:[A-Za-z]{1,6}[\-/_ ]?)?\d[\d\-/_ .]{2,}\d(?![A-Za-z0-9])|(?<![A-Za-z0-9])[A-Za-z]{1,6}\d{3,}(?![A-Za-z0-9])")


_TOK = re.compile(r"[^\s\"',;|<>\[\]]{5,40}")


def alnum(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", ascii_digits(s).casefold())


def shape_regex(value: str):
    """Regex source matching other IDs shaped like `value` (letter/digit run lengths, loose separators)."""
    v = ascii_digits(value.strip())
    if not (4 <= len(v) <= 30) or len(re.findall(r"\d", v)) < 3:
        return None
    parts = []
    for m in re.finditer(r"[A-Za-z]+|\d+|[^A-Za-z\d]+", v):
        t = m.group(0)
        if t.isalpha():  # an ID prefix is written in one case; Title-case words (names) must not match
            parts.append(f"(?:[A-Z]{{{len(t)}}}|[a-z]{{{len(t)}}})")
        elif t.isdigit():
            parts.append(f"\\d{{{len(t)}}}")
        else:
            parts.append(r"(?:[^\sA-Za-z\d]{1,2}| )?")
    src = "".join(parts)
    # collapse separator-optional neighbours into one
    src = re.sub(r"(?:\(\?:\[\^\\sA-Za-z\\d\]\{1,2\}\| \)\?){2,}", r"(?:[^\\sA-Za-z\\d]{1,2}| )?", src)
    if len(re.sub(r"\D", "", v)) < 5:
        return None  # too few digits: the shape would match ordinary words followed by a year
    has_letter = bool(re.search(r"[A-Za-z]", v))
    if not has_letter and len(re.sub(r"\D", "", v)) < 9:
        return None  # bare short numbers (PINs, counts) must not become a shape
    return src if re.search(r"\\d\{\d+\}", src) else None


class IdSet:
    def __init__(self):
        self._full = set()
        self._cores = set()
        self._shapes = set()
        self._shape_rx = None

    def add(self, value, shape: bool = True) -> None:
        v = ascii_digits(str(value)).strip()
        if not v:
            return
        a = alnum(v)
        if len(a) >= 4:
            self._full.add(a)
        for run in re.findall(r"\d+", v):
            if len(run) >= 6:
                self._cores.add(run)
        digits = re.sub(r"\D", "", v)
        if len(digits) >= 6:
            self._cores.add(digits)
        if shape:
            s = shape_regex(v)
            if s:
                self._shapes.add(s)
                self._shape_rx = None

    def has_token(self, tok: str) -> bool:
        a = alnum(tok)
        if a in self._full:
            return True
        d = re.sub(r"\D", "", ascii_digits(tok))
        return len(d) >= 6 and d in self._cores

    def _shape_regex(self):
        if self._shape_rx is None:
            if self._shapes:
                alts = "|".join(sorted(self._shapes))
                self._shape_rx = re.compile(r"(?<![A-Za-z0-9])(?:" + alts + r")(?![A-Za-z0-9])")
            else:
                self._shape_rx = re.compile(r"(?!x)x")
        return self._shape_rx

    def find(self, text: str) -> list:
        """(start, end) spans of known IDs and ID-shaped strings."""
        t = ascii_digits(text)
        spans = []
        for m in _CAND.finditer(t):
            raw = m.group(0)
            if not self.has_token(raw.strip(" .-/_")):
                continue
            s, e = m.start(), m.end()
            if alnum(raw) not in self._full:  # matched by its digits only: never swallow a preceding word
                first = re.search(r"\d", raw)
                s += first.start()
            lead = len(t[s:e]) - len(t[s:e].lstrip(" .-/_"))
            trail = len(t[s:e]) - len(t[s:e].rstrip(" .-/_"))
            spans.append((s + lead, e - trail))
        for m in self._shape_regex().finditer(t):
            spans.append((m.start(), m.end()))
        if self._full:  # exact known IDs with unusual punctuation (NC~4137~Q, TR{26}.4211, ZC@4248/26)
            for m in _TOK.finditer(t):
                tok = m.group(0)
                for cand in {tok, tok.split("=")[-1]}:
                    c = cand.strip(".:()-/_`^=")
                    if len(alnum(c)) >= 6 and alnum(c) in self._full:
                        i = tok.find(c)
                        spans.append((m.start() + i, m.start() + i + len(c)))
        return sorted(set(spans))
