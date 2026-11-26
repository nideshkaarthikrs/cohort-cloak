"""Address rewriting: segment on commas; houses, landmarks, localities and villages become typed placeholders."""
import re

from cloak.detect.validators import ascii_digits

_PIN_TAIL = re.compile(r"\s*[-–,]?\s*(\d{6})\s*$")
_KEEP = re.compile(r"^(?:tehsil|tahsil|taluka|distt?\.?|district|state|block|तहसील|जिला|ज़िला|राज्य)(?=[\s.:\-]|$)", re.I)
_HOUSE = re.compile(r"^(?:h\.?\s*no\.?|house|makan|flat|plot|मकान|भवन|घर)", re.I)
_LANDMARK = re.compile(r"^(?:near|opp\.?|opposite|behind|beside|next\s+to)\b|(?:के\s+पास|के\s+पीछे|के\s+सामने|के\s+बगल)\s*$", re.I)
_VILLAGE = re.compile(r"^(?:vill?\.?|village|gram|gaon|ग्राम|गाँव|गांव|पो\.?)\b", re.I)
_LOCALITY = re.compile(r"^(?:mohalla|mohalle|muhalla|colony|ward\s*(?:no\.?\s*)?\d+|nagar|sector|मोहल्ला|कॉलोनी|वार्ड)(?=[\s.:\-\d]|$)", re.I)


def _pin_replacement(pin: str, mode: str) -> str:
    return "[PIN]" if mode == "redact" else pin[:3] + "***"


def rewrite_address(text: str, pin_mode: str = "prefix3", sentinel=None):
    """Return (rewritten, number_of_replacements). `sentinel(kind, original, payload)` defers tehsil/district/PIN
    choices to the privacy plan (None: keep tehsil/district, PIN by `pin_mode`)."""
    n = 0
    folded = ascii_digits(text)
    pin = ""
    m = _PIN_TAIL.search(folded)
    body = text
    if m:
        pin = m.group(1)
        body = text[:m.start()]
        n += 1
    else:
        # a PIN may sit inside the last segment, not only at the very end
        m2 = re.search(r"(?<!\d)(\d{6})(?!\d)", folded)
        if m2:
            pin = m2.group(1)
            body = text[:m2.start()].rstrip(" -–,") + text[m2.end():]
            n += 1
    out = []
    for seg in body.split(","):
        s = seg.strip()
        if not s:
            continue
        if _KEEP.match(s):
            if sentinel is not None and re.match(r"(?i)(?:tehsil|tahsil|taluka|तहसील)", s):
                out.append(sentinel("tehsil_seg", s, None))
            elif sentinel is not None and re.match(r"(?i)(?:distt?\.?|district|जिला|ज़िला)", s):
                out.append(sentinel("district_seg", s, None))
            else:
                out.append(s)
            continue
        if _LANDMARK.search(s):
            out.append("[LOCALITY]")
        elif _HOUSE.match(s):
            out.append("[HOUSE]")
        elif _VILLAGE.match(s):
            out.append("[VILLAGE]")
        elif _LOCALITY.match(s):
            out.append("[LOCALITY]")
        else:
            out.append("[ADDRESS]")
        n += 1
    res = ", ".join(out)
    if pin:
        pin_text = sentinel("pin", _pin_replacement(pin, pin_mode), pin) if sentinel is not None else _pin_replacement(pin, pin_mode)
        res = (res + " - " if res else "") + pin_text
    return res, n
