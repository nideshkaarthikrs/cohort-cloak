"""Role-based rewriting of CSV, JSON/FHIR and text documents."""
import re

from cloak.detect.columns import PII_ROLES, header_role, infer_roles
from cloak.detect.guards import guard_spans, guarded
from cloak.detect.names import is_non_name
from cloak.privacy.suppress import ICD_RX
from cloak.detect.payloads import ATTACHMENT_PLACEHOLDER, decode_b64_text, encode_b64_text, looks_b64
from cloak.rewrite.keys_headers import safe_header, safe_key

REDACTED = "[REDACTED]"
_UUID = re.compile(r"^(urn:uuid:)?[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
_NAMEY_RUN = re.compile(r"(?<![A-Za-z])[A-Z][a-z]{2,}(?:\s+[A-Z][a-z]{2,})+(?![A-Za-z])")
_DEVA_NAME = re.compile(r"^\s*[ऀ-ൿء-ٟٱ-ۓ]+(?:\s+[ऀ-ൿء-ٟٱ-ۓ]+){0,3}\s*$")
_GENERIC = {"text", "value", "display", "given", "family", "line", "data", "first", "last", "local", "prefix",
            "suffix", "middle", "full", "official", "nickname", "content", "string", "valuestring"}
_NAME_PARTS = {"text", "display", "given", "family", "first", "last", "local", "prefix", "suffix", "middle", "full",
               "official", "nickname"}
_PATIENT_KEYS = {"subject", "patient", "beneficiary", "individual"}
_RELATIVE_KEYS = {"contact", "guardian", "relative", "relatedperson", "nextofkin", "nok", "attendant", "emergency"}
_KEEP_KEYS = {"practitioner", "performer", "author", "requester", "doctor", "organization", "serviceprovider",
              "facility", "hospital", "recorder", "asserter", "participant", "individualpractitioner", "consultant"}
_RESOURCE_PERSON = {"Patient": "patient", "RelatedPerson": "relative", "Practitioner": "keep", "PractitionerRole": "keep",
                    "Organization": "keep", "Location": "keep", "HealthcareService": "keep"}


def _dict_icd(d: dict):
    """ICD-10 code of a coded element ({code, display} or {coding: [{code}], text}), else None."""
    code = d.get("code")
    if isinstance(code, str) and ICD_RX.fullmatch(code.strip()):
        return code.strip().upper()
    coding = d.get("coding")
    if isinstance(coding, list):
        for c in coding:
            if isinstance(c, dict) and isinstance(c.get("code"), str) and ICD_RX.fullmatch(c["code"].strip()):
                return c["code"].strip().upper()
    return None


def _nk(key: str) -> str:
    return re.sub(r"[^a-z0-9]", "", key.casefold())


def scrub_unknown(scrubber, value: str):
    """Unknown column/key: scrub, then fail closed on name-like leftovers."""
    out, n = scrubber.scrub_text(value, doc_labels=("\n" in value))
    probe = re.sub(r"\[[A-Z]+\]", " ", out)
    g = guard_spans(probe)
    nameish = [m for m in _NAMEY_RUN.finditer(probe)
               if not guarded(g, m.start(), m.end()) and not all(is_non_name(t) for t in m.group(0).split())]
    if _DEVA_NAME.match(probe) or nameish:
        scrubber.identifiers += 1
        return REDACTED, n + 1
    return out, n


# ------------------------------------------------------------------------------------ CSV
def _header_row(header, body):
    """Index into `body` of the real header when title/preamble rows come first, else -1."""
    widths = [len(r) for r in body if any(c.strip() for c in r)]
    if not widths or len(header) >= max(set(widths), key=widths.count):
        return -1
    width = max(set(widths), key=widths.count)
    for i, row in enumerate(body[:6]):
        if len(row) == width and sum(1 for c in row if header_role(c)[0] is not None) >= 2:
            return i
    return -1


def transform_csv(header, body, scrubber, offset=0):
    """Return (new_header, new_body, count). `offset`: index of body[0] among the file's data rows (for records)."""
    hidx = _header_row(header, body) if offset == 0 else -1
    if hidx >= 0:
        pre, real, rest = body[:hidx], body[hidx], body[hidx + 1:]
        sub_header, sub_body, n = transform_csv(real, rest, scrubber, offset=hidx + 1)
        new_header, _hb, n0 = transform_csv(header, [], scrubber)
        pre_out = []
        for ri, row in enumerate(pre):
            scrubber.rec = f"row:{ri}"
            out = []
            for cell in row:
                new, k = scrub_unknown(scrubber, cell) if cell.strip() else (cell, 0)
                n += k
                out.append(new)
            pre_out.append(out)
        scrubber.rec = "doc"
        return new_header, pre_out + [sub_header] + sub_body, n + n0
    roles = infer_roles(header, body)
    count = 0
    if scrubber.table is None:  # d/m vs m/d hints from headers such as "DOB (MM/DD/YYYY)"
        for j, h in enumerate(header):
            scrubber.src = f"c{j}"
            if re.search(r"(?i)\bmm\W{0,3}dd", h):
                scrubber.vote_orders(["mdy"] * 1000)
            elif re.search(r"(?i)\bdd\W{0,3}mm", h):
                scrubber.vote_orders(["dmy"] * 1000)
    new_header, seen = [], {}
    for h in header:
        if safe_header(h, scrubber):
            new_header.append(h)
        else:
            count += 1
            c = seen.get("[COLUMN]", 0) + 1
            seen["[COLUMN]"] = c
            new_header.append("[COLUMN]" if c == 1 else f"[COLUMN]-{c}")
    new_body = []
    for ri, row in enumerate(body):
        scrubber.rec = f"row:{ri + offset}"
        out = []
        ragged = len(row) != len(header) and any(c.strip() for c in row)  # a shifted row: column positions no longer mean anything
        for j, cell in enumerate(row):
            role = None if ragged else (roles[j] if j < len(roles) else None)
            scrubber.src = f"c{j}"
            if not cell.strip():
                out.append(cell)
                continue
            if role is None:
                new, n = scrub_unknown(scrubber, cell)
            else:
                new, n = scrubber.scrub_value(role, cell)
            out.append(new)
            count += n
        new_body.append(out)
    scrubber.rec = "doc"
    return new_header, new_body, count


# ----------------------------------------------------------------------------------- JSON
class _Ctx:
    __slots__ = ("role", "person", "relative", "ref", "prof")

    def __init__(self, role=None, person=None, relative=False, ref=False, prof=None):
        self.role, self.person, self.relative, self.ref, self.prof = role, person, relative, ref, prof


def _row_profile(rows) -> dict:
    """Roles for unknown keys of a list of records, from the values like CSV columns (names, IDs, phones...)."""
    keys = sorted({k for r in rows for k in r if isinstance(k, str) and header_role(k)[0] is None})
    prof = {}
    for k in keys:
        cells = [[r[k]] for r in rows if isinstance(r.get(k), str) and r[k].strip()]
        if cells:
            role = infer_roles([k], cells)[0]
            if role in PII_ROLES:
                prof[k] = role
    return prof


def _leaf_role(key, ctx: _Ctx):
    """Role for a scalar under `key` given the inherited context."""
    nk = _nk(key)
    own, _ = header_role(key)
    explicit_patient = own == "patient_name" and nk not in ("name", "fullname", "naam", "nam")
    if ctx.person == "keep" and not explicit_patient and (own in (None, "patient_name", "doctor", "hospital") or nk in _GENERIC):
        return "doctor"
    if own == "patient_name":
        return "relative_name" if ctx.relative else "patient_name"
    if own in PII_ROLES:
        return own
    if nk in _GENERIC or own is None:
        in_name_container = ctx.role in ("patient_name", "relative_name", "person_name")
        if nk in _NAME_PARTS and (in_name_container or (nk == "display" and ctx.ref)):
            return "relative_name" if ctx.person == "relative" or ctx.relative or ctx.role == "relative_name" else "patient_name"
        if ctx.role and nk in _GENERIC:
            return ctx.role
        if nk in ("valuestring", "string"):
            return None
        if nk in ("text", "display", "value", "code", "line", "local"):
            return "clinical"
        return None
    return own


def _child_ctx(key, value, ctx: _Ctx, parent_dict) -> _Ctx:
    nk = _nk(key)
    if nk in _GENERIC:
        return ctx  # lists/objects under generic part keys (line, given...) keep the inherited role
    own, _ = header_role(key)
    person, relative, role = ctx.person, ctx.relative, ctx.role
    ref = False
    if nk in _PATIENT_KEYS or (own == "patient_name" and nk == "patient"):
        person, ref = "patient", True
    if nk in _RELATIVE_KEYS or own == "relative_name":
        person, relative, ref = "relative", True, True
    if nk in _KEEP_KEYS or own in ("doctor", "hospital", "relation", "clinical"):
        person, relative = "keep", False
    role = None  # a container's role never leaks into unrelated children
    if own in ("address", "mrn", "patient_name", "relative_name", "person_name", "village", "pin"):
        role = own
        if own == "patient_name" and (relative or person == "relative"):
            role = "relative_name"
    elif nk == "telecom":
        role = "telecom"
    return _Ctx(role, person, relative, ref)


def transform_json(data, scrubber, locs=()):
    """Return (new_data, count)."""
    count = [0]
    loc_set = set(locs) - {"doc"}
    scrubber.rec = "doc"
    if isinstance(data, dict) and data.get("resourceType") == "Bundle":
        patients = [e.get("resource") for e in data.get("entry", [])
                    if isinstance(e, dict) and isinstance(e.get("resource"), dict)
                    and e["resource"].get("resourceType") == "Patient"]
        if len(patients) > 1:
            scrubber.emit("multi_patient_unit", "1")

    def scalar(key, v, ctx):
        if isinstance(v, bool) or v is None:
            return v
        scrubber.src = key or ""
        role = _leaf_role(key, ctx) if key is not None else (ctx.role if ctx.role else None)
        if role is None and ctx.prof and key in ctx.prof:
            role = ctx.prof[key]
        if isinstance(v, (int, float)) and role == "age" and (not isinstance(v, int) or not 0 <= v <= 120):
            count[0] += 1
            return "[AGE]"
        if isinstance(v, float):
            return v
        if isinstance(v, int) and role == "age" and scrubber.table is not None and 0 <= v <= 120:
            scrubber.emit("age", v)
            count[0] += 1
            return scrubber.sentinel("age", str(v), v)
        if isinstance(v, int):
            if role in PII_ROLES and role not in ("dob",):
                scrubber.learn(role, v)
                count[0] += 1
                return 0
            if len(str(abs(v))) >= 9:
                scrubber.ids.add(v, shape=False)
                count[0] += 1
                return 0
            return v
        if not isinstance(v, str):
            return v
        if v == "" or _UUID.match(v) or _nk(key or "") == "resourcetype":
            return v
        if looks_b64(v):
            text = decode_b64_text(v)
            if text is None:
                if len(v) >= 64:
                    count[0] += 1
                    return encode_b64_text(ATTACHMENT_PLACEHOLDER)
            else:
                new, n = scrubber.scrub_decoded(text, doc_labels=True)
                count[0] += n
                return scrubber.wrap_encoded(new, encode_b64_text)
        if (scrubber.table is not None and scrubber.dx_pending and _nk(key or "") in ("display", "text")
                and not looks_b64(v)):
            count[0] += 1
            return scrubber.sentinel("icd_text", v, scrubber.dx_pending)
        if _nk(key or "") == "div":
            count[0] += 1
            return '<div xmlns="http://www.w3.org/1999/xhtml">[REDACTED]</div>' if v.lstrip().startswith("<") else REDACTED
        if role in (None, "telecom"):
            new, n = scrub_unknown(scrubber, v)
        else:
            new, n = scrubber.scrub_value(role, v)
        count[0] += n
        return new

    def walk(v, key, ctx, path=()):
        if loc_set and len(path) in (1, 2):
            ptr = "/" + "/".join(str(p).replace("~", "~0").replace("/", "~1") for p in path)
            if ptr in loc_set:
                prev, scrubber.rec = scrubber.rec, ptr
                try:
                    return _walk(v, key, ctx, path)
                finally:
                    scrubber.rec = prev
        return _walk(v, key, ctx, path)

    def _walk(v, key, ctx, path):
        if isinstance(v, list):
            recs = [x for x in v if isinstance(x, dict)]
            if len(recs) >= 2:
                prof = _row_profile(recs)
                if prof:
                    ctx = _Ctx(ctx.role, ctx.person, ctx.relative, ctx.ref, prof)
            return [walk(x, key, ctx, path + (i,)) for i, x in enumerate(v)]
        if not isinstance(v, dict):
            return scalar(key, v, ctx)
        rt = v.get("resourceType")
        if isinstance(rt, str) and rt in _RESOURCE_PERSON:
            ctx = _Ctx(None, _RESOURCE_PERSON[rt], rt == "RelatedPerson")
        url = v.get("url")
        if isinstance(url, str) and "/" in url:
            hint, _ = header_role(url.rstrip("/").rsplit("/", 1)[-1].replace("-", " ").replace("_", " "))
            if hint in PII_ROLES:
                relative = hint == "relative_name" or ctx.relative
                ctx = _Ctx(hint, ctx.person, relative, ctx.ref)
        bad = sorted(k for k in v if not safe_key(k, scrubber))
        rank = {k: i for i, k in enumerate(bad)}
        out = {}
        prev_dx = scrubber.dx_pending
        dx = _dict_icd(v)
        if dx:
            scrubber.dx_pending = dx
        try:
            for k, x in v.items():
                if k in rank:
                    nk = "[KEY]" if rank[k] == 0 else f"[KEY]-{rank[k] + 1}"
                    count[0] += 1
                else:
                    nk = k
                child = _child_ctx(k, x, ctx, v) if isinstance(x, (dict, list)) else ctx
                if k == "value" and isinstance(x, str):  # a FHIR ContactPoint: its system says what the value is
                    kind = {"phone": "phone", "sms": "phone", "fax": "phone", "pager": "phone", "email": "email"}.get(str(v.get("system", "")).casefold())
                    if kind:
                        child = _Ctx(kind, ctx.person, ctx.relative, ctx.ref)
                out[nk] = walk(x, k, child, path + (k,))
        finally:
            scrubber.dx_pending = prev_dx
        if isinstance(rt, str) and out.get("birthDate") == "[DOB]":
            # FHIR R4: a masked date is expressed with the data-absent-reason extension, not a placeholder string
            del out["birthDate"]
            out["_birthDate"] = {"extension": [{"url": "http://hl7.org/fhir/StructureDefinition/data-absent-reason",
                                                 "valueCode": "masked"}]}
        return out

    return walk(data, None, _Ctx()), count[0]


# ----------------------------------------------------------------------------------- text
def transform_text(text: str, scrubber):
    return scrubber.scrub_text(text, doc_labels=True)
