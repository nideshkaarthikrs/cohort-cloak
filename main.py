#!/usr/bin/env python3
"""Cohort Cloak entry point: python main.py --input <dir> --output <dir>."""
import sys

from cloak.cli import main

if __name__ == "__main__":
    sys.exit(main())
