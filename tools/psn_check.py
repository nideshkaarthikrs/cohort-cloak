#!/usr/bin/env python3
"""Every non-null patient in records.jsonl must appear inside its exported file (consistency)."""
import argparse
import json
from pathlib import Path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", required=True)
    a = ap.parse_args()
    out = Path(a.output)
    claims = bad = 0
    cache = {}
    for line in (out / "records.jsonl").read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        if r["patient"]:
            claims += 1
            text = cache.setdefault(r["file"], (out / r["file"]).read_text(encoding="utf-8"))
            bad += r["patient"] not in text
    print(f"psn claims {claims}, not present in exported file: {bad}")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
