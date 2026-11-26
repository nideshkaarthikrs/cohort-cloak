"""Context cues for names in prose: relation, honorific, cue words, name-near-phone."""
import re

_CAP = r"[A-Z][a-z]+(?:'s)?|[A-Z]{2,}"
_NAMERUN = r"(?:[A-Z][A-Za-z'.\-]+|[A-Z]\.)(?:\s+(?:[A-Z][A-Za-z'.\-]+|[A-Z]\.)){0,2}"
_RELATION = re.compile(r"(?<![A-Za-z/])(?:S/O|D/O|W/O|C/O|S/o|D/o|W/o|C/o|s/o|d/o|w/o|c/o|Son\s+of|Daughter\s+of|Wife\s+of|Husband\s+of)\s*[:\-]?\s*(" + _NAMERUN + ")")
_HONORIFIC_POST = re.compile(r"\b((?:[A-Z][a-z]{2,}))\s+(?:ji|sahab|sahib|saheb|bhai|bhaiya|didi|amma|behenji|behen|babu|mam|madam|sir)\b")
_HONORIFIC_PRE = re.compile(r"\b(?:Shri|Smt|Mr|Mrs|Ms|Km|Late|Master)\.?\s+(" + _NAMERUN + ")")
_CUE = re.compile(r"(?i:\bcalled\s+by|\braised\s+by|\bwitnessed\s+by|\binformed\s+by|\breported\s+by|\bvisitor|\battendant|\bguardian|\bcaller|\bcontact\s+person|\bbrought\s+by|\bnext\s+of\s+kin)\s*[:,\-(]*\s*(" + _NAMERUN + ")")
_BEFORE_PAREN = re.compile(r"(" + _NAMERUN + r")\s*\((?i:attendant|visitor|relative|guardian|patient|caller)")
_POSSESSIVE_KA = re.compile(r"\b([A-Z][a-z]{2,})\s+(?:ka|ki|ke|ne|ko)\s+(?:BP|bp|pulse|temp|sugar|RBS|bukhar|dard|tabiyat|condition|report)\b")
_STOP_CAPS = {"Mobile", "Mob", "Phone", "Ph", "Attendant", "Visitor", "Bed", "Ward", "Patient", "Tab", "Cap", "Inj", "Syp",
              "Rx", "Next", "Review", "Advice", "Diagnosis", "History", "Address", "Name", "Age", "Sex", "Date", "Time",
              "Consultant", "Doctor", "Hospital", "Medicine", "Surgery", "Dr", "Contact", "Called", "Informed", "Raised",
              "Reported", "Guardian", "The", "Fever", "Cough"}
_NEAR_PHONE_LEFT = re.compile(r"(" + _NAMERUN + r")[\s,:\-(]*(?:(?:mob(?:ile)?|ph(?:one)?|contact|tel|no)\.?[\s:#\-]*)*$", re.I)


def _clean(m_start, m_end, text):
    """Trim stop-words from the ends of a candidate name span; None if nothing is left."""
    seg = text[m_start:m_end]
    toks = list(re.finditer(r"\S+", seg))
    while toks and toks[0].group(0).strip(".,") in _STOP_CAPS:
        toks.pop(0)
    while toks and toks[-1].group(0).strip(".,") in _STOP_CAPS:
        toks.pop()
    if not toks:
        return None
    return m_start + toks[0].start(), m_start + toks[-1].end()


def cue_name_spans(text: str, phone_spans=()) -> list:
    """(start, end) spans of names inferred from context cues."""
    out = []
    for rx in (_RELATION, _HONORIFIC_PRE, _CUE, _BEFORE_PAREN, _HONORIFIC_POST, _POSSESSIVE_KA):
        for m in rx.finditer(text):
            sp = _clean(m.start(1), m.end(1), text)
            if sp:
                out.append(sp)
    for s, _e in phone_spans:
        left = text[max(0, s - 60):s]
        m = _NEAR_PHONE_LEFT.search(left)
        if m and m.group(1):
            base = max(0, s - 60)
            sp = _clean(base + m.start(1), base + m.end(1), text)
            if sp:
                out.append(sp)
    return sorted(set(out))
