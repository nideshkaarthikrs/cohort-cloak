"""Constrained clustering: strongest edges first, cannot-link respected, ambiguous soft links refused."""
from collections import defaultdict

from cloak.link.blocking import candidate_pairs
from cloak.link.evidence import is_fragment
from cloak.link.score import STRONG_KINDS, W_DEMOTED, cannot_link, name_conflict, name_relation, score


def demoted_ids(evs: list) -> set:
    """IDs/phones shared by records whose names or genders are incompatible (households, attendants)."""
    owners = defaultdict(list)
    for i, ev in enumerate(evs):
        for kind in STRONG_KINDS:
            for v in ev.ids.get(kind, ()):
                owners[(kind, v)].append(i)
        for p in ev.phones:
            owners[("phone", p)].append(i)
    out = set()
    for key, idx in owners.items():
        if len(idx) < 2 or len(idx) > 400:
            continue
        bad = False
        for a in range(len(idx)):
            for b in range(a + 1, len(idx)):
                ea, eb = evs[idx[a]], evs[idx[b]]
                if name_conflict(ea, eb) or (ea.gender and eb.gender and ea.gender != eb.gender):
                    bad = True
                    break
            if bad:
                break
        if bad:
            out.add(key)
    return out


class _UF:
    def __init__(self, n):
        self.p = list(range(n))
        self.members = {i: [i] for i in range(n)}

    def find(self, x):
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]
            x = self.p[x]
        return x

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return
        if len(self.members[ra]) < len(self.members[rb]):
            ra, rb = rb, ra
        self.p[rb] = ra
        self.members[ra].extend(self.members.pop(rb))


def cluster(evs: list, threshold: int = 10, margin: int = 3):
    """Return list of cluster ids (root index) per record, or None for records that are not clusterable.

    Fragments (prose-only) are resolved afterwards by `assign_fragments`.
    """
    n = len(evs)
    eligible = [ev.has_identity and not is_fragment(ev) for ev in evs]
    demoted = demoted_ids(evs)
    edges = []
    best = defaultdict(list)  # record -> [(weight, other)]
    for i, j in candidate_pairs(evs):
        if not (eligible[i] and eligible[j]):
            continue
        if cannot_link(evs[i], evs[j]):
            continue
        w, hard = score(evs[i], evs[j], demoted)
        if w >= threshold:
            edges.append((-w, i, j, hard))
            best[i].append((w, j))
            best[j].append((w, i))
    edges.sort()
    uf = _UF(n)
    for negw, i, j, hard in edges:
        w = -negw
        ri, rj = uf.find(i), uf.find(j)
        if ri == rj:
            continue
        mi, mj = uf.members[ri], uf.members[rj]
        if any(cannot_link(evs[a], evs[b]) for a in mi for b in mj):
            continue
        if not hard:
            # soft edge: each record must prefer this cluster over the runner-up by `margin`
            ok = True
            for rec, own, other in ((i, ri, rj), (j, rj, ri)):
                # ambiguous only if a rival cluster scores nearly as well AND cannot be the same person as `other`
                for ww, o in best[rec]:
                    ro = uf.find(o)
                    if ro in (own, other) or w - ww >= margin:
                        continue
                    if any(cannot_link(evs[a], evs[b]) for a in uf.members[ro] for b in uf.members[other]):
                        ok = False
                        break
                if not ok:
                    break
            if not ok:
                continue
        uf.union(i, j)
    return [uf.find(i) if eligible[i] else None for i in range(n)], uf


def assign_fragments(evs: list, roots: list, uf) -> list:
    """A prose fragment joins a cluster only if exactly one cluster matches its given name AND its relative."""
    out = list(roots)
    cluster_names = defaultdict(set)
    cluster_rels = defaultdict(set)
    for i, r in enumerate(roots):
        if r is not None:
            cluster_names[r] |= set(evs[i].tokens)
            cluster_rels[r] |= set(evs[i].rel_tokens)
    for i, ev in enumerate(evs):
        if roots[i] is not None or not is_fragment(ev) or not ev.wrel_tokens:
            continue
        hits = []
        for r in sorted(cluster_names):
            if (name_relation(ev.wtokens, frozenset(cluster_names[r])) in ("full", "compat")
                    and name_relation(ev.wrel_tokens, frozenset(cluster_rels[r])) in ("full", "compat")):
                hits.append(r)
        if len(hits) == 1:
            out[i] = hits[0]
    return out
