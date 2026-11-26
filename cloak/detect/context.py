"""Context cues for names in prose: relation, honorific, cue words, particles, senders, name-near-phone."""
import re
import unicodedata

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
              r"collected\s+from|sample\s+received\s+from|received\s+from|spoke\s+to|spoke\s+with|meeting\s+with|handed\s+over\s+to|"
              r"relative|brother|sister|son|daughter|wife|husband|mother|father|friend|neighbou?r|nephew|niece|uncle|aunt|"
              r"cousin|spouse|accompanied\s+by|escorted\s+by|signed\s+by|consent\s+(?:given\s+)?by|"
              r"bete|beta|beti|patni|pati|pita|mata|biwi|dost|padosi|"
              r"appt\s+for|appointment\s+for|booked\s+for|reports?\s+for|bill\s+for|prescription\s+for|certificate\s+for|"
              r"referral\s+for|admission\s+of|discharge\s+of|follow[- ]?up\s+(?:of|for)|ward\s+round\s+for")
_CUE = re.compile(r"(?i:\b(?:" + _CUE_WORDS + r"))(?=[\s:,\-(])\s*[:,\-(]*\s*(?i:(?:(?:is|was|by|named|name|mr|mrs|ms|shri|smt)\b\.?\s*){0,2})(" + _NAMERUN + ")")
_BEFORE_REL = re.compile(r"(" + _NAMERUN + r")\s*,?\s*(?:S/o|D/o|W/o|S/O|D/O|W/O)\b")
_BEFORE_DASH_HIST = re.compile(r"(" + _NAMERUN + r")\s+-\s+(?:K/C/O|H/O|C/O)\b")
_AFTER_TIME_DASH = re.compile(r"\b\d{1,2}:\d{2}\s+-\s+(" + _NAMERUN + r")(?=\s+-|\s*$)", re.M)
_BEFORE_PAREN = re.compile(r"(" + _NAMERUN + r")\s*\((?i:attendant|visitor|relative|guardian|patient|caller)")
_PATIENT_CUE = re.compile(r"(?<![A-Za-z])(?:Patient|Pt\.?)\s+(" + _NAMERUN + ")")
_POSS_REL = re.compile(r"\b([A-Z][a-z]{2,})'s\s+(?i:mother|father|wife|husband|son|daughter|attendant|relative|brother|sister|family|bhai|beti|beta)\b")
_PARTICLE_STRONG = re.compile(r"(?<![\w/])((?:" + _LATIN_TOK + r"\s+){0,2}" + _LATIN_TOK + r")\s+(?:ko|ne)\b")
_PARTICLE = re.compile(r"\b(" + _LATIN_TOK + r")\s+(?:ka|ki|ke|ne|ko|se)\b")
_POSSESSIVE_KA = re.compile(r"\b([A-Z][a-z]{2,})\s+(?:ka|ki|ke|ne|ko)\s+(?:BP|bp|pulse|temp|sugar|RBS|bukhar|dard|tabiyat|condition|report)\b")
_WHATSAPP = re.compile(r"(?m)^\s*\[[^\]\n]{4,32}\]\s*([^:\n\[\]]{2,40}?)\s*:")
_WHATSAPP2 = re.compile(r"(?m)^\s*\d{1,2}/\d{1,2}/\d{2,4},?\s+\d{1,2}:\d{2}(?:\s*[ap]m)?\s+-\s+([^:\n]{2,40}?):")
_DEVA_HON_PRE_SUBJ = re.compile(r"(?:श्रीमती|श्री|सुश्री|कुमारी|स्व\.?)\s+(" + _DEVA_RUN + ")")
# a plain noun for "patient" is not a title: a name after it must be one we know, or `मरीज से बात हुई` loses ordinary words
_DEVA_PATIENT_NOUN = re.compile(r"(?:रोगी|मरीज़|मरीज)\s+(" + _DEVA_RUN + ")")
_DEVA_HON_PRE_REL = re.compile(r"(?:पुत्र|पुत्री|पत्नी|पति|पिता|माता|भाई|बहन)\s+(" + _DEVA_RUN + ")")
_DEVA_HON_POST = re.compile(r"(" + _DEVA_TOK + r")\s+(?:जी|साहब|साहिब|भाई|भैया|दीदी|अम्मा|बहन|बाबू)(?![\u0900-\u097f])")
_DEVA_PARTICLE = re.compile(r"(" + _DEVA_TOK + r")\s+(?:को|का|की|ने|के)(?![\u0900-\u097f])")
_DEVA_LABEL_VALUE = re.compile(r"(?:नाम|का नाम)\s*[:\-]\s*(" + _DEVA_RUN + ")")
_NEAR_PHONE_LEFT = re.compile(r"(" + _NAMERUN + r")[\s,:\-(]*(?i:(?:(?:mob(?:ile)?|ph(?:one)?|contact|tel|no)\.?[\s:#\-]*)*)$")

_DEAR = re.compile(r"\bDear\s+(?:(?:Mr|Mrs|Ms|Shri|Smt)\.?\s+)?(" + _NAMERUN + r"(?:\s*,\s*" + _NAMERUN + r")?)(?=\s*[,:!.\n]|\s*$)")

# a patient banner: `Name | ID | 71 yrs`, `Name   UHID X   DOB ...` (any script): a name field, then an ID, a DOB label or an age
_BANNER_SPLIT = re.compile(r"\s*\|\s*|\t|[ ]{3,}")
_BANNER_ID = re.compile(r"(?<![\w/\-])(?=[A-Za-z0-9/\-]*[A-Za-z])(?=[A-Za-z0-9/\-]*\d{3})[A-Za-z0-9][A-Za-z0-9/\-]{4,24}(?![\w/\-])")
_BANNER_DATE = re.compile(r"\d{1,2}-[A-Za-z]{3,9}-\d{2,4}")
_BANNER_DOB = re.compile(r"(?i)\b(?:dob|d\.o\.b|date\s+of\s+birth|born)\b")
_BANNER_AGE = re.compile(r"(?i)\b\d{1,3}\s*(?:yrs?|years?|y/o|वर्ष|वर्षे|साल|வயது|ವರ್ಷ|వయస్సు|বছর|વર્ષ|വയസ്സ്)|\b\d{1,3}\s*/\s*[MF]\b")


def _name_like(seg: str) -> bool:
    words = seg.split()
    if not (1 <= len(words) <= 4) or not (2 <= len(seg) <= 40):
        return False
    return all(unicodedata.category(c)[0] in "LM" or c in ".'-," for c in seg.replace(" ", ""))


def _banner_names(text: str):
    """Spans of the first field of lines that look like a patient banner."""
    out = []
    for lm in re.finditer(r"[^\n]+", text):
        line = lm.group(0)
        if len(line) > 200:
            continue
        lead = len(line) - len(line.lstrip())
        parts = _BANNER_SPLIT.split(line.strip(), maxsplit=1)
        if len(parts) != 2 or not _name_like(parts[0]):
            continue
        rest = _BANNER_DATE.sub(" ", parts[1])
        feats = bool(_BANNER_ID.search(rest)) + bool(_BANNER_DOB.search(rest)) + bool(_BANNER_AGE.search(rest))
        if feats >= 2:
            a = lm.start() + lead
            out.append((a, a + len(parts[0])))
    return out


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


_CHUNK = 800


def _chunks(text: str):
    """Cut very long lines at whitespace (or hard at 2x) so no cue regex scans a huge unbroken run quadratically."""
    pos, n = 0, len(text)
    while pos < n:
        end = min(n, pos + _CHUNK)
        if end < n:
            ws = text.rfind(" ", pos + _CHUNK // 2, end)
            end = ws + 1 if ws > 0 else end
        yield pos, end
        pos = end


def cue_name_spans_typed(text: str, phone_spans=(), dictionary=None) -> list:
    """(start, end, kind) name spans from context cues, on the shadow text.
    kind: 'rel' (relative/attendant/visitor), 'subject' (the patient or a person being discussed), 'weak'."""
    if len(text) > 2 * _CHUNK:
        res = []
        for a, b in _chunks(text):
            ph = [(s - a, e - a) for s, e in phone_spans if a <= s < b]
            res += [(s + a, e + a, k) for s, e, k in cue_name_spans_typed(text[a:b], ph, dictionary)]
        return sorted(set(res))
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
    for rx in (_DEAR,):
        for m in rx.finditer(text):
            add(m, "subject")
    for a, b in _banner_names(text):
        sp = _trim(a, b, text)
        if sp:
            out.append((sp[0], sp[1], "subject"))
    for m in _DEVA_PATIENT_NOUN.finditer(text):
        toks = [t.group(0) for t in re.finditer(_DEVA_TOK, m.group(1))]
        followed = re.match(r"\s+(?:को|ने|का|की|के)(?![\u0900-\u097f])", text[m.end(1):])
        if followed or any(Gazetteer.known(w) or (dictionary is not None and dictionary.matches_word(w)) for w in toks):
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
            out.append((sp[0], sp[1], "subject"))  # leading non-name words (Dear, Today...) were trimmed already
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
                out.append((m.start(1), m.end(1), "chat"))  # a chat sender: a name worth remembering, but not linking evidence
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
