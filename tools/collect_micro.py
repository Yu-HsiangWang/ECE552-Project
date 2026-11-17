#!/usr/bin/env python3
"""Collect the microbenchmark runs into one CSV.

Usage: collect_micro.py <passes>:<dir> [<passes>:<dir> ...] --csv <file>
  <dir>/<pattern>/<policy>/stats.txt, as written by run_micro.sh and
  run_final.sh. When two directories hold the same (passes, pattern,
  policy), the first one wins, and the two must agree on the miss count.
"""

import argparse
import csv
import re
import sys
from pathlib import Path

PATTERNS = ["fit", "thrash", "mix"]
POLICIES = ["LRU", "SRRIP", "BRRIP", "DRRIP", "SHiP", "Hawkeye", "HawkeyeI",
            "Mockingjay", "MockingjayI"]
KEYS = {"system.llc.overallAccesses::total": "llc_accesses",
        "system.llc.overallMisses::total": "llc_misses",
        "simInsts": "insts",
        "system.cpu.ipc": "ipc"}


def read(path):
    out = {}
    for line in path.read_text().splitlines():
        m = re.match(r"(\S+)\s+(\S+)", line)
        if m and m.group(1) in KEYS:
            out[KEYS[m.group(1)]] = float(m.group(2))
    return out


def main():
    p = argparse.ArgumentParser()
    p.add_argument("sources", nargs="+")
    p.add_argument("--csv", required=True)
    args = p.parse_args()
    rows = {}
    for src in args.sources:
        passes, d = src.split(":", 1)
        for pat in PATTERNS:
            for rp in POLICIES:
                f = Path(d) / pat / rp / "stats.txt"
                if not f.exists() or f.stat().st_size == 0:
                    continue
                s = read(f)
                key = (int(passes), pat, rp)
                if key in rows:
                    if rows[key]["llc_misses"] != int(s["llc_misses"]):
                        sys.exit(f"{f}: misses differ from an earlier source")
                    continue
                rows[key] = {
                    "passes": int(passes), "pattern": pat, "policy": rp,
                    "insts": int(s["insts"]),
                    "llc_accesses": int(s["llc_accesses"]),
                    "llc_misses": int(s["llc_misses"]),
                    "miss_rate_%": 100 * s["llc_misses"] / s["llc_accesses"],
                    "ipc": s["ipc"],
                }
    cols = ["passes", "pattern", "policy", "insts", "llc_accesses",
            "llc_misses", "miss_rate_%", "ipc"]
    order = {v: i for i, v in enumerate(PATTERNS + POLICIES)}
    with open(args.csv, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for k in sorted(rows, key=lambda k: (k[0], order[k[1]], order[k[2]])):
            w.writerow(rows[k])
    print(f"wrote {args.csv}: {len(rows)} rows")


if __name__ == "__main__":
    main()
