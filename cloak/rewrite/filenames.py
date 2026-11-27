"""Filename sanitising: drop ID/phone-shaped tokens and known names from every path component."""
import re

from cloak.detect.lexicon import medical_words, words

_SEP = re.compile(r"([_\-. ()\[\]]+)")
_ALPHA_SHORT = re.compile(r"^[A-Za-z]{1,5}$")


def _flagged(tok: str) -> bool:
    if re.search(r"\d{5,}", tok):
        return True
    return bool(re.search(r"[A-Za-z]", tok) and re.search(r"\d{3,}", tok))


def _idish(tok: str) -> bool:
    return tok.isdigit() or bool(_ALPHA_SHORT.match(tok) and tok.isupper())


_FILE_WORDS = words("filename_words.txt")
_CHAT_WORDS = frozenset(("chat", "chats", "conversation", "messages", "message", "thread"))


def _name_like(tok: str) -> bool:
    return bool(re.fullmatch(r"[A-Z][a-z]{2,}", tok)) and tok.casefold() not in _FILE_WORDS and tok.casefold() not in medical_words()


def _clean_component(name: str, names=None, ids=None) -> str:
    stem, dot, ext = name.rpartition(".")
    if not dot or not stem or len(ext) > 8 or _SEP.search(ext):
        stem, ext, dot = name, "", ""
    # Match complete known/induced ID spans before punctuation splits their pieces.
    if ids is not None:
        merged = []
        for start, end in ids.find(stem):
            if merged and start < merged[-1][1]:
                merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
            else:
                merged.append((start, end))
        for start, end in reversed(merged):
            stem = stem[:start] + "~ID~" + stem[end:]
    parts = _SEP.split(stem)  # token, sep, token, sep, ..., token
    toks, seps = parts[0::2], parts[1::2] + [""]
    is_name = [bool(names is not None and len(t) >= 2 and names.has_token(t)) for t in toks]
    for i, t in enumerate(toks):  # a chat export is named after the person: "WhatsApp Chat with <Name>"
        if t.casefold() == "with" and i >= 1 and toks[i - 1].casefold() in _CHAT_WORDS:
            k = i + 1
            while k < len(toks) and k - i <= 3 and (is_name[k] or _name_like(toks[k]) or re.fullmatch(r"[A-Z]{2,}", toks[k])):
                is_name[k] = True
                k += 1
    flags = [(not is_name[i]) and (t == "~ID~" or _flagged(t) or bool(ids is not None and ids.has_token(t))) for i, t in enumerate(toks)]
    idish = [(not is_name[i]) and (flags[i] or _idish(t)) for i, t in enumerate(toks)]
    # fail closed: capitalised unknown words hugging an ID/phone run are probably the patient's name
    i = 0
    while i < len(toks):
        if not idish[i]:
            i += 1
            continue
        j = i
        while j + 1 < len(toks) and idish[j + 1]:
            j += 1
        if any(flags[i:j + 1]):
            k = i - 1
            while k >= 0 and i - k <= 4 and (is_name[k] or _name_like(toks[k])):
                is_name[k], idish[k] = True, False
                k -= 1
            k = j + 1
            while k < len(toks) and k - j <= 3 and (is_name[k] or _name_like(toks[k])):
                is_name[k], idish[k] = True, False
                k += 1
        i = j + 1
    out = []
    i = 0
    while i < len(toks):
        if is_name[i]:
            j = i
            while j + 1 < len(toks) and is_name[j + 1]:
                j += 1
            out.append("NAME" + seps[j])
            i = j + 1
        elif idish[i]:
            j = i
            while j + 1 < len(toks) and idish[j + 1]:
                j += 1
            run_text = "".join(toks[k] + (seps[k] if k < j else "") for k in range(i, j + 1))
            if any(flags[i:j + 1]) or (ids is not None and ids.find(run_text)):
                out.append("ID" + seps[j])
            else:
                out.extend(toks[k] + seps[k] for k in range(i, j + 1))
            i = j + 1
        else:
            out.append(toks[i] + seps[i])
            i += 1
    return "".join(out) + dot + ext


def sanitize_path(rel: str, names=None, ids=None) -> str:
    return "/".join(_clean_component(c, names, ids) for c in rel.split("/"))


def sanitize_paths(rels, names=None, ids=None) -> dict:
    """Map input path -> output path, unique and independent of the order of `rels`."""
    result = {}
    taken = set()
    for rel in sorted(rels):
        out = sanitize_path(rel, names, ids)
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
