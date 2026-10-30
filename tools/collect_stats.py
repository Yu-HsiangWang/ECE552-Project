#!/usr/bin/env python3
"""Collect LLC MPKI and IPC from gem5 runs into a table.

Usage: collect_stats.py <out dir> <tag> [--csv file]
  <out dir>/<benchmark>/<policy>_<tag>/stats.txt

The measured CPU is system.switch_cpu after a fast-forward, else system.cpu.
MPKI counts LLC demand misses (overallMisses) per 1000 measured
instructions. Speedup and miss reduction are relative to LRU.
"""

import argparse
import csv
import re
from pathlib import Path

POLICIES = ["LRU", "SRRIP", "BRRIP", "DRRIP", "SHiP", "Hawkeye"]


def read_stats(path):
    stats = {}
    for line in path.read_text().splitlines():
        m = re.match(r"(\S+)\s+([-0-9.e+]+|nan|inf)\s", line)
        if m:
            stats[m.group(1)] = float(m.group(2))
    return stats


def main():
    p = argparse.ArgumentParser()
    p.add_argument("out")
    p.add_argument("tag")
    p.add_argument("--csv")
    args = p.parse_args()

    rows = []
    for bench_dir in sorted(Path(args.out).iterdir()):
        for rp in POLICIES:
            f = bench_dir / f"{rp}_{args.tag}" / "stats.txt"
            if not f.exists() or f.stat().st_size == 0:
                continue
            s = read_stats(f)
            cpu = "system.switch_cpu" if f"system.switch_cpu.ipc" in s \
                and s["system.switch_cpu.ipc"] == s["system.switch_cpu.ipc"] \
                else "system.cpu"
            insts = s.get(f"{cpu}.committedInsts") or s.get(
                f"{cpu}.thread_0.numInsts", 0)
            misses = s.get("system.llc.overallMisses::total", 0)
            rows.append({
                "bench": bench_dir.name, "policy": rp, "insts": int(insts),
                "llc_accesses": int(s.get("system.llc.overallAccesses::total", 0)),
                "llc_misses": int(misses),
                "mpki": 1000 * misses / insts if insts else float("nan"),
                "ipc": s.get(f"{cpu}.ipc", float("nan")),
            })

    lru = {r["bench"]: r for r in rows if r["policy"] == "LRU"}
    for r in rows:
        base = lru.get(r["bench"])
        if base:
            r["miss_red_%"] = 100 * (1 - r["llc_misses"] / base["llc_misses"]) \
                if base["llc_misses"] else float("nan")
            r["speedup"] = r["ipc"] / base["ipc"]

    cols = ["bench", "policy", "insts", "llc_accesses", "llc_misses", "mpki",
            "ipc", "miss_red_%", "speedup"]
    print(" ".join(f"{c:>14}" for c in cols))
    for r in rows:
        vals = []
        for c in cols:
            v = r.get(c, "")
            vals.append(f"{v:>14.3f}" if isinstance(v, float) else f"{v!s:>14}")
        print(" ".join(vals))
    if args.csv:
        with open(args.csv, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=cols)
            w.writeheader()
            for r in rows:
                w.writerow({c: r.get(c, "") for c in cols})


if __name__ == "__main__":
    main()
