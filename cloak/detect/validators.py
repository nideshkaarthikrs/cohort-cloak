"""Small validators and digit folding shared by the detectors."""
import re

# Indic digit blocks: Devanagari, Bengali, Gurmukhi, Gujarati, Oriya, Tamil, Telugu, Kannada, Malayalam, Arabic-Indic
_DIGIT_BLOCKS = (0x0966, 0x09E6, 0x0A66, 0x0AE6, 0x0B66, 0x0BE6, 0x0C66, 0x0CE6, 0x0D66, 0x06F0, 0x0660)
_TRANS = {base + i: ord("0") + i for base in _DIGIT_BLOCKS for i in range(10)}


def ascii_digits(s: str) -> str:
    """Fold Indic digits to ASCII. Length-preserving, so offsets stay valid."""
    return s.translate(_TRANS)


def phone_core(s: str):
    """Return the 10-digit Indian mobile/landline core of a candidate string, or None."""
    d = re.sub(r"\D", "", ascii_digits(s))
    if len(d) == 13 and d.startswith("0091"):
        d = d[3:]
    if len(d) == 12 and d.startswith("91"):
        d = d[2:]
    elif len(d) == 11 and d.startswith("0"):
        d = d[1:]
    if len(d) == 10 and d[0] in "6789":
        return d
    return None


_D = [[0, 1, 2, 3, 4, 5, 6, 7, 8, 9], [1, 2, 3, 4, 0, 6, 7, 8, 9, 5], [2, 3, 4, 0, 1, 7, 8, 9, 5, 6],
      [3, 4, 0, 1, 2, 8, 9, 5, 6, 7], [4, 0, 1, 2, 3, 9, 5, 6, 7, 8], [5, 9, 8, 7, 6, 0, 4, 3, 2, 1],
      [6, 5, 9, 8, 7, 1, 0, 4, 3, 2], [7, 6, 5, 9, 8, 2, 1, 0, 4, 3], [8, 7, 6, 5, 9, 3, 2, 1, 0, 4],
      [9, 8, 7, 6, 5, 4, 3, 2, 1, 0]]
_P = [[0, 1, 2, 3, 4, 5, 6, 7, 8, 9], [1, 5, 7, 6, 2, 8, 3, 0, 9, 4], [5, 8, 0, 3, 7, 9, 6, 1, 4, 2],
      [8, 9, 1, 6, 0, 4, 3, 5, 2, 7], [9, 4, 5, 3, 1, 2, 6, 8, 7, 0], [4, 2, 8, 6, 5, 7, 3, 9, 0, 1],
      [2, 7, 9, 3, 8, 0, 6, 4, 1, 5], [7, 0, 4, 6, 9, 1, 3, 2, 5, 8]]


def verhoeff_ok(number: str) -> bool:
    """Verhoeff checksum. Used as a confidence boost only (synthetic Aadhaars may not pass)."""
    c = 0
    for i, ch in enumerate(reversed(re.sub(r"\D", "", ascii_digits(number)))):
        c = _D[c][_P[i % 8][int(ch)]]
    return c == 0
