"""report.json and records.jsonl writers. Counts describe exactly what was written."""
import json
import sys
from pathlib import Path


def peak_rss_mb() -> float:
    """Peak resident memory of this process, in MiB (not a sum of unrelated peaks)."""
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes
        class Memory(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD)] + [
                (n, ctypes.c_size_t) for n in ("PeakWorkingSetSize", "WorkingSetSize", "QuotaPeakPagedPoolUsage",
                "QuotaPagedPoolUsage", "QuotaPeakNonPagedPoolUsage", "QuotaNonPagedPoolUsage", "PagefileUsage", "PeakPagefileUsage")]
        memory = Memory()
        memory.cb = ctypes.sizeof(memory)
        if not ctypes.WinDLL("psapi", use_last_error=True).GetProcessMemoryInfo(ctypes.c_void_p(-1), ctypes.byref(memory), memory.cb):
            raise ctypes.WinError(ctypes.get_last_error())
        return round(memory.PeakWorkingSetSize / 1048576, 1)
    import resource
    own = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return round(own / (1048576 if sys.platform == "darwin" else 1024), 1)


def write_records(path: Path, records: list) -> None:
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n")


def build_report(files: list, records: list, identifiers: int, seconds: float, entities=None, generalized: int = 0) -> dict:
    n_san = sum(e["status"] == "sanitized" for e in files)
    return {
        "schema": "raksha-report/1",
        "files": files,
        "counts": {
            "files_total": len(files), "files_sanitized": n_san, "files_quarantined": len(files) - n_san,
            "records_processed": len(records), "identifiers_detected": identifiers,
            "records_linked": sum(r["patient"] is not None for r in records),
            "records_generalized": generalized, "records_suppressed": 0, "records_quarantined": 0,
        },
        "entities": {k.strip("[]"): entities[k] for k in sorted(entities)} if entities else {},
        "timing": {"seconds": round(seconds, 2)},
        "resources": {"peak_rss_mb": peak_rss_mb()},
    }


def write_report(path: Path, report: dict) -> None:
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
