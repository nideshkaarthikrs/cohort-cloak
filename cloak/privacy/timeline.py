"""Resolve date candidates after linking, using only the submitted input evidence."""
import datetime as dt
from collections import defaultdict
from dataclasses import replace


def resolve_dates(table, unit_group, shifts):
    groups = defaultdict(list)
    for i, (fid, rec, kind, fallback, payload) in enumerate(table):
        if kind == "date":
            groups[unit_group[(fid, rec)]].append((i, *payload))
    resolved = {}
    for group in sorted(groups, key=str):
        entries = groups[group]
        anchors = set()
        for _, tok, ref in entries:
            if tok.year and not tok.is_birth and (not tok.ambiguous or tok.order_known):
                anchors.add(tok.as_date(ref))
        for i, original, ref in entries:
            tok = replace(original)
            if tok.ambiguous and not tok.order_known:
                alternate = replace(tok, day=tok.month, month=tok.day,
                                    layout="mdy" if tok.layout == "dmy" else "dmy")
                matches = [t for t in (tok, alternate) if t.as_date(ref) in anchors]
                if len(matches) == 1:
                    tok = matches[0]
                    tok.order_known = True
            if tok.year:
                tok.year_resolved = True
            elif anchors:
                candidates = []
                for year in sorted({a.year + d for a in anchors for d in (-1, 0, 1)}):
                    try:
                        value = dt.date(year, tok.month, tok.day)
                    except ValueError:
                        continue
                    distance = min(abs((value - a).days) for a in anchors)
                    candidates.append((distance, year))
                candidates.sort()
                if candidates and (len(candidates) == 1 or candidates[0][0] < candidates[1][0]):
                    ref = candidates[0][1]
                    tok.year_resolved = True
                tok.append_year = tok.year_resolved and (tok.as_date(ref) + dt.timedelta(days=shifts[group])).year != ref
            if not tok.year and not tok.year_resolved:
                # Leap-day fragments are printable even when their calendar year is unknown.
                for offset in sorted(range(-4, 5), key=lambda n: (abs(n), n)):
                    try:
                        dt.date(ref + offset, tok.month, tok.day)
                        ref += offset
                        break
                    except ValueError:
                        pass
            resolved[i] = (tok, ref)
    return resolved
