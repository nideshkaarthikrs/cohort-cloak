"""Sniff the file kind by content, not extension."""
import csv
import io
import json
from dataclasses import dataclass

from cloak.errors import Quarantine
from cloak.ingest.encoding import decode_bytes

_BINARY_MAGIC = (b"%PDF", b"\xff\xd8\xff", b"\x89PNG", b"GIF8", b"PK\x03\x04", b"\x1f\x8b", b"BM", b"II*\x00", b"MM\x00*")
_DELIMS = (",", "\t", ";", "|")
_EXT_DELIM = {".csv": ",", ".tsv": "\t"}


@dataclass
class Parsed:
    kind: str                 # csv | json | jsonl | fhir | text
    text: str
    delimiter: str = ""
    data: object = None


def json_depth_exceeds(text: str, limit: int) -> bool:
    """Iterative bracket-depth scan (never recursive), ignoring brackets inside strings."""
    depth = 0
    in_str = esc = False
    for ch in text:
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
        elif ch == '"':
            in_str = True
        elif ch in "{[":
            depth += 1
            if depth > limit:
                return True
        elif ch in "}]":
            depth -= 1
    return False


def _rows(text: str, delim: str):
    return list(csv.reader(io.StringIO(text, newline=""), delimiter=delim))


def sniff_delimiter(text: str, ext: str) -> str:
    """Return a delimiter if the content is consistently tabular, else ''."""
    pref = _EXT_DELIM.get(ext)
    lines = [l for l in text.splitlines() if l.strip()][:50]
    if not lines:
        return ""
    if pref and pref in lines[0]:
        return pref
    best = ""
    for d in _DELIMS:
        try:
            rows = [r for r in _rows("\n".join(lines), d) if r]
        except csv.Error:
            continue
        counts = [len(r) for r in rows]
        if not counts or counts[0] < 2 or len(rows) < 3:
            continue
        mode = max(set(counts), key=counts.count)
        if mode < 2:
            continue
        lead = counts.index(mode)  # a few title rows may sit above the header row
        tail = counts[lead:]
        if lead > 6 or len(tail) < 3 or tail.count(mode) / len(tail) < 0.9:
            continue
        if lead and not all(1 <= c <= mode for c in counts[:lead]):
            continue
        if any(c.count(" ") >= 5 for c in rows[lead]):
            continue  # a prose or key=value log line, not a header row
        best = d
        break
    if not best and pref:
        return pref  # a .csv/.tsv file with a single column
    return best


def parse(raw: bytes, ext: str, max_depth: int) -> Parsed:
    ext = ext.lower()
    if not raw.strip():
        raise Quarantine("empty_file")
    if raw.startswith(_BINARY_MAGIC):
        raise Quarantine("unsupported_format")
    text = decode_bytes(raw)
    if not text.strip("﻿ \t\r\n"):
        raise Quarantine("empty_file")
    body = text.lstrip("﻿ \t\r\n")
    if body.startswith("<"):
        raise Quarantine("unsupported_format")  # xml / html
    if body[0] in "{[":
        if json_depth_exceeds(body, max_depth):
            raise Quarantine("nesting_too_deep")
        try:
            data = json.loads(body)
        except (ValueError, RecursionError):
            lines = [l for l in body.splitlines() if l.strip()]
            recs = []
            if body[0] == "{" and len(lines) >= 2:
                try:
                    recs = [json.loads(l) for l in lines]
                except (ValueError, RecursionError):
                    recs = []
            if recs and all(isinstance(r, dict) for r in recs):
                return Parsed("jsonl", text, data=recs)
            if body[0] == "{" or ext == ".json":
                raise Quarantine("malformed_json")
            data = None  # '[' text such as a chat export
        if data is not None:
            fhir = isinstance(data, dict) and data.get("resourceType") == "Bundle"
            return Parsed("fhir" if fhir else "json", text, data=data)
    elif ext == ".json":
        raise Quarantine("malformed_json")
    delim = sniff_delimiter(text, ext)
    if delim:
        return Parsed("csv", text, delimiter=delim)
    return Parsed("text", text)
