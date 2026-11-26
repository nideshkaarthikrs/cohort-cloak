#!/usr/bin/env python3
"""Score a pipeline run on the stress set: critical-ID leaks, name leaks, canaries, medical preservation."""
import argparse
import base64
import binascii
import hashlib
import html
import json
import re
import sys
from pathlib import Path
from urllib.parse import unquote

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from cloak.detect.normalize import normalize  # noqa: E402

_B64 = re.compile(r"[A-Za-z0-9+/]{24,}={0,2}")


def fold(text: str) -> str:
    shadow, _ = normalize(text)
    return " ".join(shadow.casefold().split())


def expand(text: str) -> str:
    """Original text plus every decodable hidden layer (base64, %-encoding, \\u escapes, HTML entities)."""
    parts = [text]
    for m in _B64.finditer(text):
        tok = m.group(0)
        try:
            parts.append(base64.b64decode(tok + "=" * (-len(tok) % 4)).decode("utf-8", errors="ignore"))
        except (binascii.Error, ValueError):
            pass
    parts.append(unquote(text))
    parts.append(re.sub(r"\\u([0-9a-fA-F]{4})", lambda m: chr(int(m.group(1), 16)), text))
    parts.append(html.unescape(text))
    return "\n".join(parts)


def digits_hit(core: str, text: str) -> bool:
    return bool(re.search(r"(?<!\d)" + r"[\W_]{0,2}".join(core) + r"(?!\d)", text))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--truth", required=True)
    a = ap.parse_args()
    inp, out = Path(a.input), Path(a.output)
    truth = json.loads(Path(a.truth).read_text(encoding="utf-8"))
    report = json.loads((out / "report.json").read_text(encoding="utf-8"))
    mapped = {e["input_sha256"]: (e.get("output"), e.get("reason")) for e in report["files"]}
    ids_total = ids_leak = names_total = names_full = names_tok = 0
    kept = pres_total = 0
    reasons = {}
    leaks = []
    per_file_text = {}
    for rel, meta in truth["files"].items():
        sha = hashlib.sha256((inp / rel).read_bytes()).hexdigest()
        o, reason = mapped.get(sha, (None, "missing"))
        if not o:
            reasons[reason] = reasons.get(reason, 0) + 1
            per_file_text[rel] = ""
            continue
        path = out / o
        text = fold(expand(path.read_bytes().decode("utf-8", errors="replace")) + "\n" + path.name)
        per_file_text[rel] = text
        for ident in meta["ids"]:
            core = re.sub(r"\D", "", ident)
            ids_total += 1
            hit = digits_hit(core, text) if len(core) >= 6 else fold(ident) in text
            ids_leak += hit
            if hit and len(leaks) < 60:
                leaks.append(("id", rel, ident))
        for name in meta["names"]:
            names_total += 1
            f = fold(name)
            full = f in text
            tok = any(re.search(r"(?<![a-z])" + re.escape(t) + r"(?![a-z])", text) for t in f.split() if len(t) >= 4)
            names_full += full
            names_tok += tok
            if tok and len(leaks) < 60:
                leaks.append(("name", rel, name))
    missing = []
    for pv in truth["preserve"]:
        pres_total += 1
        ok = fold(pv["text"]) in per_file_text.get(pv["file"], "")
        kept += ok
        if not ok and len(missing) < 5:
            missing.append((pv["file"], pv["text"]))
    blob = ""
    for p in sorted(out.rglob("*")):
        if p.is_file():
            blob += fold(expand(p.read_bytes().decode("utf-8", errors="replace"))) + " " + fold(p.name) + "\n"
    canaries = sorted(set(truth["canaries"]))
    can_hit = sum(1 for c in canaries if (digits_hit(c, blob) if c.isdigit() else fold(c) in blob))
    print(f"stress: critical IDs leaked {ids_leak}/{ids_total} ({100 * ids_leak / max(1, ids_total):.1f}%)")
    print(f"        names leaked: full {names_full}/{names_total} ({100 * names_full / max(1, names_total):.1f}%), "
          f"any >=4-letter token {names_tok}/{names_total} ({100 * names_tok / max(1, names_total):.1f}%)")
    print(f"        canaries {can_hit}/{len(canaries)}; medical/clean probes kept {kept}/{pres_total} ({100 * kept / max(1, pres_total):.1f}%)")
    print(f"        quarantine reasons: {dict(sorted(reasons.items(), key=str))}")
    for m in missing:
        print("   LOST", m)
    for kind, rel, v in leaks:
        print("   LEAK", kind, rel, v)
    print(f"STRESS ids={ids_leak / max(1, ids_total):.4f} names_full={names_full / max(1, names_total):.4f} "
          f"names_tok={names_tok / max(1, names_total):.4f} canaries={can_hit} medical={kept / max(1, pres_total):.4f}")
    return 1 if can_hit else 0


if __name__ == "__main__":
    sys.exit(main())
