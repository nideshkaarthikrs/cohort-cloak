"""The privacy plan: per-group date shifts, cluster-consistent age bands, rare-dx and k-anonymity decisions."""
import hashlib
import hmac
from collections import defaultdict

from cloak.privacy import suppress
from cloak.privacy.ages import band_for


class Plan:
    def __init__(self, keys, policy, unit_group, group_shift, group_ages, group_level, code_level, unit_loc, group_loc):
        self.keys, self.policy = keys, policy
        self.unit_group = unit_group
        self.group_shift = group_shift
        self.group_ages = group_ages
        self.group_level = group_level
        self.code_level = code_level
        self.unit_loc = unit_loc
        self.group_loc = group_loc
        self.touched = set()      # units where something was generalised

    # ---- dates -----------------------------------------------------------------------------
    def shift(self, unit) -> int:
        return self.group_shift[self.unit_group[unit]]

    # ---- ages ------------------------------------------------------------------------------
    def band(self, unit, age: int) -> str:
        g = self.unit_group[unit]
        lv = self.group_level.get(g, 0)
        width = int(self.policy["age_band_years"]) * (1 if lv == 0 else 2 if lv == 1 else 4)
        ages = self.group_ages.get(g) or [age]
        return band_for(list(ages) + [age], width, int(self.policy["age_top_code"]))

    # ---- diagnoses ---------------------------------------------------------------------------
    def icd(self, unit, code: str):
        g = self.unit_group[unit]
        return suppress.apply_level(code, self.code_level.get(code, 0))

    # ---- location ----------------------------------------------------------------------------
    def place(self, unit, kind: str):
        """Raw place value for a unit (own record first, then the rest of its patient group)."""
        v = self.unit_loc.get(unit, {}).get(kind)
        if v:
            return v
        return self.group_loc.get(self.unit_group[unit], {}).get(kind)

    def location_level(self, unit) -> int:
        return self.group_level.get(self.unit_group[unit], 0)


def _unlinked_shift(keys, rel, rec, max_days):
    return keys.date_shift_days(f"unlinked|{rel}|{rec}", max_days)


def build(keys, policy, table, unit_psn, rels, unit_info) -> Plan:
    """table: sentinel table; unit_psn: {(fid, rec): PSN|None}; unit_info: {(fid, rec): dict(gender, district, ...raw)}."""
    max_days = int(policy["date_shift_max_days"])
    units = set(unit_psn) | {(t[0], t[1]) for t in table}
    unit_group, group_shift = {}, {}
    for u in sorted(units):
        psn = unit_psn.get(u)
        g = psn if psn else ("u", u[0], u[1])
        unit_group[u] = g
        if g not in group_shift:
            group_shift[g] = (keys.date_shift_days(psn, max_days) if psn else _unlinked_shift(keys, rels[u[0]], u[1], max_days))
    group_ages, group_codes = defaultdict(list), defaultdict(set)
    for fid, rec, kind, _fb, payload in table:
        g = unit_group[(fid, rec)]
        if kind == "age":
            group_ages[g].append(payload)
        elif kind == "icd":
            group_codes[g].add(payload)
    n_patients = len({g for g in unit_group.values() if isinstance(g, str)}) or 1  # linked patients (PSN groups)
    cap = int(policy["rare_dx_max_patients"])
    if cap > 0:  # "rare" scales with the cohort: a fixed 8 would blank most diagnoses of a 50-patient set
        cap = max(2, min(cap, int(float(policy.get("rare_dx_fraction", 0.05)) * n_patients)))
    code_level = suppress.rare_levels(group_codes, cap)
    # location facts per unit and per group
    unit_loc = {u: unit_info.get(u, {}) for u in units}
    group_loc = defaultdict(dict)
    for u in sorted(units):
        for k, v in unit_loc[u].items():
            if v:
                group_loc[unit_group[u]].setdefault(k, v)
    # k-anonymity over (gender, age band, district, generalised dx)
    infos = {}
    for g in sorted({unit_group[u] for u in units}, key=str):
        ages = group_ages.get(g)
        if not ages:
            continue
        codes = group_codes.get(g, set())
        dx = frozenset(suppress.apply_level(c, code_level.get(c, 0))[0] for c in codes)
        dxc = frozenset(suppress.apply_level(c, 2)[0] for c in codes)
        loc = group_loc.get(g, {})
        infos[g] = {"gender": loc.get("gender", ""), "age_min": min(ages), "district": (loc.get("district") or "").casefold(),
                    "dx": dx, "dx_chapter": dxc}
    group_level = suppress.escalate(infos, int(policy["k_min"]), int(policy.get("k_max_level", 3)))
    return Plan(keys, policy, unit_group, group_shift, group_ages, group_level, code_level, unit_loc, group_loc)
