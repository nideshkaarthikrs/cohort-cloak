"""Orchestration: ingest -> (redact) -> write, with a global exception guard."""
import argparse
import csv
import hashlib
import io
import json
import os
import shutil
import sys
import time
import traceback
from pathlib import Path

from cloak.errors import Quarantine, reason_for
from cloak.ingest.records import csv_rows, json_locs
from cloak.ingest.sniff import parse
from cloak.keys import Keys
from cloak.log import RunLog
from cloak.policy import load_policy
from cloak.report import build_report, write_records, write_report
from cloak.detect.engine import Scrubber
from cloak.rewrite.filenames import sanitize_paths
from cloak.rewrite.structured import transform_csv, transform_json, transform_text

ROOT = Path(__file__).resolve().parent.parent


def _excepthook(etype, _value, tb):
    """Type and file:line frames only; the exception message may embed record content."""
    frames = [f"{Path(f.filename).name}:{f.lineno}" for f in traceback.extract_tb(tb)]
    sys.stderr.write(f"fatal {etype.__name__} at {' > '.join(frames[-6:])}\n")


def _render(p, scrubber):
    """Return (output_bytes, redaction_count) for a parsed file."""
    if p.kind in ("json", "fhir"):
        out, n = transform_json(p.data, scrubber)
        return (json.dumps(out, ensure_ascii=False, indent=2) + "\n").encode("utf-8"), n
    if p.kind == "csv":
        rows = csv_rows(p.text, p.delimiter)
        if not rows:
            raise Quarantine("empty_file")
        nh, nb, n = transform_csv(rows[0], rows[1:], scrubber)
        buf = io.StringIO()
        w = csv.writer(buf, delimiter=p.delimiter, lineterminator="\n")
        w.writerow(nh)
        w.writerows(nb)
        return buf.getvalue().encode("utf-8"), n
    out, n = transform_text(p.text, scrubber)
    return out.encode("utf-8"), n


def _locs(p):
    if p.kind in ("json", "fhir"):
        return json_locs(p.data, p.kind == "fhir")
    if p.kind == "csv":
        rows = csv_rows(p.text, p.delimiter)
        return [f"row:{i}" for i, r in enumerate(rows[1:]) if any(c.strip() for c in r)]
    return ["doc"]


def _list_files(inp: Path):
    out = []
    for dp, dn, fn in os.walk(inp):
        dn.sort()
        for name in sorted(fn):
            out.append(Path(dp) / name)
    return sorted(out, key=lambda p: p.relative_to(inp).as_posix())


def main(argv=None) -> int:
    sys.excepthook = _excepthook
    sys.setrecursionlimit(3000)
    ap = argparse.ArgumentParser(description="Cohort Cloak privacy firewall")
    ap.add_argument("--input", required=True)
    ap.add_argument("--output", required=True)
    a = ap.parse_args(argv)
    t0 = time.monotonic()
    secret = os.environ.get("RAKSHA_SECRET", "")
    if not secret:
        print("error missing_secret")
        return 2
    inp, out = Path(a.input).resolve(), Path(a.output).resolve()
    if not inp.is_dir():
        print("error input_not_a_directory")
        return 2
    if out == inp or inp in out.parents or out in inp.parents:
        print("error output_overlaps_input")
        return 2
    keys = Keys(secret.encode("utf-8"))  # noqa: F841 - used from Phase 4 on
    policy = load_policy(ROOT / "config" / "policy.yaml")

    for stale in ("sanitized", "logs"):
        shutil.rmtree(out / stale, ignore_errors=True)
    for stale in ("report.json", "records.jsonl"):
        try:
            (out / stale).unlink()
        except FileNotFoundError:
            pass
    (out / "sanitized").mkdir(parents=True, exist_ok=True)
    log = RunLog(out / "logs" / "run.log")

    scrubber = Scrubber(policy)
    # pass 1: read and parse everything, then learn names/IDs from every channel (output discarded)
    items = []  # (rel, sha, parsed|None, reason)
    for path in _list_files(inp):
        rel = path.relative_to(inp).as_posix()
        sha, parsed, reason = "", None, None
        try:
            raw = path.read_bytes()
            sha = hashlib.sha256(raw).hexdigest()
            parsed = parse(raw, path.suffix, int(policy["max_json_depth"]))
        except Exception as exc:  # noqa: BLE001 - global guard: quarantine, record the class only
            reason = reason_for(exc)
            if not sha:
                sha = hashlib.sha256(b"").hexdigest()
        items.append((rel, sha, parsed, reason))
    for _rel, _sha, parsed, reason in items:
        if parsed is not None:
            try:
                _render(parsed, scrubber)
            except Exception:  # noqa: BLE001 - surfaced again (and quarantined) in pass 2
                pass
    scrubber.identifiers = 0

    # pass 2: rewrite with the complete dictionaries
    results = []  # (rel, sha, output_bytes|None, locs, reason)
    for rel, sha, parsed, reason in items:
        data, locs = None, []
        if parsed is not None:
            try:
                data, n = _render(parsed, scrubber)
                locs = _locs(parsed)
            except Exception as exc:  # noqa: BLE001
                reason, data, locs = reason_for(exc), None, []
        results.append((rel, sha, data, locs, reason))
        log.event("file_done", status="quarantined" if data is None else "sanitized", records=len(locs))
    identifiers = scrubber.identifiers

    mapping = sanitize_paths([r[0] for r in results if r[2] is not None], scrubber.names, scrubber.ids)
    files, records = [], []
    for rel, sha, data, locs, reason in results:
        if data is None:
            files.append({"input_sha256": sha, "output": None, "status": "quarantined", "reason": reason})
            continue
        out_rel = mapping[rel]
        dest = out / "sanitized" / out_rel
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)
        except OSError as exc:
            files.append({"input_sha256": sha, "output": None, "status": "quarantined", "reason": reason_for(exc)})
            continue
        files.append({"input_sha256": sha, "output": f"sanitized/{out_rel}", "status": "sanitized"})
        records.extend({"file": f"sanitized/{out_rel}", "loc": loc, "patient": None} for loc in locs)

    write_records(out / "records.jsonl", records)
    report = build_report(files, records, identifiers, time.monotonic() - t0)
    write_report(out / "report.json", report)
    log.event("run_done", files=len(files), records=len(records))
    log.close()
    c = report["counts"]
    print(f"files {c['files_total']} sanitized {c['files_sanitized']} quarantined {c['files_quarantined']} "
          f"records {c['records_processed']}")
    return 0
