"""Known identifiers (UHID/MRN/insurance/phone...) and shape induction from ID-role columns."""
import re

from cloak.detect.validators import ascii_digits

_CAND = re.compile(r"(?<![A-Za-z0-9])(?:[A-Za-z]{1,6}[\-/_ ]?)?\d[\d\-/_ .]{2,}\d(?![A-Za-z0-9])|(?<![A-Za-z0-9])[A-Za-z]{1,6}\d{3,}(?![A-Za-z0-9])")


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
        if t.isalpha():
            parts.append(f"[A-Za-z]{{{len(t)}}}")
        elif t.isdigit():
            parts.append(f"\\d{{{len(t)}}}")
        else:
            parts.append(r"[\-/_ .]?")
    src = "".join(parts)
    # collapse separator-optional neighbours into one
    src = re.sub(r"(?:\[\\-/_ \.\]\?){2,}", r"[\\-/_ .]?", src)
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
            if self.has_token(m.group(0).strip(" .-/_")):
                s = m.start() + len(m.group(0)) - len(m.group(0).lstrip(" .-/_"))
                spans.append((s, m.start() + len(m.group(0).rstrip(" .-/_"))))
        for m in self._shape_regex().finditer(t):
            spans.append((m.start(), m.end()))
        return sorted(set(spans))
