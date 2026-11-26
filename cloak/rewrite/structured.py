"""Role-based rewriting of CSV, JSON/FHIR and text documents."""
import re

from cloak.detect.columns import PII_ROLES, header_role, infer_roles
from cloak.detect.guards import guard_spans, guarded
from cloak.detect.payloads import ATTACHMENT_PLACEHOLDER, decode_b64_text, encode_b64_text, looks_b64
from cloak.rewrite.keys_headers import safe_header, safe_key

REDACTED = "[REDACTED]"
_UUID = re.compile(r"^(urn:uuid:)?[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
_NAMEY_RUN = re.compile(r"(?<![A-Za-z])[A-Z][a-z]{2,}(?:\s+[A-Z][a-z]{2,})+(?![A-Za-z])")
_DEVA_NAME = re.compile(r"^\s*[ऀ-ॿ]+(?:\s+[ऀ-ॿ]+){0,3}\s*$")
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


def _nk(key: str) -> str:
    return re.sub(r"[^a-z0-9]", "", key.casefold())


def scrub_unknown(scrubber, value: str):
    """Unknown column/key: scrub, then fail closed on name-like leftovers."""
    out, n = scrubber.scrub_text(value, doc_labels=("\n" in value))
    probe = re.sub(r"\[[A-Z]+\]", " ", out)
    g = guard_spans(probe)
    if _DEVA_NAME.match(probe) or any(not guarded(g, m.start(), m.end()) for m in _NAMEY_RUN.finditer(probe)):
        scrubber.identifiers += 1
        return REDACTED, n + 1
    return out, n


# ------------------------------------------------------------------------------------ CSV
def transform_csv(header, body, scrubber):
    """Return (new_header, new_body, count)."""
    roles = infer_roles(header, body)
    count = 0
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
    for row in body:
        out = []
        for j, cell in enumerate(row):
            role = roles[j] if j < len(roles) else None
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
    return new_header, new_body, count


# ----------------------------------------------------------------------------------- JSON
class _Ctx:
    __slots__ = ("role", "person", "relative", "ref")

    def __init__(self, role=None, person=None, relative=False, ref=False):
        self.role, self.person, self.relative, self.ref = role, person, relative, ref


def _leaf_role(key, ctx: _Ctx):
    """Role for a scalar under `key` given the inherited context."""
    nk = _nk(key)
    own, _ = header_role(key)
    if ctx.person == "keep" and (own in (None, "patient_name", "doctor", "hospital") or nk in _GENERIC):
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
        if nk in _GENERIC:
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


def transform_json(data, scrubber, collect=False):
    """Return (new_data, count)."""
    count = [0]

    def scalar(key, v, ctx):
        if isinstance(v, bool) or v is None or isinstance(v, float):
            return v
        role = _leaf_role(key, ctx) if key is not None else (ctx.role if ctx.role else None)
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
                new, n = scrubber.scrub_text(text, doc_labels=True)
                count[0] += n
                return encode_b64_text(new)
        if _nk(key or "") == "div":
            count[0] += 1
            return '<div xmlns="http://www.w3.org/1999/xhtml">[REDACTED]</div>' if v.lstrip().startswith("<") else REDACTED
        if role in (None, "telecom"):
            new, n = scrub_unknown(scrubber, v)
        else:
            new, n = scrubber.scrub_value(role, v)
        count[0] += n
        return new

    def walk(v, key, ctx):
        if isinstance(v, dict):
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
            for k, x in v.items():
                if k in rank:
                    nk = "[KEY]" if rank[k] == 0 else f"[KEY]-{rank[k] + 1}"
                    count[0] += 1
                else:
                    nk = k
                out[nk] = walk(x, k, _child_ctx(k, x, ctx, v) if isinstance(x, (dict, list)) else ctx)
            return out
        if isinstance(v, list):
            return [walk(x, key, ctx) for x in v]
        return scalar(key, v, ctx)

    return walk(data, None, _Ctx()), count[0]


# ----------------------------------------------------------------------------------- text
def transform_text(text: str, scrubber):
    return scrubber.scrub_text(text, doc_labels=True)
