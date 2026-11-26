"""Dates in every common format: find, resolve (d/m vs m/d inference), shift by whole days, print in the same shape."""
import datetime as dt
import re
from collections import defaultdict
from dataclasses import dataclass

EN_FULL = ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
           "november", "december"]
EN_ABBR = [m[:3] for m in EN_FULL]
HI_MONTHS = ["जनवरी", "फ़रवरी", "मार्च", "अप्रैल", "मई", "जून", "जुलाई", "अगस्त", "सितंबर", "अक्टूबर", "नवंबर", "दिसंबर"]
_HI_LOOKUP = {m: i + 1 for i, m in enumerate(HI_MONTHS)}
_HI_LOOKUP.update({"फरवरी": 2, "सितम्बर": 9, "नवम्बर": 11, "दिसम्बर": 12, "जानेवारी": 1, "फेब्रुवारी": 2, "एप्रिल": 4, "मे": 5, "जुलै": 7, "ऑगस्ट": 8, "सप्टेंबर": 9, "ऑक्टोबर": 10, "नोव्हेंबर": 11, "डिसेंबर": 12})
_EN_LOOKUP = {}
for _i, (_f, _a) in enumerate(zip(EN_FULL, EN_ABBR)):
    _EN_LOOKUP[_f] = _i + 1
    _EN_LOOKUP[_a] = _i + 1
_EN_LOOKUP["sept"] = 9

_NUM = re.compile(r"(?<![\w/\-.:])(\d{1,4})([/\-.])(\d{1,2})\2(\d{1,4})(?:(?=T\d)|(?![\w/\-:]|\.\d))")
_MON_EN = "|".join(sorted(_EN_LOOKUP, key=len, reverse=True))
_TXT_DMY = re.compile(r"(?<![\w])(\d{1,2})(?:st|nd|rd|th)?([ \-./]+)(" + _MON_EN + r")\.?(?:([ \-./,]+)(\d{4}))?(?![\w])", re.I)
_TXT_MDY = re.compile(r"(?<![\w])(" + _MON_EN + r")\.?[ ]+(\d{1,2})(?:st|nd|rd|th)?,?[ ]+(\d{4})(?![\w])", re.I)
_HI_RX = "|".join(sorted(_HI_LOOKUP, key=len, reverse=True))
_HI = re.compile(r"(?<![\w])(\d{1,2})([ ]+)(" + _HI_RX + r")(?:([ ,]+)(\d{4}))?(?![ऀ-ॿ])")


@dataclass
class DateTok:
    start: int
    end: int
    kind: str          # num | txt_dmy | txt_mdy | hi
    year: object       # int or None (no-year)
    month: int
    day: int
    layout: str = ""   # numeric: ymd | dmy | mdy
    seps: tuple = ()
    widths: tuple = ()  # printed widths of the three numeric parts (for zero padding)
    month_style: str = ""   # txt: 'full' | 'abbr' ; case: 'lower' | 'upper' | 'title'
    raw_month: str = ""
    ordinal: str = ""
    ambiguous: bool = False

    def as_date(self, ref_year: int) -> dt.date:
        return dt.date(self.year or ref_year, self.month, self.day)

    def render(self, days: int, ref_year: int) -> str:
        d = self.as_date(ref_year) + dt.timedelta(days=days)
        if self.kind == "num":
            parts = {"y": d.year, "m": d.month, "d": d.day}
            out = []
            for sym, width in zip(self.layout, self.widths):
                v = parts[{"y": "y", "m": "m", "d": "d"}[sym]]
                s = str(v)
                if sym == "y" and width == 2:
                    s = f"{v % 100:02d}"
                else:
                    s = s.zfill(width) if width > 1 else s
                out.append(s)
            return out[0] + self.seps[0] + out[1] + self.seps[1] + out[2]
        if self.kind == "hi":
            mon = HI_MONTHS[d.month - 1]
            s = f"{d.day}{self.seps[0]}{mon}"
            return s + (f"{self.seps[1]}{d.year}" if self.year else "")
        name = (EN_FULL if self.month_style == "full" else EN_ABBR)[d.month - 1]
        name = name.upper() if self.month_style_case == "upper" else name.title() if self.month_style_case == "title" else name
        if self.kind == "txt_mdy":
            return f"{name} {d.day}, {d.year}" if self.seps[0] == "," else f"{name} {d.day} {d.year}"
        s = f"{d.day}{self.ordinal}{self.seps[0]}{name}"
        return s + (f"{self.seps[1]}{d.year}" if self.year else "")

    @property
    def month_style_case(self) -> str:
        r = self.raw_month
        return "upper" if r.isupper() else "title" if r[:1].isupper() else "lower"


def _valid(y, m, d) -> bool:
    try:
        dt.date(y, m, d)
        return True
    except ValueError:
        return False


def _month_style(raw: str) -> str:
    return "full" if raw.casefold() in EN_FULL else "abbr"


def find_dates(text: str, order: str = "dmy", skip=(), votes=None, order_for=None, soft_skip=()) -> list:
    """Return DateTok objects. `order` resolves ambiguous numeric dates ('dmy'|'mdy'); `order_for(raw)` may override.
    `skip` holds (start, end) spans never treated as dates. `votes` collects 'dmy'/'mdy' evidence from unambiguous ones."""
    out = []

    def blocked(s, e):
        # `skip` spans always block; `soft_skip` spans (e.g. the range "05-26" inside 26-05-2026) only when they
        # reach outside the candidate date
        return (any(s < b and a < e for a, b in skip)
                or any(s < b and a < e and not (s <= a and b <= e) for a, b in soft_skip))

    for m in _NUM.finditer(text):
        if blocked(m.start(), m.end()):
            continue
        g1, sep, g2, g3 = m.group(1), m.group(2), m.group(3), m.group(4)
        s1, s2 = m.group(2), m.group(2)
        widths = (len(g1), len(g2), len(g3))
        tok = None
        if len(g1) == 4:
            y, mo, d = int(g1), int(g2), int(g3)
            if len(g3) <= 2 and _valid(y, mo, d):
                tok = DateTok(m.start(), m.end(), "num", y, mo, d, "ymd", (s1, s2), widths)
        elif len(g3) in (2, 4) and len(g1) <= 2:
            a, b, c = int(g1), int(g2), int(g3)
            if len(g3) == 2:
                if sep != "/" or a == 0 or b == 0:
                    continue
                y = 2000 + c if c <= 69 else 1900 + c
            else:
                y = c
            if not 1900 <= y <= 2100:
                continue
            if a > 12 and b <= 12:
                layout, amb = "dmy", False
            elif b > 12 and a <= 12:
                layout, amb = "mdy", False
            elif a <= 12 and b <= 12:
                layout, amb = (order_for(m.group(0)) if order_for else order), True
            else:
                continue
            if layout == "dmy":
                day, mon = a, b
            else:
                day, mon = b, a
            if _valid(y, mon, day):
                tok = DateTok(m.start(), m.end(), "num", y, mon, day, layout, (s1, s2), widths, ambiguous=amb)
                if votes is not None and not amb:
                    votes.append(layout)
                # printed layout symbols for numeric render
                tok.layout = "dmy" if layout == "dmy" else "mdy"
        if tok:
            out.append(tok)
    for m in _TXT_DMY.finditer(text):
        if blocked(m.start(), m.end()):
            continue
        raw = m.group(3)
        if raw.lower() == "may" and not (raw[0].isupper() or m.group(5)):
            continue
        d, mon = int(m.group(1)), _EN_LOOKUP[raw.casefold()]
        y = int(m.group(5)) if m.group(5) else None
        if _valid(y or 2024, mon, d):
            tok = DateTok(m.start(), m.end(), "txt_dmy", y, mon, d, seps=(m.group(2), m.group(4) or ""),
                          month_style=_month_style(raw), raw_month=raw,
                          ordinal=re.sub(r"[\d]", "", m.group(0).split(m.group(2))[0]))
            out.append(tok)
    for m in _TXT_MDY.finditer(text):
        if blocked(m.start(), m.end()):
            continue
        raw = m.group(1)
        mon, d, y = _EN_LOOKUP[raw.casefold()], int(m.group(2)), int(m.group(3))
        if _valid(y, mon, d):
            sep = "," if re.search(r"\d,", m.group(0)) else " "
            out.append(DateTok(m.start(), m.end(), "txt_mdy", y, mon, d, seps=(sep,), month_style=_month_style(raw),
                               raw_month=raw))
    for m in _HI.finditer(text):
        if blocked(m.start(), m.end()):
            continue
        d, mon = int(m.group(1)), _HI_LOOKUP[m.group(3)]
        y = int(m.group(5)) if m.group(5) else None
        if _valid(y or 2024, mon, d):
            out.append(DateTok(m.start(), m.end(), "hi", y, mon, d, seps=(m.group(2), m.group(4) or " ")))
    out.sort(key=lambda t: t.start)
    kept, last = [], -1
    for t in out:  # no overlaps
        if t.start >= last:
            kept.append(t)
            last = t.end
    return kept


def shift_text(text: str, days: int, order: str = "dmy", ref_year: int = 2026) -> str:
    toks = find_dates(text, order)
    for t in reversed(toks):
        text = text[:t.start] + t.render(days, ref_year) + text[t.end:]
    return text


class OrderVotes:
    """d/m vs m/d evidence from unambiguous dates, by source (file+column/label), file, and file-name tokens."""

    def __init__(self):
        self._v = defaultdict(lambda: defaultdict(int))

    def vote(self, key, layout: str, weight: int = 1) -> None:
        self._v[key][layout] += weight

    def _pick(self, keys):
        tot = defaultdict(int)
        for k in keys:
            for lay, n in self._v.get(k, {}).items():
                tot[lay] += n
        if not tot or tot["dmy"] == tot["mdy"]:
            return None
        return max(tot, key=tot.get)

    def order(self, source_key, file_keys, default: str = "dmy") -> str:
        return (self._pick([source_key]) or self._pick([file_keys[0]]) or self._pick(file_keys[1:]) or default)
