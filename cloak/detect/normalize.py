"""Detection shadow string: homoglyphs folded, zero-width removed, Indic digits to ASCII, diacritics stripped.

`normalize` returns (shadow, offsets) where offsets[i] is the index in the original of shadow char i.
"""
import re
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


_OCR_NUM = re.compile(r"(?<![A-Za-z0-9])(?=[0-9OolI]{4,}(?![A-Za-z0-9]))(?=(?:[^\d]*\d){3})[0-9OolI]+")
_OCR_DIGIT = str.maketrans("OolI", "0011")
# the tail of an ID typed with look-alike letters, after a capital prefix or a number and a separator
# (`PL/26/lOO4`, `QR::lOO5:M`, `RL-26-lOO2-OP`); needs at least one look-alike and 3+ characters
_OCR_TAIL = re.compile(
    r"(?:(?<=[A-Z][/\-:@._])|(?<=[A-Z][/\-:@._]{2})|(?<=\d[/\-:@._]))"
    r"(?<![A-Za-z0-9])(?=[0-9OolI]{3,}(?![A-Za-z0-9]))[0-9OolI]*[OolI][0-9OolI]*")


def _fix_scanned_digits(text: str) -> str:
    """Tokens that are mostly digits with O/l/I standing in for 0/1 (OCR) read as numbers; same length, so offsets hold."""
    text = _OCR_TAIL.sub(lambda m: m.group(0).translate(_OCR_DIGIT), text)
    if not _OCR_NUM.search(text):
        return text
    return _OCR_NUM.sub(lambda m: m.group(0).translate(_OCR_DIGIT) if sum(c.isdigit() for c in m.group(0)) * 2 >= len(m.group(0)) else m.group(0), text)


def normalize(text: str):
    shadow, offsets = [], []
    for i, ch in enumerate(text):
        for c in _fold_char(ch):
            shadow.append(c)
            offsets.append(i)
    return _fix_scanned_digits("".join(shadow)), offsets


def map_span(offsets, start: int, end: int, original_len: int):
    """Map a shadow span [start, end) to original offsets, covering any removed chars inside it."""
    if not offsets or start >= len(offsets):
        return original_len, original_len
    a = offsets[start]
    b = offsets[end - 1] + 1 if end - 1 < len(offsets) else original_len
    return a, b
