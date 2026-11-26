"""Context cues for names in prose: relation, honorific, cue words, particles, senders, name-near-phone."""
import re

from cloak.detect.names import Gazetteer, is_non_name

_LATIN_TOK = r"(?:[A-Z][A-Za-z'.\-]+|[A-Z]\.)"
_NAMERUN = _LATIN_TOK + r"(?:\s+" + _LATIN_TOK + r"){0,2}"
_DEVA_TOK = r"[\u0900-\u0963\u0971-\u097f]+"
_DEVA_RUN = _DEVA_TOK + r"(?:\s+" + _DEVA_TOK + r"){0,2}"
_LOWER_TOK = r"[a-z][a-z'\-]{2,}"

_REL_MARK = r"(?<![A-Za-z/])(?:S/O|D/O|W/O|S/o|D/o|W/o|s/o|d/o|w/o|Son\s+of|Daughter\s+of|Wife\s+of|Husband\s+of)"
_RELATION = re.compile(_REL_MARK + r"\s*[:\-]?\s*(" + _NAMERUN + ")")
_RELATION_LOWER = re.compile(_REL_MARK + r"\s*[:\-]?\s*(" + _LOWER_TOK + ")")
_CARE_OF = re.compile(r"(?<![A-Za-z/])(?:C/O|C/o)\s*[:\-]?\s*(" + _NAMERUN + ")")
_HONORIFIC_PRE = re.compile(r"\b(?:Shri|Smt|Mr|Mrs|Ms|Km|Late|Master|Pt)\.?\s+(" + _NAMERUN + ")")
_HONORIFIC_POST = re.compile(r"((?:" + _LATIN_TOK + r"\s+){0,2}[A-Z][a-z]{2,})\s+(?i:ji|sahab|sahib|saheb|saab|bhai|bhaiya|didi|amma|behenji|behen|babu|mam|madam|sir)\b")
_CUE_WORDS = (r"called\s+by|raised\s+by|witnessed\s+by|informed\s+by|reported\s+by|visitor|attendant|guardian|caller|"
              r"contact\s+person|brought\s+by|next\s+of\s+kin|patient\s+name|pt\s+name|name\s+of\s+patient|report\s+of|"
              r"collected\s+from|sample\s+received\s+from|received\s+from|spoke\s+to|spoke\s+with|meeting\s+with|handed\s+over\s+to")
_CUE = re.compile(r"(?i:\b(?:" + _CUE_WORDS + r"))\s*[:,\-(]*\s*(?i:(?:(?:is|was|by|named|name|mr|mrs|ms|shri|smt)\b\.?\s*){0,2})(" + _NAMERUN + ")")
_BEFORE_REL = re.compile(r"(" + _NAMERUN + r")\s*,?\s*(?:S/o|D/o|W/o|S/O|D/O|W/O)\b")
_BEFORE_DASH_HIST = re.compile(r"(" + _NAMERUN + r")\s+-\s+(?:K/C/O|H/O|C/O)\b")
_AFTER_TIME_DASH = re.compile(r"\b\d{1,2}:\d{2}\s+-\s+(" + _NAMERUN + r")(?=\s+-|\s*$)", re.M)
_BEFORE_PAREN = re.compile(r"(" + _NAMERUN + r")\s*\((?i:attendant|visitor|relative|guardian|patient|caller)")
_PATIENT_CUE = re.compile(r"(?<![A-Za-z])(?:Patient|Pt\.?)\s+(" + _NAMERUN + ")")
_POSS_REL = re.compile(r"\b([A-Z][a-z]{2,})'s\s+(?i:mother|father|wife|husband|son|daughter|attendant|relative|brother|sister|family|bhai|beti|beta)\b")
_PARTICLE_STRONG = re.compile(r"(?<![\w/])(" + _LATIN_TOK + r")\s+(?:ko|ne)\b")
_PARTICLE = re.compile(r"\b(" + _LATIN_TOK + r")\s+(?:ka|ki|ke|ne|ko|se)\b")
_POSSESSIVE_KA = re.compile(r"\b([A-Z][a-z]{2,})\s+(?:ka|ki|ke|ne|ko)\s+(?:BP|bp|pulse|temp|sugar|RBS|bukhar|dard|tabiyat|condition|report)\b")
_WHATSAPP = re.compile(r"(?m)^\s*\[[^\]\n]{4,32}\]\s*([^:\n\[\]]{2,40}?)\s*:")
_WHATSAPP2 = re.compile(r"(?m)^\s*\d{1,2}/\d{1,2}/\d{2,4},?\s+\d{1,2}:\d{2}(?:\s*[ap]m)?\s+-\s+([^:\n]{2,40}?):")
_DEVA_HON_PRE_SUBJ = re.compile(r"(?:श्रीमती|श्री|सुश्री|कुमारी|स्व\.?)\s+(" + _DEVA_RUN + ")")
_DEVA_HON_PRE_REL = re.compile(r"(?:पुत्र|पुत्री|पत्नी|पति|पिता|माता|भाई|बहन)\s+(" + _DEVA_RUN + ")")
_DEVA_HON_POST = re.compile(r"(" + _DEVA_TOK + r")\s+(?:जी|साहब|साहिब|भाई|भैया|दीदी|अम्मा|बहन|बाबू)(?![\u0900-\u097f])")
_DEVA_PARTICLE = re.compile(r"(" + _DEVA_TOK + r")\s+(?:को|का|की|ने|के)(?![\u0900-\u097f])")
_DEVA_LABEL_VALUE = re.compile(r"(?:नाम|का नाम)\s*[:\-]\s*(" + _DEVA_RUN + ")")
_NEAR_PHONE_LEFT = re.compile(r"(" + _NAMERUN + r")[\s,:\-(]*(?i:(?:(?:mob(?:ile)?|ph(?:one)?|contact|tel|no)\.?[\s:#\-]*)*)$")

def _trim(start: int, end: int, text: str):
    """Trim non-name words from both ends of a candidate span; None if nothing is left."""
    toks = list(re.finditer(r"\S+", text[start:end]))
    while toks and is_non_name(toks[0].group(0)):
        toks.pop(0)
    while toks and is_non_name(toks[-1].group(0)):
        toks.pop()
    if not toks:
        return None
    return start + toks[0].start(), start + toks[-1].end()


def cue_name_spans_typed(text: str, phone_spans=(), dictionary=None) -> list:
    """(start, end, kind) name spans from context cues, on the shadow text.
    kind: 'rel' (relative/attendant/visitor), 'subject' (the patient or a person being discussed), 'weak'."""
    out = []

    def add(m, kind, g=1):
        sp = _trim(m.start(g), m.end(g), text)
        if sp:
            out.append((sp[0], sp[1], kind))

    for rx in (_RELATION, _RELATION_LOWER, _BEFORE_PAREN, _DEVA_HON_PRE_REL):
        for m in rx.finditer(text):
            add(m, "rel")
    for rx in (_BEFORE_REL, _BEFORE_DASH_HIST, _AFTER_TIME_DASH, _PATIENT_CUE, _HONORIFIC_PRE, _POSSESSIVE_KA,
               _DEVA_HON_PRE_SUBJ, _DEVA_LABEL_VALUE):
        for m in rx.finditer(text):
            add(m, "subject")
    for m in _CUE.finditer(text):
        label = text[m.start():m.start(1)].casefold()
        add(m, "subject" if ("patient" in label or "pt name" in label or "report of" in label) else "rel")
    for rx in (_POSS_REL, _PARTICLE_STRONG, _DEVA_HON_POST):
        for m in rx.finditer(text):
            add(m, "weak")
    for m in _CARE_OF.finditer(text):
        first = m.group(1).split()[0]
        if not is_non_name(first):  # "C/O fever" is a complaint, "C/O Ramesh Kumar" a relative
            add(m, "rel")
    for m in _HONORIFIC_POST.finditer(text):
        sp = _trim(m.start(1), m.end(1), text)
        if sp:
            # keep only trailing tokens: a leading capitalised word may just start the sentence
            seg = text[sp[0]:sp[1]]
            toks = list(re.finditer(r"\S+", seg))
            keep = [t for t in toks if Gazetteer.known(t.group(0)) or (dictionary is not None and dictionary.matches_word(t.group(0)))]
            last = toks[-1]
            lo = min([t.start() for t in keep] + [last.start()])
            out.append((sp[0] + lo, sp[1], "subject"))
    for m in list(_PARTICLE.finditer(text)):
        w = m.group(1)
        if Gazetteer.known(w) or (dictionary is not None and dictionary.matches_word(w)):
            out.append((m.start(1), m.end(1), "weak"))
    for m in _DEVA_PARTICLE.finditer(text):
        w = m.group(1)
        if Gazetteer.known(w) or (dictionary is not None and dictionary.matches_word(w)):
            out.append((m.start(1), m.end(1), "weak"))
    for rx in (_WHATSAPP, _WHATSAPP2):
        for m in rx.finditer(text):
            seg = m.group(1)
            if not re.search(r"\d{4,}", seg) and not is_non_name(seg.split()[0]):
                out.append((m.start(1), m.end(1), "weak"))
    for s, _e in phone_spans:
        base = max(0, s - 60)
        m = _NEAR_PHONE_LEFT.search(text[base:s])
        if m and m.group(1):
            sp = _trim(base + m.start(1), base + m.end(1), text)
            if sp:
                out.append((sp[0], sp[1], "weak"))
    return sorted(set(out))


def cue_name_spans(text: str, phone_spans=(), dictionary=None) -> list:
    """(start, end) spans only (kind dropped)."""
    return sorted({(s, e) for s, e, _k in cue_name_spans_typed(text, phone_spans, dictionary)})
