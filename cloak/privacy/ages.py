"""Age forms: where ages occur, and cluster-consistent generalised bands."""
import re

_DUR_BEFORE = re.compile(r"(?:\bx|×|\bfor|\bsince|\bover|\bfrom|\blast|\bpast|\babout|\bnearly|\bwithin|\bafter|\bin)\s*$", re.I)
_AGE_SEX = re.compile(r"(?<![\d./\-])(\d{1,3})(?=\s*/\s*[MFmf](?![A-Za-z]))")
_AGE_UNIT = re.compile(
    r"(?<![\d./\-])(\d{1,3})(?=\s*(?:Y|Yrs?|Years?|yo|वर्षीय|वर्ष|साल)(?![A-Za-zऀ-ॿ])"
    r"(?!\s*(?:back|ago|पहले|से)(?![A-Za-z\u0900-\u097f])))", re.I)
_AGE_OLD = re.compile(r"(?<![\d./\-])(\d{1,3})(?=[\s\-]*(?:year|yr)s?[\s\-]*old)", re.I)


def find_ages(text: str) -> list:
    """(start, end) spans of the number in an age form; history durations and ranges are skipped."""
    out = set()
    for rx in (_AGE_SEX, _AGE_UNIT, _AGE_OLD):
        for m in rx.finditer(text):
            if not (0 <= int(m.group(1)) <= 120):
                continue
            if rx is not _AGE_SEX and _DUR_BEFORE.search(text[max(0, m.start(1) - 12):m.start(1)]):
                continue
            out.add((m.start(1), m.end(1)))
    return sorted(out)


def first_number_span(value: str):
    """Span of the first plausible age number in a value from an age field (`47`, `47 वर्ष`, `35/F`)."""
    m = re.search(r"(?<![\d.])(\d{1,3})(?![\d.])", value)
    if m and 0 <= int(m.group(1)) <= 120:
        return m.start(1), m.end(1)
    return None


def band_for(ages, width: int = 5, top: int = 85) -> str:
    """One band, `width` wide where possible, containing every age in `ages` (top-coded at `top`)."""
    lo_age, hi_age = min(ages), max(ages)
    if hi_age >= top:
        return f"{(min(lo_age, top) // width) * width}+" if lo_age < top else f"{top}+"
    lo = (lo_age // width) * width
    if hi_age <= lo + width - 1:
        return f"{lo}-{lo + width - 1}"
    lo = lo_age
    return f"{lo}-{max(lo + width - 1, hi_age)}"
