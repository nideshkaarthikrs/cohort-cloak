"""Shared small data types."""
from dataclasses import dataclass


@dataclass(frozen=True, order=True)
class Span:
    start: int
    end: int
    kind: str          # e.g. PHONE, AADHAAR, ID, DOSE (guards use their own kinds)
    conf: float = 1.0
