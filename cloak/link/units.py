"""Glue: events -> per-unit evidence -> clusters -> PSN per unit, and the per-record patient decision."""
import statistics
from collections import Counter, defaultdict

from cloak.link import cluster as clustering
from cloak.link import evidence as ev_mod
from cloak.link import pseudonym


def _unit_keys(results):
    """Clustering units: (fid, loc) for every record, except the doc line of pointer-style JSON files."""
    units = []
    for fid, (_rel, _sha, data, locs, _reason) in enumerate(results):
        if data is None:
            continue
        pointer_style = any(l != "doc" and not l.startswith("row:") for l in locs)
        for loc in locs:
            if loc == "doc" and pointer_style:
                continue
            units.append((fid, loc))
    return units


def link_units(results, sink, keys, policy):
    """Return ({(fid, loc): PSN or None}, stats)."""
    by_unit = defaultdict(list)
    years = Counter()
    for fid, rec, kind, value in sink:
        by_unit[(fid, rec)].append((kind, value))
        if kind == "date_event":
            y = ev_mod.event_year(value)
            if y:
                years[y] += 1
    default_year = years.most_common(1)[0][0] if years else 2026
    units = _unit_keys(results)
    evs = [ev_mod.build(by_unit.get(u, ()), default_year) for u in units]
    roots, uf = clustering.cluster(evs, int(policy["link_threshold"]), int(policy["soft_link_margin"]))
    final = clustering.assign_fragments(evs, roots, uf)
    frag = sum(1 for a, b in zip(roots, final) if a is None and b is not None)
    groups = defaultdict(list)
    for i, r in enumerate(final):
        if r is not None:
            groups[r].append(evs[i])
    psn_by_root = pseudonym.assign(keys, groups)
    unit_psn = {u: (psn_by_root[final[i]] if final[i] is not None else None) for i, u in enumerate(units)}
    unit_info = {}
    for i, u in enumerate(units):
        info = {"gender": evs[i].gender or ""}
        for kind, value in by_unit.get(u, ()):
            if kind in ("district", "tehsil", "state") and kind not in info:
                info[kind] = value.strip()
        unit_info[u] = info
    return unit_psn, unit_info, {"clusters": len(groups), "units": len(units), "fragments": frag}


def patient_for(fid, loc, locs, unit_psn, placed):
    """Patient value for one records.jsonl line: only claims that the exported record actually contains."""
    key = (fid, loc)
    pointer_style = any(l != "doc" and not l.startswith("row:") for l in locs)
    if loc == "doc" and pointer_style:
        vals = {unit_psn.get((fid, l)) for l in locs if l != "doc" and (fid, l) in placed}
        all_items = [l for l in locs if l != "doc"]
        if len(vals) == 1 and None not in vals and all(unit_psn.get((fid, l)) for l in all_items):
            return next(iter(vals))
        return None
    return unit_psn.get(key) if key in placed else None
