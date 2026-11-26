"""Filename sanitising: drop ID/phone-shaped tokens from every path component."""
import re

_SEP = re.compile(r"([_\-. ()\[\]]+)")
_ALPHA_SHORT = re.compile(r"^[A-Za-z]{1,5}$")


def _flagged(tok: str) -> bool:
    if re.search(r"\d{5,}", tok):
        return True
    return bool(re.search(r"[A-Za-z]", tok) and len(re.findall(r"\d", tok)) >= 3)


def _idish(tok: str) -> bool:
    return tok.isdigit() or bool(_ALPHA_SHORT.match(tok) and tok.isupper())


def _clean_component(name: str) -> str:
    stem, dot, ext = name.rpartition(".")
    if not dot or not stem or len(ext) > 8 or _SEP.search(ext):
        stem, ext, dot = name, "", ""
    parts = _SEP.split(stem)  # token, sep, token, sep, ..., token
    toks, seps = parts[0::2], parts[1::2] + [""]
    flags = [_flagged(t) for t in toks]
    idish = [f or _idish(t) for f, t in zip(flags, toks)]
    out = []
    i = 0
    while i < len(toks):
        if not idish[i]:
            out.append(toks[i] + seps[i])
            i += 1
            continue
        j = i
        while j + 1 < len(toks) and idish[j + 1]:
            j += 1
        if any(flags[i:j + 1]):
            out.append("ID" + seps[j])
        else:
            out.extend(toks[k] + seps[k] for k in range(i, j + 1))
        i = j + 1
    return "".join(out) + dot + ext


def sanitize_path(rel: str) -> str:
    return "/".join(_clean_component(c) for c in rel.split("/"))


def sanitize_paths(rels) -> dict:
    """Map input path -> output path, unique and independent of the order of `rels`."""
    result = {}
    taken = set()
    for rel in sorted(rels):
        out = sanitize_path(rel)
        if out in taken:
            stem, dot, ext = out.rpartition(".")
            if not dot or "/" in ext:
                stem, ext, dot = out, "", ""
            n = 2
            while f"{stem}_{n}{dot}{ext}" in taken:
                n += 1
            out = f"{stem}_{n}{dot}{ext}"
        taken.add(out)
        result[rel] = out
    return result
