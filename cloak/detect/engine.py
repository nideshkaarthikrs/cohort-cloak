"""Text scrubber: hard identifiers, known IDs/shapes, known names, label-anchored fields, context cues."""
import re
from collections import Counter

from cloak.detect.address import rewrite_address
from cloak.detect.columns import header_role
from cloak.detect.context import cue_name_spans_typed
from cloak.detect.guards import guard_spans, guarded, overlaps_guard
from cloak.detect.ids import IdSet
from cloak.detect.names import Gazetteer, NameDict, merge_spans
from cloak.detect.normalize import map_span, normalize
from cloak.detect.payloads import ENCODINGS
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

_LABEL = re.compile(r"(?:^|(?<=\s{2})|(?<=[|;]\s)|(?<=\|))\s*([A-Za-z\u0900-\u097f][A-Za-z\u0900-\u097f ./()'&\-#]{0,38}?)\s*[:=]\s*(?=\S)", re.M)
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


class Scrubber:
    def __init__(self, policy: dict):
        self.policy = policy
        self.names = NameDict()
        self.ids = IdSet()
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
        names += self.names.find(shadow, guards)
        names += Gazetteer.runs(shadow, guards)
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
                kind, payload = ph
                if self.table is None:
                    continue
                ph = self.sentinel(kind, text[a:b], payload)
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
        return text, total

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
        return "\n".join(out_lines), total

    def _scrub_line(self, line: str):
        marks = list(_LABEL.finditer(line))
        if not marks:
            return self._scrub_plain(line)
        pieces, total, pos = [], 0, 0
        for i, m in enumerate(marks):
            label = m.group(1).strip()
            role, _ = header_role(label)
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
            new, n = self.scrub_value(role, value.rstrip())
            pieces.append(new + trail)
            total += n
            pos = vend
        if pos < len(line):
            tail, n = self._scrub_plain(line[pos:])
            pieces.append(tail)
            total += n
        return "".join(pieces), total
