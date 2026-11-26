"""Pseudonym insertion: resolve placement sentinels once clusters are known."""
import re
from collections import defaultdict

_SENTINEL = re.compile(r"(\n?)@@PSN(\d+)@@")


def resolve(table: list, unit_psn: dict):
    """table: [(fid, rec, kind, fallback)]. Returns (replacements, placed_units).

    Per record: the first patient-name placement becomes the PSN (others keep their `[NAME]`); with no name
    placement the first MRN/UHID placement does; with neither, an appended `Patient:` line carries it.
    A record that is not linked keeps every fallback placeholder, and appended lines vanish.
    """
    groups = defaultdict(list)
    for idx, (fid, rec, _kind, _fb) in enumerate(table):
        groups[(fid, rec)].append(idx)
    repl = [None] * len(table)
    placed = set()
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
            kind, fallback = table[i][2], table[i][3]
            if i == target:
                repl[i] = f"Patient: {psn}" if kind == "append" else psn
                placed.add(key)
            else:
                repl[i] = None if kind == "append" else fallback
    return repl, placed


def substitute(text: str, repl: list) -> str:
    def one(m):
        r = repl[int(m.group(2))]
        return "" if r is None else m.group(1) + r
    return _SENTINEL.sub(one, text)
