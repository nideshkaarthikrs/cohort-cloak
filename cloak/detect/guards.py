"""Protected spans: clinical content that name/ID heuristics must not redact."""
import re

_DR = re.compile(
    r"(?<![A-Za-z])(?:Dr|DR|Doctor|Prof)\.?\s+((?:[A-Z][\w.'\-]*|[A-Z]\.)(?:\s+(?:[A-Z][\w.'\-]*|[A-Z]\.)){0,2})")
_DR_DEVA = re.compile(r"डॉ\.?\s*((?:[ऀ-ॿ]+)(?:\s+[ऀ-ॿ]+){0,2})")
_DOSE = re.compile(
    r"(?<![\w.])\d+(?:\.\d+)?\s?(?:mg|mcg|µg|ug|g|gm|ml|l|iu|units?|u|meq|mmol|cc|%)\b(?:/\w+)?", re.I)
_FREQ = re.compile(r"(?<![\w/.\-])\d(?:\.\d)?-\d(?:\.\d)?-\d(?:\.\d)?(?:-\d)?(?![\w/.\-])|\b(?:OD|BD|BID|TDS|TID|QID|QD|HS|SOS|PRN|stat)\b")
_DURATION = re.compile(r"\b(?:x|for|×)\s?\d+\s?(?:days?|d|wks?|weeks?|months?|mo|yrs?|years?|hrs?|hours?)\b|\b\d+\s?(?:days?|wks?|weeks?|months?)\b", re.I)
_VITAL = re.compile(r"(?<![\w/])\d{2,3}/\d{2,3}(?![\w/])|(?<![\w.])\d{2,3}(?:\.\d)?\s?°?\s?[CF]\b")
_RANGE = re.compile(r"(?<![\w.])\d+(?:\.\d+)?\s?-\s?\d+(?:\.\d+)?(?![\w.])")
_ICD = re.compile(r"\b[A-TV-Z]\d{2}(?:\.\d{1,4})?\b")
_LOINC = re.compile(r"(?<![\w\-])\d{3,5}-\d(?![\w\-])")
_HOSP = re.compile(
    r"\b(?:[A-Z][\w'.\-]*\s+){1,5}(?:Hospital|Hospitals|Diagnostics|Pathology|Sadan|Clinic|Nursing\s+Home|Medical\s+(?:College|Institute|Centre|Center)|Referral\s+(?:Centre|Center)|Labs?|Laboratory|Healthcare)\b")
_WARD = re.compile(r"\bWard\s*\d+\s*\([A-Za-z &]+\)(?:\s*/\s*Bed\s*\d+)?|\bBed\s*\d+\b|\bWard/Bed\b")
_HIST_TAIL = r"(?:\s+(?:[a-z][\w'\-]*|\d+\s?(?:yrs?|years?|days?|months?)[\w ]*|[A-Z]{2,4}|[A-Za-z]+'s|and|&|,))*"
_HIST = re.compile(r"(?:K/C/O|H/O)\s+((?:[a-z][\w'\-]*|[A-Z]{2,4}|[A-Z][a-z]+'s)" + _HIST_TAIL + ")")
_COMPLAINT = re.compile(r"(?<![A-Za-z/])C/O\s+([a-z][\w'\-]*" + _HIST_TAIL + ")")
_ASHA = re.compile(r"\bASHA\s+(?:worker|didi|sevika)\b|\bASHA\b(?=\s+(?:[a-z]|$))")
_DRUG_FORM = re.compile(
    r"(?<![A-Za-z])(?:Tab|Tabs|Tablet|Cap|Caps|Capsule|Inj|Injection|Syp|Syrup|Susp|Oint|Ointment|Drops?|Gel|Cream|Inh|Neb|Rx)\.?\s+"
    r"([A-Z][\w'\-]*(?:\s+[A-Z][\w'\-]*){0,2})")
_DRUG_DOSE = re.compile(
    r"(?<![A-Za-z])([A-Z][a-z][\w'\-]*(?:\s+[A-Z][a-z][\w'\-]*){0,2})(?=\s+(?:\d+(?:\.\d+)?\s?(?:mg|mcg|µg|g|gm|ml|iu|units?)\b|\d(?:\.\d)?-\d(?:\.\d)?-\d(?:\.\d)?))", )
_CLINICAL_KW = re.compile(r"\b(?:fever|cough|headache|giddiness|weakness|vomiting|pain|diabetes|hypertension|tb|asthma)\b", re.I)


def guard_spans(text: str) -> list:
    """Return (start, end, kind) protected spans, unsorted and possibly overlapping."""
    spans = []
    for m in _DR.finditer(text):
        spans.append((m.start(1), m.end(1), "doctor"))
    for m in _DR_DEVA.finditer(text):
        spans.append((m.start(1), m.end(1), "doctor"))
    for rx, kind in ((_DOSE, "dose"), (_FREQ, "frequency"), (_DURATION, "duration"), (_VITAL, "vital"),
                     (_RANGE, "range"), (_ICD, "icd"), (_LOINC, "loinc"), (_HOSP, "hospital"),
                     (_WARD, "ward"), (_ASHA, "asha")):
        for m in rx.finditer(text):
            spans.append((m.start(), m.end(), kind))
    for rx in (_HIST, _COMPLAINT):
        for m in rx.finditer(text):
            spans.append((m.start(1), m.end(1), "history"))
    for rx in (_DRUG_FORM, _DRUG_DOSE):
        for m in rx.finditer(text):
            spans.append((m.start(1), m.end(1), "drug"))
    return spans


def guarded(spans, start: int, end: int) -> bool:
    """True if [start, end) lies fully inside one protected span."""
    return any(a <= start and end <= b for a, b, _ in spans)


def overlaps_guard(spans, start: int, end: int) -> bool:
    return any(start < b and a < end for a, b, _ in spans)
