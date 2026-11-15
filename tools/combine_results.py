#!/usr/bin/env python3
"""Combine every SPEC CPU2017 result into one table.

Reads the per-study CSVs (2 MB main runs, HawkeyeI at 2 MB, the LLC-size
sweep, and the Mockingjay runs) and writes results/06_all_policies.csv with
one row per LLC size, benchmark and policy. Miss reduction and speedup are
recomputed against LRU at the same LLC size. Overlapping rows must agree.

Usage (from the repository root): python3 tools/combine_results.py
"""

import csv
import sys

SOURCES = [
    ("results/02_spec_main.csv", "2MB"),
    ("StatusReport/fig/hawkeyei_2mb.csv", "2MB"),
    ("results/04_llc_sweep.csv", None),
    ("results/mockingjay/mj_main.csv", "2MB"),
    ("results/mockingjay/mj_llc1MB.csv", "1MB"),
    ("results/mockingjay/mj_llc4MB.csv", "4MB"),
]
OUT = "results/06_all_policies.csv"
LLCS = ["1MB", "2MB", "4MB"]
BENCHES = ["605.mcf_s", "620.omnetpp_s", "502.gcc_r", "623.xalancbmk_s",
           "557.xz_r", "531.deepsjeng_r"]
POLICIES = ["LRU", "SRRIP", "BRRIP", "DRRIP", "SHiP", "Hawkeye", "HawkeyeI",
            "Mockingjay", "MockingjayI"]
RAW = ["insts", "llc_accesses", "llc_misses", "ipc"]


def main():
    rows = {}
    for path, llc in SOURCES:
        for r in csv.DictReader(open(path)):
            key = (r.get("llc") or llc, r["bench"], r["policy"])
            raw = {k: r[k] for k in RAW}
            if key in rows and rows[key] != raw:
                sys.exit(f"{path}: {key} disagrees with an earlier source")
            rows[key] = raw

    with open(OUT, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["llc", "bench", "policy", "insts", "llc_accesses",
                    "llc_misses", "mpki", "ipc", "miss_red_%", "speedup"])
        n = 0
        for llc in LLCS:
            for b in BENCHES:
                lru = rows.get((llc, b, "LRU"))
                for p in POLICIES:
                    r = rows.get((llc, b, p))
                    if r is None:
                        continue
                    insts, misses = int(r["insts"]), int(r["llc_misses"])
                    red = 100 * (int(lru["llc_misses"]) - misses) / int(lru["llc_misses"])
                    spd = float(r["ipc"]) / float(lru["ipc"])
                    w.writerow([llc, b, p, insts, r["llc_accesses"], misses,
                                repr(1000 * misses / insts), r["ipc"],
                                repr(red), repr(spd)])
                    n += 1
    print(f"wrote {OUT}: {n} rows")


if __name__ == "__main__":
    main()
