"""Text scrubber: hard identifiers, known IDs/shapes, known names, label-anchored fields, context cues."""
import re
from collections import Counter

from cloak.detect.address import rewrite_address
from cloak.detect.columns import header_role
from cloak.detect.context import cue_name_spans_typed
from cloak.detect.guards import guard_spans, guarded, overlaps_guard
from cloak.detect.ids import IdSet
from cloak.detect.lexicon import medical_words, words as words_of
from cloak.detect.names import Gazetteer, NameDict, is_non_name, iter_words, merge_spans
from cloak.detect.normalize import map_span, normalize
from cloak.detect.payloads import ENCODINGS, decode_b64_text, encode_b64_text
from cloak.detect.patterns import find_hard
from cloak.detect.validators import ascii_digits
from cloak.privacy.ages import find_ages, first_number_span
from cloak.privacy.dates import OrderVotes, find_dates
from cloak.privacy.suppress import ICD_RX
from cloak.rewrite.filenames import _clean_component

PLACEHOLDER = {"PHONE": "[PHONE]", "AADHAAR": "[AADHAAR]", "ABHA": "[ABHA]", "PAN": "[PAN]", "EMAIL": "[EMAIL]",
               "INSURANCE": "[ID]", "ID": "[ID]", "NAME": "[NAME]", "RELATIVE": "[RELATIVE]"}
ROLE_PLACEHOLDER = {"patient_name": "[NAME]", "person_name": "[NAME]", "relative_name": "[RELATIVE]", "phone": "[PHONE]",
                    "email": "[EMAIL]", "aadhaar": "[AADHAAR]", "abha": "[ABHA]", "pan": "[PAN]", "mrn": "[ID]",
                    "insurance": "[ID]", "house": "[HOUSE]", "locality": "[LOCALITY]", "landmark": "[LOCALITY]",
                    "village": "[VILLAGE]"}
ROLE_KIND = {"phone": "PHONE", "email": "EMAIL", "aadhaar": "AADHAAR", "abha": "ABHA", "pan": "PAN", "mrn": "ID",
             "insurance": "ID"}

_LABEL = re.compile(r"(?:^|(?<=\s{2})|(?<=[|;]\s)|(?<=\|))\s{0,40}([A-Za-z\u0900-\u097f][A-Za-z\u0900-\u097f ./()'&\-#]{0,38}?)\s*[:=]\s*(?=\S)", re.M)
_DOB_RX = re.compile(r"(?<!\d)(\d{1,4})[/\-. ](\d{1,2})[/\-. ](\d{1,4})(?!\d)")


def dob_year(value: str) -> str:
    v = ascii_digits(value)
    m = _DOB_RX.search(v)
    if m:
        for g in m.groups():
            if len(g) == 4:
                return g
    m = re.search(r"(?<!\d)(1[89]\d\d|20[0-4]\d)(?!\d)", v)
    return m.group(1) if m else "[DOB]"


_DEVA_ANY = re.compile(r"[ऀ-ൿء-ٟٱ-ۓ]")
_DEVA_AFTER = re.compile(r"[ \t]+([ऀ-ॣॱ-ൿء-ٟٱ-ۓ]{3,})(?![ऀ-ൿء-ٟٱ-ۓ])")
_DEVA_BEFORE = re.compile(r"([ऀ-ॣॱ-ൿء-ٟٱ-ۓ]{3,})[ \t]+\Z")
_GENERIC_ID = re.compile(r"(?<![A-Za-z0-9])([A-Z]{2,5})[/~@.\-_:#{}\\]{1,2}\d{2,6}(?:[/~@.\-_:#{}\\]{1,2}[A-Za-z0-9]{1,6}){1,3}(?![A-Za-z0-9])")
_B64_TOKEN = re.compile(r"(?<![A-Za-z0-9+/])[A-Za-z0-9+/]{8,}={0,2}(?![A-Za-z0-9+/=])")
_TOKEN_ROLES = frozenset({"phone", "aadhaar", "abha", "pan", "insurance", "mrn", "email", "pin", "dob"})


class Scrubber:
    def __init__(self, policy: dict):
        self.policy = policy
        self.names = NameDict()
        self.ids = IdSet()
        self.districts = set()  # casefolded district names seen in structured fields (kept, never learned as villages)
        self.places = {}        # learned village names: casefolded first word -> set of full casefolded phrases
        self.identifiers = 0
        self.stats = Counter()
        # Phase 4: event sink (per-record evidence) and PSN placement table, active only in the final render
        self.sink = None        # list of (fid, rec, kind, value) or None
        self.in_payload = 0     # >0 while scrubbing the decoded text of an encoded value
        self.table = None       # list of (fid, rec, kind, fallback) or None
        self.fid = 0
        self.rec = "doc"
        # Phase 5: date-order inference, reference year, per-source context
        self.date_votes = OrderVotes()
        self.year_counts = Counter()
        self.ref_year = 2026
        self.file_tokens = {}   # fid -> tokens of the file name (hospital signature)
        self.src = ""           # current column/key/label, for d/m vs m/d votes
        self.dx_pending = None  # ICD code of the enclosing coded element (pairs code with display)

    def emit(self, kind: str, value) -> None:
        if self.sink is not None and value is not None and str(value).strip():
            self.sink.append((self.fid, self.rec, kind, str(value)))

    def sentinel(self, kind: str, fallback: str, payload=None) -> str:
        if self.in_payload and kind in ("name", "mrn", "append"):
            return fallback  # a pseudonym is never written inside an encoded payload
        self.table.append((self.fid, self.rec, kind, fallback, payload))
        return f"@@PSN{len(self.table) - 1}@@"

    def order(self) -> str:
        keys = [(self.fid,)] + [("tok", t) for t in self.file_tokens.get(self.fid, ())]
        return self.date_votes.order((self.fid, self.src), keys, "dmy")

    def vote_orders(self, layouts) -> None:
        if self.table is None:  # votes are collected in the learn pass only, then frozen
            keys = [(self.fid, self.src), (self.fid,)] + [("tok", t) for t in self.file_tokens.get(self.fid, ())]
            for lay in layouts:
                for k in keys:
                    self.date_votes.vote(k, lay)

    # ---- registration of known values -------------------------------------------------
    def learn(self, role: str, value) -> None:
        if value is None or isinstance(value, bool):
            return
        v = str(value).strip()
        if not v:
            return
        if role in ("patient_name", "person_name", "relative_name"):
            if not self.policy.get("ablate_names"):  # dev-only switch: measure detection without the dictionary
                self.names.add(self._strip_relation(v))
        elif role in ("mrn", "insurance", "aadhaar", "abha", "pan"):
            self.ids.add(v)
        elif role == "phone":
            self.ids.add(v, shape=False)
        elif role == "district":
            self.districts.add(v.casefold())
        elif role == "village":
            words = [w.casefold() for _s, _e, w in iter_words(v)]
            if words and len(" ".join(words)) >= 4 and not (set(words) & (medical_words() | words_of("hinglish_stopwords.txt"))):
                self.places.setdefault(words[0], set()).add(" ".join(words))

    @staticmethod
    def _strip_relation(v: str) -> str:
        v = re.sub(r"(?i)^\s*(?:s/o|d/o|w/o|c/o|h/o)\s*[:\-]?\s*", "", v)
        return re.split(r"[,;(\n]|\s{2,}|\s+(?:mob|ph|phone|ward|bed)\b", v, maxsplit=1, flags=re.I)[0]

    # ---- value actions by role --------------------------------------------------------
    def scrub_value(self, role, value: str):
        """Apply the action for `role` to one string. Returns (new_value, redaction_count)."""
        if not value.strip():
            return value, 0
        if role is not None:
            self.emit(role, value)
        if self.table is not None and role in ("patient_name", "mrn"):
            self.learn(role, value)
            self.identifiers += 1
            self.stats[ROLE_PLACEHOLDER[role]] += 1
            return self.sentinel("name" if role == "patient_name" else "mrn", ROLE_PLACEHOLDER[role]), 1
        if role in ("procedure", "package_code"):
            if self.table is None:
                return value, 0
            return self.sentinel("proc", value, (role, value.strip())), 0
        if role in ("age", "age_sex"):
            span = first_number_span(value)
            if self.table is None or span is None:
                return value, 0
            self.identifiers += 1
            self.stats["[AGE]"] += 1
            age = int(value[span[0]:span[1]])
            return value[:span[0]] + self.sentinel("age", value[span[0]:span[1]], age) + value[span[1]:], 1
        if role == "village" and self.table is not None and self.policy.get("village_mode") in ("tehsil", "district"):
            self.identifiers += 1
            self.stats["[VILLAGE]"] += 1
            return self.sentinel("village", "[VILLAGE]", self.policy["village_mode"]), 1
        if role == "district" and self.table is not None:
            return self.sentinel("district", value), 0
        if role == "tehsil" and self.table is not None:
            return self.sentinel("tehsil", value), 0
        if role in ROLE_PLACEHOLDER and role not in ("village", "house", "locality", "landmark"):
            self.learn(role, value)
            self.identifiers += 1
            self.stats[ROLE_PLACEHOLDER[role]] += 1
            return ROLE_PLACEHOLDER[role], 1
        if role in ("village", "house", "locality", "landmark"):
            if role == "village":
                self.learn(role, value)
            self.identifiers += 1
            self.stats[ROLE_PLACEHOLDER[role]] += 1
            return ROLE_PLACEHOLDER[role], 1
        if role == "address":
            out, n = rewrite_address(value, self.policy.get("pin_mode", "prefix3"),
                                     self.sentinel if self.table is not None else None)
            self.identifiers += n
            self.stats["[ADDRESS]"] += n
            return out, n
        if role == "pin":
            d = re.sub(r"\D", "", ascii_digits(value))
            self.identifiers += 1
            self.stats["[PIN]"] += 1
            if self.table is not None and len(d) == 6:
                return self.sentinel("pin", d[:3] + "***" if self.policy.get("pin_mode") == "prefix3" else "[PIN]", d), 1
            if len(d) == 6 and self.policy.get("pin_mode", "prefix3") == "prefix3":
                return d[:3] + "***", 1
            return "[PIN]", 1
        if role == "path":
            parts = re.split(r"([\\/])", value)
            out = "".join(p if i % 2 else _clean_component(p, self.names, self.ids) for i, p in enumerate(parts))
            n = int(out != value)
            self.identifiers += n
            self.stats["[PATH]"] += n
            return out, n
        if role == "dob":
            self.identifiers += 1
            self.stats["[DOB]"] += 1
            mode = self.policy.get("dob_mode", "shift")
            if mode == "shift" and self.table is not None:
                toks = find_dates(ascii_digits(value), self.order())
                if toks:
                    t = toks[0]
                    return (value[:t.start] + self.sentinel("date", value[t.start:t.end], (t, self.ref_year))
                            + value[t.end:]), 1
                return "[DOB]", 1
            return (dob_year(value) if mode != "redact" else "[DOB]"), 1
        return self.scrub_text(value, doc_labels=("\n" in value))

    # ---- free text ---------------------------------------------------------------------
    def scrub_text(self, text: str, doc_labels: bool = False):
        """Detect-and-redact in prose. doc_labels: also honour `Label: value` segments."""
        if not text.strip():
            return text, 0
        if doc_labels:
            return self._scrub_lines(text)
        return self._scrub_plain(text)

    def _scrub_plain(self, text: str):
        text, n_enc = self._scrub_encoded(text)
        if not text.strip():
            return text, n_enc
        shadow, offs = normalize(text)
        guards = guard_spans(shadow)
        hard = find_hard(shadow)
        for s in hard:
            if s.kind == "ID":
                self.ids.add(shadow[s.start:s.end])  # a labelled ID is known from here on, labelled or not
        if self.sink is not None:
            for s in hard:
                self.emit("hard:" + s.kind, shadow[s.start:s.end])
        fixed = [(s.start, s.end, PLACEHOLDER[s.kind]) for s in hard]
        fixed += self._privacy_spans(shadow, guards, hard)
        phone_spans = [(s.start, s.end) for s in hard if s.kind == "PHONE"]
        for s, e in self.ids.find(shadow):
            fixed.append((s, e, "[ID]"))
            self.emit("id:known", shadow[s:e])
        names = []
        for s, e, kind in cue_name_spans_typed(shadow, phone_spans, self.names):
            if not overlaps_guard([g for g in guards if g[2] in ("doctor", "history", "ward", "hospital")], s, e):
                names.append((s, e))
                if kind in ("subject", "rel"):
                    self.emit("name:" + kind, shadow[s:e])
        for m in _GENERIC_ID.finditer(shadow):
            if sum(c.isdigit() for c in m.group(0)) >= 4 and m.group(1).casefold() not in medical_words() \
                    and not overlaps_guard(guards, m.start(), m.end()):
                fixed.append((m.start(), m.end(), "[ID]"))
                self.ids.add(m.group(0))
        fixed += self._pin_spans(shadow, guards)
        fixed += self._place_spans(shadow, guards)
        names += self.names.find(shadow, guards)
        names += Gazetteer.runs(shadow, guards)
        names = [(s, e) for s, e in merge_spans(names, shadow)]
        names = self._absorb_devanagari(shadow, names, guards)
        for s, e in list(names):  # "Surname, Given Names": the surname before the comma goes too
            m = re.search(r"([A-Z][A-Za-z']{2,}),[ \t]*$", shadow[max(0, s - 40):s])
            if m and not is_non_name(m.group(1)) and m.group(1).casefold() not in medical_words():
                a = s - (len(shadow[max(0, s - 40):s]) - m.start(1))
                if not overlaps_guard(guards, a, a + len(m.group(1))):
                    names.append((a, a + len(m.group(1))))
        names = [(s, e) for s, e in merge_spans(names, shadow)]
        spans = list(fixed)
        for s, e in names:
            if not any(s < b and a < e for a, b, _ in fixed):
                spans.append((s, e, "[NAME]"))
        spans = self._resolve(spans)
        mapped = []
        for s, e, ph in spans:
            a, b = map_span(offs, s, e, len(text))
            if isinstance(ph, tuple):  # generalisation resolved after clustering
                kind, payload, *fb = ph
                if self.table is None:
                    continue
                ph = self.sentinel(kind, fb[0] if fb else text[a:b], payload)
            mapped.append((a, b, ph))
        for a, b, ph in reversed(sorted(mapped)):
            text = text[:a] + ph + text[b:]
        for _a, _b, ph in mapped:
            if not ph.startswith("@@"):
                self.stats[ph] += 1
        self.identifiers += len(mapped)
        return text, len(mapped) + n_enc

    def _scrub_encoded(self, text: str):
        """Percent-encoded, \\uXXXX-escaped and HTML-entity text: decode, scrub, re-encode only if changed."""
        total = 0
        for decode, encode in ENCODINGS:
            if not decode.detect(text):
                continue
            plain = decode.run(text)
            new, n = self.scrub_decoded(plain)
            if n:
                text = self.wrap_encoded(new, encode)
                total += n
        text, n = self._scrub_b64_tokens(text)
        return text, total + n

    def _scrub_b64_tokens(self, text: str):
        """Base64 values inside plain text (key.b64=..., envelope fields): decode, scrub, re-encode only if changed."""
        if "@@PSN" in text or not _B64_TOKEN.search(text):
            return text, 0
        total, out, pos = 0, [], 0
        for m in _B64_TOKEN.finditer(text):
            tok = m.group(0)
            if not (any(c.isdigit() for c in tok) or tok.endswith("=") or (tok != tok.lower() and tok != tok.upper())):
                continue
            plain = decode_b64_text(tok)
            if plain is None or len(plain.strip()) < 4 or not plain.isascii():
                continue
            new, n = self.scrub_decoded(plain)
            if n and new != plain:
                out.append(text[pos:m.start()])
                out.append(self.wrap_encoded(new, encode_b64_text))
                pos, total = m.end(), total + n
        out.append(text[pos:])
        return "".join(out), total

    def scrub_decoded(self, text: str, doc_labels: bool = False):
        """Scrub the decoded text of an encoded value. Dates, ages and codes still go through the privacy plan."""
        saved = self._scrub_encoded
        self._scrub_encoded = lambda t: (t, 0)  # prevent recursion into the same layers
        self.in_payload += 1
        try:
            return self.scrub_text(text, doc_labels=doc_labels) if doc_labels else self._scrub_plain(text)
        finally:
            self._scrub_encoded = saved
            self.in_payload -= 1

    def wrap_encoded(self, inner: str, encode) -> str:
        """Re-encode once the placeholders inside `inner` are resolved (learn pass: encode directly)."""
        if self.table is None:
            return encode(inner)
        return self.sentinel("enc", "", (encode, inner))

    def _absorb_devanagari(self, shadow: str, names: list, guards) -> list:
        """Devanagari words right next to a detected name are its other-script spelling or a further name part."""
        if not names or not _DEVA_ANY.search(shadow):
            return names
        func = words_of("deva_function_words.txt") | medical_words()
        out = []
        for s, e in names:
            for _ in range(3):
                m = _DEVA_AFTER.match(shadow, e)
                if not m or m.group(1) in func or overlaps_guard(guards, m.start(1), m.end(1)):
                    break
                e = m.end(1)
            for _ in range(3):
                m = _DEVA_BEFORE.search(shadow, max(0, s - 40), s)
                if not m or m.group(1) in func or overlaps_guard(guards, m.start(1), m.end(1)):
                    break
                s = m.start(1)
            out.append((s, e))
        return [(a, b) for a, b in merge_spans(out, shadow)]

    _PIN_LABELLED = re.compile(r"(?<![\w])(?:p[1i]n(?:\s*code)?|postal\s*(?:code|zone)|post\s*code|zone|zip|da+k|dak\s*(?:code|pin)|पिन(?:\s*कोड)?|डाक)\s*[:=#\-]?\s*([1-9]\d{5})(?!\d)", re.I)
    _PIN_AFTER_PLACE = re.compile(r"(?<![\w])([A-Z][A-Za-z]{3,})[ \t\"',/;:\-(^|]+([1-8]\d{5})(?!\d)")
    _PIN_BARE = re.compile(r"(?<![\w.,/\-:₹])([1-8]\d{5})(?![\w]|[.,]\d|\s*(?:/|per\b|cells?\b|cumm\b|mm\b|mg\b|ml\b|iu\b))")
    _NOT_A_PIN_CONTEXT = frozenset({"rs", "inr", "count", "total", "amount", "bill", "paid", "cost", "fee", "charges", "platelet",
                                    "platelets", "wbc", "rbc", "cells", "sample", "id", "no", "number", "ref", "ipd", "opd",
                                    "invoice", "receipt", "claim", "balance", "due"})
    _VILLAGE_CUE = re.compile(r"(?<![\w])(?i:village|vill|gaon|gaanv|gram|ghar|nivasi|niwasi|r/o|resident\s+of|native\s+of)\.?[ \t:,\-]+"
                              r"([A-Z][a-z]{3,}(?:[ \t]+[A-Z][a-z]{3,})?)|(?:गाँव|गांव|ग्राम|निवासी)[ \t:,\-]+([ऀ-ॿ]{3,})")

    def _pin_spans(self, shadow: str, guards) -> list:
        """6-digit PIN codes in prose: labelled, or right after a capitalised place word. Never lab values."""
        blocked = [(a, b) for a, b, k in guards if k in ("frequency", "vital", "range", "dose", "loinc", "doctor")]
        out = []
        for m in self._PIN_BARE.finditer(shadow):  # a bare 6-digit number that is not a count, amount or reference
            if shadow.strip() == m.group(1):
                continue  # a cell or value that is only a number: an amount or a count, not an address
            prev = re.findall(r"[A-Za-z]+", shadow[max(0, m.start() - 30):m.start()])[-2:]
            if any(w.casefold() in self._NOT_A_PIN_CONTEXT or w.casefold() in medical_words() for w in prev):
                continue
            if any(m.start(1) < b and a < m.end(1) for a, b in blocked):
                continue
            d = m.group(1)
            fb = d[:3] + "***" if self.policy.get("pin_mode", "prefix3") == "prefix3" else "[PIN]"
            out.append((m.start(1), m.end(1), ("pin", d, fb)))
        for rx, grp in ((self._PIN_LABELLED, 1), (self._PIN_AFTER_PLACE, 2)):
            for m in rx.finditer(shadow):
                s, e = m.start(grp), m.end(grp)
                if rx is self._PIN_AFTER_PLACE:
                    w = m.group(1)
                    if w.casefold() in medical_words() or is_non_name(w):
                        continue
                if any(s < b and a < e for a, b in blocked):
                    continue
                if rx is self._PIN_AFTER_PLACE and w.casefold() not in self.districts:
                    ws = m.start(1)
                    out.append((ws, m.end(1), ("village", self.policy.get("village_mode"), "[VILLAGE]")
                                if self.policy.get("village_mode") in ("tehsil", "district") else "[VILLAGE]"))
                    self.places.setdefault(w.casefold(), set()).add(w.casefold())
                d = shadow[s:e]
                fb = d[:3] + "***" if self.policy.get("pin_mode", "prefix3") == "prefix3" else "[PIN]"
                out.append((s, e, ("pin", d, fb)))
        return out

    def _place_spans(self, shadow: str, guards) -> list:
        """Villages learned from structured fields, wherever they appear in prose."""
        mode = self.policy.get("village_mode")
        ph = ("village", mode, "[VILLAGE]") if mode in ("tehsil", "district") else "[VILLAGE]"
        out = []
        for m in self._VILLAGE_CUE.finditer(shadow):
            g = 1 if m.group(1) else 2
            w = m.group(g)
            first = w.split()[0]
            if (first.casefold() in medical_words() or first.casefold() in words_of("hinglish_stopwords.txt")
                    or is_non_name(first) or overlaps_guard(guards, m.start(g), m.end(g))):
                continue
            out.append((m.start(g), m.end(g), ph))
        if not self.places:
            return out
        words = list(iter_words(shadow))
        for i, (s, e, w) in enumerate(words):
            phrases = self.places.get(w.casefold())
            if not phrases or overlaps_guard(guards, s, e):
                continue
            best = None
            for ph in sorted(phrases, key=len, reverse=True):
                n = ph.count(" ") + 1
                if i + n <= len(words) and " ".join(x[2].casefold() for x in words[i:i + n]) == ph:
                    best = (words[i][0], words[i + n - 1][1])
                    break
            if best:
                out.append((best[0], best[1], ("village", mode, "[VILLAGE]") if mode in ("tehsil", "district") else "[VILLAGE]"))
        return out

    def _privacy_spans(self, shadow: str, guards, hard) -> list:
        """Dates, ages and ICD codes (with their display text) as generalisation spans."""
        out = []
        skip = [(s.start, s.end) for s in hard]
        soft = [(a, b) for a, b, k in guards if k in ("frequency", "vital", "range", "dose", "loinc")]
        votes = []
        toks = find_dates(shadow, self.order(), skip, votes, soft_skip=soft)
        if votes:
            self.vote_orders(votes)
        taken = list(skip) + soft
        for t in toks:
            if t.year:
                self.year_counts[t.year] += 1
            out.append((t.start, t.end, ("date", (t, self.ref_year))))
            taken.append((t.start, t.end))
        if self.table is None:
            return out
        for s, e in find_ages(shadow):
            if not any(s < b and a < e for a, b in taken):
                out.append((s, e, ("age", int(shadow[s:e]))))
                taken.append((s, e))
        for m in ICD_RX.finditer(shadow):
            if any(m.start() < b and a < m.end() for a, b in taken):
                continue
            code = m.group(1).upper()
            out.append((m.start(1), m.end(1), ("icd", code)))
            taken.append((m.start(1), m.end(1)))
            pm = re.search(r"([^;:\n|()]{3,120}?)\s*\(\s*$", shadow[:m.start(1)])
            if pm and re.search(r"[A-Za-z]{3}", pm.group(1)) and not any(pm.start(1) < b and a < pm.end(1) for a, b in taken):
                out.append((pm.start(1), pm.end(1), ("icd_text", code)))
                taken.append((pm.start(1), pm.end(1)))
        return out

    @staticmethod
    def _resolve(spans):
        """Drop overlaps (earlier-listed spans win)."""
        kept = []
        for s, e, ph in spans:
            if e <= s or any(s < b and a < e for a, b, _ in kept):
                continue
            kept.append((s, e, ph))
        kept.sort()
        return kept

    def _scrub_lines(self, text: str):
        out_lines, total = [], 0
        for line in text.split("\n"):
            new, n = self._scrub_line(line)
            out_lines.append(new)
            total += n
        total += self._continued_name_lines(text.split("\n"), out_lines)
        return "\n".join(out_lines), total

    _ONE_WORD_LINE = re.compile(r"^\s*([A-Z][a-z]{3,})\s*$")

    def _continued_name_lines(self, src: list, out: list) -> int:
        """A lone capitalised word on a line next to a line that is only a redacted name continues that name."""
        added = 0
        for i, line in enumerate(out):
            if line.strip() != "[NAME]":
                continue
            for step in (-1, 1):
                j = i + step
                while 0 <= j < len(src) and j - i in range(-3, 4):
                    m = self._ONE_WORD_LINE.match(src[j])
                    w = m.group(1) if m else ""
                    if (not m or out[j] != src[j] or is_non_name(w) or w.casefold() in medical_words()
                            or w.casefold() in words_of("hinglish_stopwords.txt") or w.casefold() in words_of("filename_words.txt")):
                        break
                    out[j] = "[NAME]"
                    added += 1
                    j += step
        return added

    def _scrub_line(self, line: str):
        marks = list(_LABEL.finditer(line))
        if not marks:
            return self._scrub_plain(line)
        pieces, total, pos = [], 0, 0
        for i, m in enumerate(marks):
            label = m.group(1).strip()
            role, score = header_role(label)
            if role and len(label.split()) > 3 and score < 95:
                role = None  # a sentence fragment that merely resembles a header, not a field name
            vstart = m.end()
            vend = marks[i + 1].start() if i + 1 < len(marks) else len(line)
            self.src = label
            if role is None and ("/" in label or "." in label):
                # compound labels such as "Pt. Name/Age": try each part
                for part in re.split(r"[/.]", label):
                    role, _ = header_role(part)
                    if role:
                        break
            if m.start() > pos:
                head, n = self._scrub_plain(line[pos:m.start()])
                pieces.append(head)
                total += n
            pieces.append(line[m.start():vstart])
            value = line[vstart:vend]
            trail = value[len(value.rstrip()):]
            if role is None:
                # unknown label: scan label and value together so label-anchored IDs are seen
                whole, n = self._scrub_plain(line[m.start():vend].rstrip())
                pieces.pop()
                pieces.append(whole + trail)
                total += n
                pos = vend
                continue
            body, rest = value.rstrip(), ""
            if role in _TOKEN_ROLES:  # a number or ID: anything after a wide gap is separate text, scan it on its own
                parts = re.split(r"(\s{2,})", body.lstrip(), maxsplit=1)
                if len(parts) == 3:
                    lead = body[:len(body) - len(body.lstrip())]
                    body, rest = lead + parts[0], parts[1] + parts[2]
            new, n = self.scrub_value(role, body)
            total += n
            if rest:
                tail, k = self._scrub_plain(rest)
                new, total = new + tail, total + k
            pieces.append(new + trail)
            pos = vend
        if pos < len(line):
            tail, n = self._scrub_plain(line[pos:])
            pieces.append(tail)
            total += n
        return "".join(pieces), total
