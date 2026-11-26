"""Cluster key and PSN assignment (HMAC, collision-safe, independent of input order)."""


def cluster_key(members: list) -> str:
    """min(sorted strong IDs) else min(name key | dob). Deterministic under reordering."""
    ids = sorted(f"{k}:{v}" for ev in members for k in ("aadhaar", "abha", "mrn") for v in ev.ids.get(k, ()))
    if ids:
        return ids[0]
    other = sorted(f"{k}:{v}" for ev in members for k in sorted(ev.ids) for v in ev.ids[k])
    if other:
        return other[0]
    parts = sorted("|".join(sorted(ev.tokens)) + "|" + ",".join(sorted(ev.dob_raw)) for ev in members)
    return "name:" + parts[0]


def assign(keys, clusters: dict) -> dict:
    """clusters: root -> list of Evidence. Returns root -> PSN."""
    items = sorted((cluster_key(m), root) for root, m in clusters.items())
    used, out = {}, {}
    for key, root in items:
        n = 0
        while True:
            psn = keys.pseudonym(key if n == 0 else f"{key}|{n}")
            if psn not in used:
                break
            n += 1
        used[psn] = root
        out[root] = psn
    return out

