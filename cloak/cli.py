"""Orchestration: ingest -> (redact) -> write, with a global exception guard."""
import argparse
import csv
import hashlib
import re
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
from cloak.link.units import link_units, patient_for
from cloak.privacy.plan import build as build_plan
from cloak.rewrite.apply import resolve, substitute
from cloak.security.store import SpillStore
from cloak.rewrite.structured import transform_csv, transform_json, transform_text

ROOT = Path(__file__).resolve().parent.parent


def _excepthook(etype, _value, tb):
    """Type and file:line frames only; the exception message may embed record content."""
    frames = [f"{Path(f.filename).name}:{f.lineno}" for f in traceback.extract_tb(tb)]
    sys.stderr.write(f"fatal {etype.__name__} at {' > '.join(frames[-6:])}\n")


def _render(p, scrubber, locs=()):
    """Return (output_bytes, redaction_count) for a parsed file."""
    scrubber.rec = "doc"
    if p.kind == "jsonl":
        out, n = transform_json(p.data, scrubber, locs)
        scrubber.rec = "doc"
        return ("\n".join(json.dumps(x, ensure_ascii=False) for x in out) + "\n").encode("utf-8"), n
    if p.kind in ("json", "fhir"):
        out, n = transform_json(p.data, scrubber, locs)
        scrubber.rec = "doc"
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
    if scrubber.table is not None and scrubber.sink is not None:
        placed = any(t[0] == scrubber.fid and t[1] == "doc" and t[2] in ("name", "mrn") for t in scrubber.table)
        has_identity = any(e[0] == scrubber.fid and e[1] == "doc" and e[2] in _IDENTITY_EVENTS for e in scrubber.sink)
        if has_identity and not placed:
            scrubber.rec = "doc"
            out = out.rstrip("\n") + "\n" + scrubber.sentinel("append", "") + "\n"
    return out.encode("utf-8"), n


_IDENTITY_EVENTS = ("patient_name", "name:subject", "mrn", "aadhaar", "abha", "hard:ID", "hard:AADHAAR", "hard:ABHA",
                    "hard:PHONE", "id:known", "phone")


def _locs(p):
    if p.kind in ("json", "fhir", "jsonl"):
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
    ap = argparse.ArgumentParser(description="CohortCloak privacy firewall")
    ap.add_argument("--input", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--ablate-names", action="store_true", help="dev only: do not learn names from structured fields")
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
    keys = Keys(secret.encode("utf-8"))
    policy = load_policy(Path(os.environ.get("COHORT_POLICY") or ROOT / "config" / "policy.yaml"))
    policy["ablate_names"] = bool(a.ablate_names)

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
    store = SpillStore(keys.at_rest_key, int(float(policy.get("spill_threshold_mb", 64)) * 1048576))
    try:
        return _run(a, inp, out, keys, policy, scrubber, store, log, t0)
    finally:
        store.close()
        log.close()


def _read_parse(path, policy):
    """(sha, parsed|None, reason|None) for one file. Raw bytes are never kept."""
    sha, parsed, reason = "", None, None
    try:
        raw = path.read_bytes()
        sha = hashlib.sha256(raw).hexdigest()
        parsed = parse(raw, path.suffix, int(policy["max_json_depth"]))
    except Exception as exc:  # noqa: BLE001 - global guard: quarantine, record the class only
        reason = reason_for(exc)
        if not sha:
            sha = hashlib.sha256(b"").hexdigest()
    return sha, parsed, reason


def _run(a, inp, out, keys, policy, scrubber, store, log, t0):
    files_in = _list_files(inp)
    rels = [p.relative_to(inp).as_posix() for p in files_in]
    for fid, rel in enumerate(rels):
        scrubber.file_tokens[fid] = tuple(re.findall(r"[a-z]{3,}", rel.rsplit("/", 1)[-1].casefold()))

    # pass 1 (learn): names/IDs/date-order votes from every channel; output discarded, files re-read in pass 2
    shas, reasons = [], []
    for fid, path in enumerate(files_in):
        sha, parsed, reason = _read_parse(path, policy)
        shas.append(sha)
        reasons.append(reason)
        scrubber.fid = fid
        if parsed is not None:
            try:
                _render(parsed, scrubber, _locs(parsed))
            except Exception:  # noqa: BLE001 - surfaced again (and quarantined) in the final pass
                pass
        del parsed
    if scrubber.year_counts:
        scrubber.ref_year = sorted(scrubber.year_counts, key=lambda y: (-scrubber.year_counts[y], y))[0]

    # pass 2: final render with evidence capture and PSN placement sentinels
    scrubber.identifiers = 0
    scrubber.stats.clear()
    scrubber.sink, scrubber.table = [], []
    results = []  # (rel, sha, store handle|None, locs, reason)
    for fid, path in enumerate(files_in):
        sha, parsed, reason = shas[fid], None, reasons[fid]
        handle, locs = None, []
        if reason is None:
            sha2, parsed, reason = _read_parse(path, policy)
            if sha2 != sha and reason is None:
                parsed, reason = None, "input_changed_during_run"
        if parsed is not None:
            scrubber.fid = fid
            mark = (len(scrubber.sink), len(scrubber.table))
            try:
                locs = _locs(parsed)
                data, _n = _render(parsed, scrubber, locs)
                handle = store.put(data)
            except Exception as exc:  # noqa: BLE001
                reason, handle, locs = reason_for(exc), None, []
                del scrubber.sink[mark[0]:], scrubber.table[mark[1]:]
        del parsed
        results.append((rels[fid], sha, handle, locs, reason))
        log.event("file_done", status="quarantined" if handle is None else "sanitized", records=len(locs))
    identifiers = scrubber.identifiers

    # link -> privacy plan -> resolve placement sentinels. If linking fails, fall back to "nothing linked".
    try:
        unit_psn, unit_info, link_stats = link_units(results, scrubber.sink, keys, policy)
        plan = build_plan(keys, policy, scrubber.table, unit_psn, rels, unit_info)
        repl, placed, touched = resolve(scrubber.table, unit_psn, plan)
    except Exception:  # noqa: BLE001
        log.event("link_failed")
        unit_psn, unit_info, link_stats = {}, {}, {"clusters": 0, "units": 0, "fragments": 0}
        plan = build_plan(keys, policy, scrubber.table, unit_psn, rels, unit_info)
        repl, placed, touched = resolve(scrubber.table, unit_psn, plan)
    log.event("linked", clusters=link_stats["clusters"], units=link_stats["units"], fragments=link_stats["fragments"])

    mapping = sanitize_paths([r[0] for r in results if r[2] is not None], scrubber.names, scrubber.ids)
    files, records = [], []
    for fid, (rel, sha, data, locs, reason) in enumerate(results):
        if data is None:
            files.append({"input_sha256": sha, "output": None, "status": "quarantined", "reason": reason})
            continue
        out_rel = mapping[rel]
        dest = out / "sanitized" / out_rel
        try:
            text = substitute(store.get(data).decode("utf-8"), repl).encode("utf-8")
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(text)
        except Exception as exc:  # noqa: BLE001
            files.append({"input_sha256": sha, "output": None, "status": "quarantined", "reason": reason_for(exc)})
            continue
        files.append({"input_sha256": sha, "output": f"sanitized/{out_rel}", "status": "sanitized"})
        for loc in locs:
            psn = patient_for(fid, loc, locs, unit_psn, placed)
            records.append({"file": f"sanitized/{out_rel}", "loc": loc, "patient": psn})

    write_records(out / "records.jsonl", records)
    report = build_report(files, records, identifiers, time.monotonic() - t0, scrubber.stats, len(touched))
    write_report(out / "report.json", report)
    log.event("run_done", files=len(files), records=len(records), spilled=store.spilled)
    c = report["counts"]
    print(f"files {c['files_total']} sanitized {c['files_sanitized']} quarantined {c['files_quarantined']} "
          f"records {c['records_processed']}")
    return 0
