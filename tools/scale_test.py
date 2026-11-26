#!/usr/bin/env python3
"""Scaling exponent: run the pipeline on stress sets of growing size and fit time ~ size^k (gate: k <= 1.15)."""
import argparse
import math
import os
import resource
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scales", default="1,4,10")
    ap.add_argument("--seed", type=int, default=7)
    a = ap.parse_args()
    pts = []
    for sc in (int(x) for x in a.scales.split(",")):
        work = Path(tempfile.mkdtemp(prefix="scale_"))
        subprocess.run([sys.executable, str(ROOT / "tools/make_stress.py"), "--out", str(work / "in"), "--truth",
                        str(work / "truth.json"), "--seed", str(a.seed), "--scale", str(sc)], check=True, capture_output=True)
        size = sum(p.stat().st_size for p in (work / "in").rglob("*") if p.is_file())
        nfiles = sum(1 for p in (work / "in").rglob("*") if p.is_file())
        t0 = time.monotonic()
        env = dict(os.environ, RAKSHA_SECRET="practice")
        r = subprocess.run(["/usr/bin/time", "-l", sys.executable, str(ROOT / "main.py"), "--input", str(work / "in"), "--output",
                            str(work / "out")], env=env, capture_output=True, text=True)
        wall = time.monotonic() - t0
        rss = 0
        for line in r.stderr.splitlines():
            if "maximum resident" in line:
                rss = int(line.split()[0]) / 1048576
        pts.append((sc, nfiles, size, wall, rss))
        print(f"scale {sc:>3}: files {nfiles:>5} bytes {size:>9} wall {wall:6.1f}s peak RSS {rss:6.0f} MB", flush=True)
    xs = [math.log(p[2]) for p in pts]
    ys = [math.log(p[3]) for p in pts]
    n = len(pts)
    mx, my = sum(xs) / n, sum(ys) / n
    k = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sum((x - mx) ** 2 for x in xs)
    print(f"scaling exponent (log-log fit of wall time vs input bytes): {k:.2f}")
    print(f"SCALE exponent={k:.3f} max_wall={max(p[3] for p in pts):.1f} max_rss={max(p[4] for p in pts):.0f}")


if __name__ == "__main__":
    main()
