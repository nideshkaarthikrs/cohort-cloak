"""Loaders for the hand-written lexicons under data/lexicons/."""
from functools import lru_cache
from pathlib import Path

import yaml

LEX_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "lexicons"


@lru_cache(maxsize=None)
def header_roles() -> dict:
    """role -> list of normalised synonym phrases (file order is the priority order)."""
    from cloak.detect.columns import norm_header
    raw = yaml.safe_load((LEX_DIR / "header_roles.yaml").read_text(encoding="utf-8"))
    return {role: [norm_header(p) for p in phrases] for role, phrases in raw.items()}
