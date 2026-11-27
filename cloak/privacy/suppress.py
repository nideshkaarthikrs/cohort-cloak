"""Rare-value suppression and k-anonymity escalation (ICD-10 generalisation)."""
import re
from collections import Counter, defaultdict
from cloak.privacy.ages import band_for

ICD_RX = re.compile(r"(?<![A-Za-z0-9.\-])(?<!itamin )(?<!VIT )(?<!Vit )([A-TZ]\d{2}(?:\.\d{1,4})?)(?![A-Za-z0-9\-])")

CHAPTERS = [
    ("A00", "B99", "I", "Certain infectious and parasitic diseases"),
    ("C00", "D48", "II", "Neoplasms"),
    ("D50", "D89", "III", "Diseases of the blood and immune mechanism"),
    ("E00", "E90", "IV", "Endocrine, nutritional and metabolic diseases"),
    ("F00", "F99", "V", "Mental and behavioural disorders"),
    ("G00", "G99", "VI", "Diseases of the nervous system"),
    ("H00", "H59", "VII", "Diseases of the eye and adnexa"),
    ("H60", "H95", "VIII", "Diseases of the ear and mastoid process"),
    ("I00", "I99", "IX", "Diseases of the circulatory system"),
    ("J00", "J99", "X", "Diseases of the respiratory system"),
    ("K00", "K93", "XI", "Diseases of the digestive system"),
    ("L00", "L99", "XII", "Diseases of the skin and subcutaneous tissue"),
    ("M00", "M99", "XIII", "Diseases of the musculoskeletal system"),
    ("N00", "N99", "XIV", "Diseases of the genitourinary system"),
    ("O00", "O99", "XV", "Pregnancy, childbirth and the puerperium"),
    ("P00", "P96", "XVI", "Perinatal conditions"),
    ("Q00", "Q99", "XVII", "Congenital malformations"),
    ("R00", "R99", "XVIII", "Symptoms, signs and abnormal findings"),
    ("S00", "T98", "XIX", "Injury, poisoning and external causes"),
    ("V01", "Y98", "XX", "External causes of morbidity"),
    ("Z00", "Z99", "XXI", "Factors influencing health status"),
    ("U00", "U99", "XXII", "Codes for special purposes"),
]


def category(code: str) -> str:
    return code.split(".")[0].upper()


def chapter(code: str):
    """(range label, title) for an ICD-10 code."""
    c = category(code)
    for lo, hi, _num, title in CHAPTERS:
        if lo <= c <= hi:
            return f"{lo}-{hi}", title
    return "", "Other conditions"


def rare_levels(group_codes: dict, rare_max: int) -> dict:
    """group_codes: group -> set of full codes. Returns code -> level (0 keep, 1 category, 2 chapter)."""
    if rare_max <= 0:
        return {}
    per_code = Counter()
    per_cat = Counter()
    for codes in group_codes.values():
        for c in codes:
            per_code[c] += 1
        for cat in {category(c) for c in codes}:
            per_cat[cat] += 1
    levels = {}
    for c, n in per_code.items():
        if n <= rare_max:
            levels[c] = 2 if per_cat[category(c)] <= rare_max else 1
    return levels


def apply_level(code: str, level: int):
    """Return (code_text, display_text or None meaning 'keep the original display')."""
    if level <= 0:
        return code, None
    if level == 1:
        return category(code), chapter(code)[1]
    rng, title = chapter(code)
    return rng or category(code), title


def escalate(groups: dict, k_min: int, max_level: int = 3, base_width: int = 5, top: int = 85) -> dict:
    """groups: id -> dict(gender, age_min, district, dx: frozenset of generalised dx labels).
    k is measured over the quasi-identifiers a registry attacker holds (gender, age band, district); diagnoses are
    protected separately by rare-value suppression. Returns id -> escalation level (0..max_level): 1/2 widen the age
    band (x2, x4), 3 replaces the district (and PIN prefix, tehsil) by the state."""
    level = {g: 0 for g in groups}
    if k_min <= 1:
        return level

    def cell(g):
        info, lv = groups[g], level[g]
        width = base_width * (1 if lv == 0 else 2 if lv == 1 else 4)
        ages = info.get("ages") or [info["age_min"]]
        band = band_for(ages, width, top) if ages[0] is not None else None
        district = info.get("state", "[DISTRICT]") if lv >= 3 else info["district"]
        return (info["gender"], band, district)

    for _ in range(max_level):
        counts = Counter(cell(g) for g in groups)
        low = [g for g in sorted(groups, key=str) if counts[cell(g)] < k_min and level[g] < max_level]
        if not low:
            break
        for g in low:
            level[g] += 1
    return level


_PROC_FAMILIES = (("ectomy", "Excision procedure"), ("otomy", "Incision procedure"), ("ostomy", "Incision procedure"),
                  ("plasty", "Reconstructive procedure"), ("scopy", "Endoscopic procedure"),
                  ("graphy", "Imaging procedure"), ("repair", "Repair procedure"), ("transplant", "Transplant procedure"),
                  ("replacement", "Replacement procedure"), ("biopsy", "Biopsy procedure"))


def procedure_label(text: str) -> str:
    """Generic family for a rare procedure name; suffix rules only, no procedure list."""
    t = text.casefold()
    for suffix, label in _PROC_FAMILIES:
        if suffix in t:
            return label
    return "Surgical procedure"


def package_prefix(code: str):
    m = re.match(r"^([A-Za-z]{2,4})(?=\d)", code.strip())
    return m.group(1) if m else None
