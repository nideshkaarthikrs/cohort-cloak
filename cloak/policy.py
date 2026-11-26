"""Policy loader: config/policy.yaml over built-in defaults."""
from pathlib import Path

import yaml

DEFAULTS = {
    "date_shift_max_days": 180, "age_band_years": 5, "age_top_code": 85, "dob_mode": "shift",
    "village_mode": "district", "tehsil_mode": "keep", "pin_mode": "prefix3",
    "rare_dx_max_patients": 8, "rare_dx_fraction": 0.05, "k_min": 5, "k_max_level": 3, "link_threshold": 10, "soft_link_margin": 3,
    "name_confidence_threshold": 0.6, "max_json_depth": 200,
}


def load_policy(path: Path) -> dict:
    policy = dict(DEFAULTS)
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        data = {}
    if isinstance(data, dict):
        for k in sorted(data):
            if k in DEFAULTS:
                policy[k] = data[k]
    return policy
