"""Placement and generalisation sentinels: resolved once clusters and the privacy plan are known."""
import re
from collections import defaultdict

_SENTINEL = re.compile(r"(\n?)@@PSN(\d+)@@")
_GENERALISING = {"date", "age", "icd", "icd_text", "village", "district", "tehsil", "tehsil_seg", "district_seg", "pin"}


def resolve(table: list, unit_psn: dict, plan):
    """table: [(fid, rec, kind, fallback, payload)]. Returns (replacements, placed_units, generalised_units).

    Names: per record, the first patient-name placement becomes the PSN (others keep `[NAME]`); with none, the first
    MRN/UHID placement does; with neither, an appended `Patient:` line carries it. A record that is not linked keeps
    every fallback placeholder and appended lines vanish.
    Dates, ages, diagnoses and places are rewritten from the privacy plan of the record's patient group.
    """
    groups = defaultdict(list)
    for idx, entry in enumerate(table):
        groups[(entry[0], entry[1])].append(idx)
    repl = [None] * len(table)
    placed, touched = set(), set()
    for key in sorted(groups):
        idxs = groups[key]
        psn = unit_psn.get(key)
        kinds = [table[i][2] for i in idxs]
        target = None
        if psn:
            for want in ("name", "mrn", "append"):
                if want in kinds:
                    target = idxs[kinds.index(want)]
                    break
        for i in idxs:
            _fid, _rec, kind, fallback, payload = table[i]
            if kind == "enc":
                continue  # filled below, once the placeholders inside it are resolved
            if kind in ("name", "mrn", "append"):
                if i == target:
                    repl[i] = f"Patient: {psn}" if kind == "append" else psn
                    placed.add(key)
                else:
                    repl[i] = None if kind == "append" else fallback
                continue
            repl[i] = _generalise(kind, fallback, payload, key, plan)
            if repl[i] != fallback:
                touched.add(key)
    for i, entry in enumerate(table):  # encoded payloads: inner placeholders have lower indices, so index order works
        if entry[2] == "enc":
            encode, inner = entry[4]
            repl[i] = encode(substitute(inner, repl))
    return repl, placed, touched


def _generalise(kind, fallback, payload, unit, plan) -> str:
    if kind == "date":
        tok, ref_year = payload
        return tok.render(plan.shift(unit), ref_year)
    if kind == "age":
        return plan.band(unit, payload)
    if kind == "icd":
        return plan.icd(unit, payload)[0]
    if kind == "icd_text":
        text = plan.icd(unit, payload)[1]
        return fallback if text is None else text
    if kind == "village":
        return plan.place(unit, payload) or fallback
    if kind == "district":
        if plan.location_level(unit) >= 3:
            return plan.place(unit, "state") or "[DISTRICT]"
        return fallback
    if kind == "district_seg":
        return "[DISTRICT]" if plan.location_level(unit) >= 3 else fallback
    if kind == "tehsil":
        if plan.location_level(unit) >= 3:
            return "[TEHSIL]"
        return fallback if plan.policy.get("tehsil_mode") == "keep" else (plan.place(unit, "district") or "[TEHSIL]")
    if kind == "tehsil_seg":
        return fallback if plan.policy.get("tehsil_mode") == "keep" and plan.location_level(unit) < 3 else "[TEHSIL]"
    if kind == "pin":
        if plan.policy.get("pin_mode") != "prefix3" or plan.location_level(unit) >= 3:
            return "[PIN]"
        return payload[:3] + "***"
    return fallback


def substitute(text: str, repl: list) -> str:
    def one(m):
        r = repl[int(m.group(2))]
        return "" if r is None else m.group(1) + r
    return _SENTINEL.sub(one, text)
