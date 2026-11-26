#!/usr/bin/env python3
"""Scan the output folder (+ optional extra files/dirs) for canaries and critical identifiers.

Reads the truth for CANARY surfaces and `critical` entity surfaces. Prints counts only.
Exit 1 if any canary is found.
"""
import argparse
import base64
import binascii
import json
import os
import re
import sys
import unicodedata
from pathlib import Path

_B64 = re.compile(r"[A-Za-z0-9+/]{24,}={0,2}")


def norm(s):
    return " ".join(unicodedata.normalize("NFKC", s).casefold().split())


def digits(s):
    return re.sub(r"\D", "", s)


def blob_of(path: Path) -> str:
    parts = []
    paths = [path] if path.is_file() else [Path(dp) / n for dp, _, fn in os.walk(path) for n in sorted(fn)]
    for p in paths:
        parts.append(p.name)
        try:
            text = p.read_bytes().decode("utf-8", errors="replace")
        except OSError:
            continue
        parts.append(text)
        for m in _B64.finditer(text):
            tok = m.group(0)
            try:
                parts.append(base64.b64decode(tok + "=" * (-len(tok) % 4)).decode("utf-8", errors="ignore"))
            except (binascii.Error, ValueError):
                pass
    return "\n".join(parts)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", required=True)
    ap.add_argument("--truth", required=True)
    ap.add_argument("--extra", nargs="*", default=[], help="more files or dirs (stdout capture, TMPDIR...)")
    a = ap.parse_args()
    truth = json.loads(Path(a.truth).read_text(encoding="utf-8"))
    canaries, critical = set(), set()
    for f in truth["files"].values():
        for u in f["units"].values():
            for e in u["entities"]:
                if e.get("type") == "CANARY":
                    canaries.add(norm(e["surface"]))
                elif e.get("critical"):
                    critical.add(e["surface"])
    text = norm("\n".join([blob_of(Path(a.output))] + [blob_of(Path(x)) for x in a.extra if Path(x).exists()]))
    dtext = digits(text)
    hit_c = sum(1 for c in canaries if c and c in text)
    hit_k = 0
    for s in critical:
        d = digits(s)
        if len(d) >= 6:
            hit_k += d in dtext
        elif norm(s) and norm(s) in text:
            hit_k += 1
    print(f"canaries {hit_c}/{len(canaries)} critical_ids {hit_k}/{len(critical)}")
    return 1 if hit_c else 0


if __name__ == "__main__":
    sys.exit(main())
