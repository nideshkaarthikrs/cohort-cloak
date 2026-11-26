"""Record locators (the truth's granularity): row:N for CSV/TSV, JSON pointers, or doc."""
import csv
import io
import re

_IDENTITY_KEYS = {
    "name", "fullname", "naam", "patientname", "ptname", "uhid", "patientref", "patientid", "mrn",
    "mobile", "mobileno", "phone", "phoneno", "contact", "aadhaar", "aadhar", "aadharno", "aadhaarno",
    "abha", "hospitaluhid", "regno", "registrationno",
}


def _norm_key(k: str) -> str:
    return re.sub(r"[^a-z0-9]", "", k.lower())


def _identity_key(k: str) -> bool:
    n = _norm_key(k)
    return n in _IDENTITY_KEYS or n.startswith("patient") or n.endswith("uhid")


def _has_identity(obj) -> bool:
    if not isinstance(obj, dict):
        return False
    for k, v in obj.items():
        if _identity_key(k):
            return True
        if "patient" in k.lower() and isinstance(v, dict) and any(_identity_key(x) for x in v):
            return True
    return False


def _pointer(key: str) -> str:
    return key.replace("~", "~0").replace("/", "~1")


def json_locs(data, fhir: bool) -> list:
    if fhir:
        return ["doc"]
    if isinstance(data, dict):
        if _has_identity(data):
            return ["doc"]
        locs = []
        for k, v in data.items():
            if isinstance(v, list) and v and all(isinstance(x, dict) for x in v) and any(_has_identity(x) for x in v):
                locs.extend(f"/{_pointer(k)}/{i}" for i in range(len(v)))
        return locs + ["doc"] if locs else ["doc"]
    if isinstance(data, list) and data and all(isinstance(x, dict) for x in data) and any(_has_identity(x) for x in data):
        return [f"/{i}" for i in range(len(data))] + ["doc"]
    return ["doc"]


def csv_rows(text: str, delimiter: str) -> list:
    return list(csv.reader(io.StringIO(text, newline=""), delimiter=delimiter))
