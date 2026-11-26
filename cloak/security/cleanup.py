"""Temp-file hygiene: everything registered here is removed on normal exit, exceptions, SIGTERM and SIGINT."""
import atexit
import os
import shutil
import signal

_paths = []
_installed = False


def register(path: str) -> None:
    _paths.append(path)
    install()


def cleanup() -> None:
    while _paths:
        shutil.rmtree(_paths.pop(), ignore_errors=True)


def _on_signal(signum, _frame):
    cleanup()
    raise SystemExit(128 + signum)  # unwinds `finally` blocks, then exits non-zero


def install() -> None:
    global _installed
    if _installed:
        return
    _installed = True
    atexit.register(cleanup)
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            signal.signal(sig, _on_signal)
        except (ValueError, OSError):  # not the main thread / unsupported platform
            pass
