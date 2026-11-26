"""Detection shadow string: homoglyphs folded, zero-width removed, Indic digits to ASCII, diacritics stripped.

`normalize` returns (shadow, offsets) where offsets[i] is the index in the original of shadow char i.
"""
import unicodedata

from cloak.detect.validators import ascii_digits

_ZERO_WIDTH = {"​", "‌", "‍", "⁠", "﻿", "­", "‎", "‏", "⁢", "⁣"}
_HOMO = {}
for _pair in ("аa еe оo рp сc хx уy іi јj ԁd ԛq ѕs һh кk ӏl ΑA ΒB ΕE ΖZ ΗH ΙI ΚK ΜM ΝN ΟO ΡP ΤT ΥY ΧX αa οo ρp νv ιi κk "
              "АA ВB ЕE КK МM НH ОO РP СC ТT УY ХX").split():
    _HOMO[_pair[0]] = _pair[1]


def _fold_char(ch: str) -> str:
    if ch in _ZERO_WIDTH:
        return ""
    if ch in _HOMO:
        return _HOMO[ch]
    if ord(ch) < 128:
        return ch
    d = unicodedata.normalize("NFKD", ch)
    base = d[0]
    if "A" <= base <= "z" and all(unicodedata.category(c) == "Mn" for c in d[1:]):
        return base  # Latin letter with diacritics
    out = unicodedata.normalize("NFKC", ascii_digits(ch))
    return "".join(_HOMO.get(c, c) for c in out)


def normalize(text: str):
    shadow, offsets = [], []
    for i, ch in enumerate(text):
        for c in _fold_char(ch):
            shadow.append(c)
            offsets.append(i)
    return "".join(shadow), offsets


def map_span(offsets, start: int, end: int, original_len: int):
    """Map a shadow span [start, end) to original offsets, covering any removed chars inside it."""
    if not offsets or start >= len(offsets):
        return original_len, original_len
    a = offsets[start]
    b = offsets[end - 1] + 1 if end - 1 < len(offsets) else original_len
    return a, b
