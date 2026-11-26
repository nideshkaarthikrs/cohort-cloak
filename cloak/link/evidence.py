"""Per-record identity evidence built from the events the scrubber emits while rewriting."""
import re
from dataclasses import dataclass, field

from cloak.detect.names import Gazetteer
from cloak.detect.validators import ascii_digits, phone_core
from cloak.link.translit import name_key, name_tokens_for_key, place_key as _place_key, skeleton

_MONTHS = {m: i + 1 for i, m in enumerate(
    "jan feb mar apr may jun jul aug sep oct nov dec".split())}
_FEMALE = re.compile(r"^(f|female|woman|girl|महिला|स्त्री|औरत|लड़की)\b", re.I)
_MALE = re.compile(r"^(m|male|man|boy|पुरुष|आदमी|लड़का)\b", re.I)
_PLACE_NOISE = re.compile(r"(?i)\b(?:vill?\.?|village|gram|gaon|ग्राम|गाँव|गांव|tehsil|tahsil|distt?\.?|district|जिला|तहसील|mohalla|city)\b\.?")


def norm_alnum(v: str) -> str:
    return re.sub(r"[^a-z0-9]", "", ascii_digits(v).casefold())


def parse_dob(value: str) -> frozenset:
    """All (year, month, day) readings of a date string; empty if none."""
    v = ascii_digits(value)
    out = set()
    m = re.search(r"(?<!\d)(\d{4})[/\-. ](\d{1,2})[/\-. ](\d{1,2})(?!\d)", v)
    if m:
        out.add((int(m.group(1)), int(m.group(2)), int(m.group(3))))
    else:
        m = re.search(r"(?<!\d)(\d{1,2})[/\-. ](\d{1,2})[/\-. ](\d{4})(?!\d)", v)
        if m:
            a, b, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
            if a > 12:
                out.add((y, b, a))
            elif b > 12:
                out.add((y, a, b))
            else:
                out.update({(y, b, a), (y, a, b)})
        else:
            m = re.search(r"(?i)(\d{1,2})[ \-]([a-z]{3})[a-z]*[ \-,]+(\d{4})", v)
            if m and m.group(2).lower() in _MONTHS:
                out.add((int(m.group(3)), _MONTHS[m.group(2).lower()], int(m.group(1))))
    return frozenset(t for t in out if 1 <= t[1] <= 12 and 1 <= t[2] <= 31 and 1850 <= t[0] <= 2100)


def parse_age(value: str):
    m = re.search(r"(?<![\d.])(\d{1,3})(?![\d.])", ascii_digits(value))
    if not m:
        return None
    age = int(m.group(1))
    return age if 0 <= age <= 120 else None


def parse_gender(value: str):
    v = value.strip()
    if _FEMALE.match(v):
        return "F"
    if _MALE.match(v):
        return "M"
    m = re.search(r"/\s*([MFmf])\b", v)
    return m.group(1).upper() if m else None


def event_year(value: str):
    m = re.search(r"(?<!\d)(20[0-4]\d)(?!\d)", ascii_digits(value))
    return int(m.group(1)) if m else None


def place_key(value: str) -> str:
    return _place_key(_PLACE_NOISE.sub(" ", value))


@dataclass
class Evidence:
    names: list = field(default_factory=list)         # strong (structured / labelled) patient names
    wnames: list = field(default_factory=list)        # weak (prose cue) names of the subject
    rels: list = field(default_factory=list)          # strong relative names
    wrels: list = field(default_factory=list)         # weak relatives from prose cues
    ids: dict = field(default_factory=dict)           # kind -> set of normalised values
    phones: set = field(default_factory=set)
    dobs: set = field(default_factory=set)            # set of frozensets of (y, m, d) readings (one per raw date)
    dob_raw: set = field(default_factory=set)
    ages: list = field(default_factory=list)
    gender: str = None
    event_years: list = field(default_factory=list)
    villages: set = field(default_factory=set)
    districts: set = field(default_factory=set)
    tehsils: set = field(default_factory=set)
    # derived
    tokens: frozenset = frozenset()
    rel_tokens: frozenset = frozenset()
    wtokens: frozenset = frozenset()
    wrel_tokens: frozenset = frozenset()
    birth: tuple = None                                # (lo, hi) birth-year interval or None

    def add_id(self, kind, value):
        n = norm_alnum(value)
        if len(n) >= 4:
            self.ids.setdefault(kind, set()).add(n)
        digits = re.sub(r"\D", "", ascii_digits(value))
        if kind == "mrn" and len(digits) >= 6:
            self.ids.setdefault("mrn", set()).add("d" + digits)

    @property
    def strong_name(self) -> bool:
        return bool(self.tokens)

    @property
    def has_identity(self) -> bool:
        return bool(self.tokens or self.ids or self.phones)


def _toks(values):
    out = set()
    for v in values:
        for t in name_tokens_for_key(v):
            s = skeleton(t)
            if s:
                out.add(s)
    return frozenset(out)


def build(events, default_year: int = 2026) -> Evidence:
    """events: iterable of (kind, value)."""
    ev = Evidence()
    for kind, value in events:
        value = str(value)
        if kind == "patient_name":
            ev.names.append(value)
        elif kind == "name:subject":
            ev.wnames.append(value)
        elif kind == "relative_name":
            ev.rels.append(value)
        elif kind == "name:rel":
            ev.wrels.append(value)
        elif kind in ("mrn", "hard:ID", "id:known"):
            ev.add_id("mrn", value)
        elif kind in ("aadhaar", "hard:AADHAAR"):
            d = re.sub(r"\D", "", ascii_digits(value))
            if len(d) == 12:
                ev.add_id("aadhaar", d)
        elif kind in ("abha", "hard:ABHA"):
            d = re.sub(r"\D", "", ascii_digits(value))
            if len(d) == 14:
                ev.add_id("abha", d)
            elif "@" in value:
                ev.add_id("abhaaddr", value)
        elif kind in ("phone", "hard:PHONE"):
            core = phone_core(value)
            if core:
                ev.phones.add(core)
        elif kind in ("pan", "hard:PAN"):
            ev.add_id("pan", value)
        elif kind in ("email", "hard:EMAIL"):
            ev.add_id("email", value.casefold())
        elif kind in ("insurance", "hard:INSURANCE"):
            ev.add_id("insurance", value)
        elif kind == "dob":
            r = parse_dob(value)
            if r:
                ev.dobs.add(r)
                ev.dob_raw.add(ascii_digits(value).strip())
        elif kind == "age":
            a = parse_age(value)
            if a is not None:
                ev.ages.append(a)
            g = parse_gender(value)
            if g:
                ev.gender = ev.gender or g
        elif kind == "age_sex":
            a = parse_age(value)
            if a is not None:
                ev.ages.append(a)
            g = parse_gender(value)
            if g:
                ev.gender = ev.gender or g
        elif kind == "gender":
            g = parse_gender(value)
            if g:
                ev.gender = ev.gender or g
        elif kind == "date_event":
            y = event_year(value)
            if y:
                ev.event_years.append(y)
        elif kind == "village":
            ev.villages.add(place_key(value))
        elif kind == "district":
            ev.districts.add(place_key(value))
        elif kind == "tehsil":
            ev.tehsils.add(place_key(value))
        elif kind == "address":
            for seg in value.split(","):
                s = seg.strip()
                if re.match(r"(?i)(?:vill?\.?|village|gram|gaon|ग्राम|गाँव|गांव)", s):
                    ev.villages.add(place_key(s))
                elif re.match(r"(?i)(?:distt?\.?|district|जिला)", s):
                    ev.districts.add(place_key(s))
                elif re.match(r"(?i)(?:tehsil|tahsil|तहसील)", s):
                    ev.tehsils.add(place_key(s))
    ev.villages.discard("")
    ev.districts.discard("")
    ev.tehsils.discard("")
    ev.tokens = _toks(ev.names)
    ev.rel_tokens = _toks(_strip(ev.rels))
    ev.wtokens = _toks(ev.wnames)
    ev.wrel_tokens = _toks(ev.wrels)
    if ev.dobs:
        years = {t[0] for r in ev.dobs for t in r}
        ev.birth = (min(years), max(years))
    elif ev.ages:
        y = (sorted(ev.event_years)[0] if ev.event_years else default_year)
        ev.birth = (y - max(ev.ages) - 1, y - min(ev.ages))
    return ev


def _strip(values):
    return [re.sub(r"(?i)^\s*(?:s/o|d/o|w/o|c/o|h/o)\s*[:\-]?\s*", "", v) for v in values]


def is_fragment(ev: Evidence) -> bool:
    """Prose-only evidence: weak subject name(s) plus maybe a relative, no strong name or ID."""
    return not ev.tokens and not ev.ids and not ev.phones and bool(ev.wtokens)
