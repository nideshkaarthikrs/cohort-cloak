"""Text scrubber: hard identifiers, known IDs/shapes, known names, label-anchored fields, context cues."""
import re

from cloak.detect.address import rewrite_address
from cloak.detect.columns import header_role
from cloak.detect.context import cue_name_spans
from cloak.detect.guards import guard_spans, guarded, overlaps_guard
from cloak.detect.ids import IdSet
from cloak.detect.names import NameDict
from cloak.detect.patterns import find_hard
from cloak.detect.validators import ascii_digits

PLACEHOLDER = {"PHONE": "[PHONE]", "AADHAAR": "[AADHAAR]", "ABHA": "[ABHA]", "PAN": "[PAN]", "EMAIL": "[EMAIL]",
               "INSURANCE": "[ID]", "ID": "[ID]", "NAME": "[NAME]", "RELATIVE": "[RELATIVE]"}
ROLE_PLACEHOLDER = {"patient_name": "[NAME]", "person_name": "[NAME]", "relative_name": "[RELATIVE]", "phone": "[PHONE]",
                    "email": "[EMAIL]", "aadhaar": "[AADHAAR]", "abha": "[ABHA]", "pan": "[PAN]", "mrn": "[ID]",
                    "insurance": "[ID]", "house": "[HOUSE]", "locality": "[LOCALITY]", "landmark": "[LOCALITY]",
                    "village": "[VILLAGE]"}
ROLE_KIND = {"phone": "PHONE", "email": "EMAIL", "aadhaar": "AADHAAR", "abha": "ABHA", "pan": "PAN", "mrn": "ID",
             "insurance": "ID"}

_LABEL = re.compile(r"(?:^|(?<=\s{2})|(?<=[|;]\s)|(?<=\|))\s*([A-Za-z\u0900-\u097f][A-Za-z\u0900-\u097f ./()'&\-#]{0,38}?)\s*:\s*(?=\S)", re.M)
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

    # ---- registration of known values -------------------------------------------------
    def learn(self, role: str, value) -> None:
        if value is None or isinstance(value, bool):
            return
        v = str(value).strip()
        if not v:
            return
        if role in ("patient_name", "person_name", "relative_name"):
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
        if role in ROLE_PLACEHOLDER and role not in ("village", "house", "locality", "landmark"):
            self.learn(role, value)
            self.identifiers += 1
            return ROLE_PLACEHOLDER[role], 1
        if role in ("village", "house", "locality", "landmark"):
            self.identifiers += 1
            return ROLE_PLACEHOLDER[role], 1
        if role == "address":
            out, n = rewrite_address(value, self.policy.get("pin_mode", "prefix3"))
            self.identifiers += n
            return out, n
        if role == "pin":
            d = re.sub(r"\D", "", ascii_digits(value))
            self.identifiers += 1
            if len(d) == 6 and self.policy.get("pin_mode", "prefix3") == "prefix3":
                return d[:3] + "***", 1
            return "[PIN]", 1
        if role == "dob":
            self.identifiers += 1
            return dob_year(value), 1
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
        guards = guard_spans(text)
        hard = find_hard(text)
        spans = [(s.start, s.end, PLACEHOLDER[s.kind]) for s in hard]
        phone_spans = [(s.start, s.end) for s in hard if s.kind == "PHONE"]
        for s, e in self.ids.find(text):
            spans.append((s, e, "[ID]"))
        for s, e in cue_name_spans(text, phone_spans):
            if not guarded(guards, s, e):
                spans.append((s, e, "[NAME]"))
        for s, e in self.names.find(text, guards):
            spans.append((s, e, "[NAME]"))
        spans = self._resolve(spans)
        for s, e, ph in reversed(spans):
            text = text[:s] + ph + text[e:]
        self.identifiers += len(spans)
        return text, len(spans)

    @staticmethod
    def _resolve(spans):
        """Drop overlaps, earlier-listed (higher priority) spans win; merge adjacent identical placeholders."""
        kept = []
        for s, e, ph in spans:
            if e <= s:
                continue
            if any(s < b and a < e for a, b, _ in kept):
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
            new, n = self.scrub_value(role, value.rstrip()) if role != "age_sex" else (value.rstrip(), 0)
            pieces.append(new + trail)
            total += n
            pos = vend
        if pos < len(line):
            tail, n = self._scrub_plain(line[pos:])
            pieces.append(tail)
            total += n
        return "".join(pieces), total
