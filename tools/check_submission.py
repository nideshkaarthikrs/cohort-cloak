"""Portable launcher for the unchanged official submission checker."""
import argparse
import os
from pathlib import Path
import runpy
import shlex
import subprocess
import sys


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--kit", required=True)
    args, remaining = ap.parse_known_args()
    checker = Path(args.kit).resolve() / "check_submission.py"
    if not checker.is_file():
        ap.error("Official checker not found")
    os.environ["PATH"] = str(Path(sys.executable).parent) + os.pathsep + os.environ.get("PATH", "")
    previous = shlex.quote
    if os.name == "nt":
        shlex.quote = lambda value: subprocess.list2cmdline([value])
    sys.argv = [str(checker)] + remaining
    try:
        runpy.run_path(str(checker), run_name="__main__")
    finally:
        shlex.quote = previous


if __name__ == "__main__":
    main()
