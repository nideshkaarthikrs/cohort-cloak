import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def run_main(inp: Path, out: Path, secret: str = "unit-test-secret", policy: dict = None):
    env = dict(os.environ)
    env["RAKSHA_SECRET"] = secret
    if policy is not None:
        pol = out.parent / (out.name + "_policy.yaml")
        pol.write_text("\n".join(f"{k}: {v}" for k, v in policy.items()) + "\n", encoding="utf-8")
        env["COHORT_POLICY"] = str(pol)
    return subprocess.run(
        [sys.executable, str(ROOT / "main.py"), "--input", str(inp), "--output", str(out)],
        capture_output=True, text=True, env=env, cwd=str(ROOT),
    )


@pytest.fixture
def runner():
    return run_main


def report_of(out: Path) -> dict:
    return json.loads((out / "report.json").read_text(encoding="utf-8"))


def entry_for(report: dict, data: bytes) -> dict:
    import hashlib
    sha = hashlib.sha256(data).hexdigest()
    return next(e for e in report["files"] if e["input_sha256"] == sha)
