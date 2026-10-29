#!/usr/bin/env python3
"""Reference models for validating the gem5 Hawkeye implementation.

  python3 hawkeye_ref.py demo
      Toy example: LRU, Belady's OPT, and OPTgen side by side on one set.

  python3 hawkeye_ref.py check <gem5 log> [--ways 16 --sets 2048 ...]
      Reads a gem5 log made with --debug-flags=Hawkeye, replays the LLC
      demand accesses through a Python copy of OPTgen and the sampler, and
      compares every OPT hit/miss label with gem5's. Also reports the miss
      rates of LRU and Belady's OPT on the same access stream.

OPTgen here follows hawkeye_rp.cc (and the authors' CRC2 code): a 128-entry
occupancy vector per sampled set, a capacity of ways - 2, a 1024-entry timer,
and a 2800-entry, 8-way sampler tagged by crc(addr >> 12) % 256.
"""

import argparse
import re
import sys
from collections import OrderedDict, defaultdict


# ----------------------------------------------------------------------
# Basic policies on one access stream
# ----------------------------------------------------------------------

def lru_hits(stream, ways):
    """stream: list of (set, block). Returns a list of booleans (hit?)."""
    sets = defaultdict(OrderedDict)
    hits = []
    for s, blk in stream:
        lines = sets[s]
        if blk in lines:
            lines.move_to_end(blk)
            hits.append(True)
        else:
            if len(lines) == ways:
                lines.popitem(last=False)
            lines[blk] = True
            hits.append(False)
    return hits


def belady_hits(stream, ways, bypass=True):
    """Belady's OPT: on a miss in a full set, evict the line whose next use
    is furthest away. With bypass, the incoming line itself may be the one
    that is not kept (this is the OPT that OPTgen models)."""
    inf = float("inf")
    next_use = [inf] * len(stream)
    seen = {}
    for i in range(len(stream) - 1, -1, -1):
        next_use[i] = seen.get(stream[i], inf)
        seen[stream[i]] = i

    sets = defaultdict(dict)  # set -> {block: next use}
    hits = []
    for i, (s, blk) in enumerate(stream):
        lines = sets[s]
        if blk in lines:
            hits.append(True)
            lines[blk] = next_use[i]
            continue
        hits.append(False)
        if len(lines) < ways:
            lines[blk] = next_use[i]
            continue
        victim = max(lines, key=lines.get)
        if bypass and next_use[i] >= lines[victim]:
            continue  # the incoming line is reused last: do not keep it
        del lines[victim]
        lines[blk] = next_use[i]
    return hits


# ----------------------------------------------------------------------
# OPTgen, as in hawkeye_rp.cc
# ----------------------------------------------------------------------

def crc_hash(value):
    for _ in range(32):
        value = (value >> 1) ^ 0xEDB88320 if value & 1 else value >> 1
    return value


class OptGenModel:
    def __init__(self, capacity, vector_size=128, timer_size=1024,
                 sampler_entries=2800, sampler_ways=8, exact_tags=False):
        self.capacity = capacity
        self.vector_size = vector_size
        self.timer_size = timer_size
        self.sampler_sets = sampler_entries // sampler_ways
        self.sampler_ways = sampler_ways
        self.exact_tags = exact_tags
        self.occupancy = defaultdict(lambda: [0] * vector_size)
        self.timer = defaultdict(int)
        # sampler set -> {tag: [last_time, pc, lru]}
        self.sampler = defaultdict(dict)

    def access(self, cache_set, addr, pc):
        """Returns (pc_trained, opt_hit) when a usage interval ends,
        otherwise None."""
        occ = self.occupancy[cache_set]
        now = self.timer[cache_set]
        curr = now % self.vector_size
        sset = self.sampler[(addr >> 6) % self.sampler_sets]
        tag = addr if self.exact_tags else crc_hash(addr >> 12) % 256
        result = None

        if tag in sset:
            last_time, last_pc, lru = sset[tag]
            elapsed = (now + self.timer_size - last_time) % self.timer_size
            opt_hit = False
            if elapsed <= self.vector_size:
                last = last_time % self.vector_size
                idx = []
                i = last
                while i != curr:
                    idx.append(i)
                    i = (i + 1) % self.vector_size
                opt_hit = all(occ[i] < self.capacity for i in idx)
                if opt_hit:
                    for i in idx:
                        occ[i] += 1
            result = (last_pc, opt_hit)
            for other in sset.values():
                if other[2] < lru:
                    other[2] += 1
        else:
            if len(sset) == self.sampler_ways:
                for t, e in list(sset.items()):
                    if e[2] == self.sampler_ways - 1:
                        del sset[t]
                        break
            for other in sset.values():
                other[2] += 1
            sset[tag] = [0, 0, 0]

        occ[curr] = 0
        sset[tag] = [now, pc, 0]
        self.timer[cache_set] = (now + 1) % self.timer_size
        return result


# ----------------------------------------------------------------------
# demo
# ----------------------------------------------------------------------

def demo():
    ways = 3
    seq = list("ABCDABCDABCD")
    stream = [(0, b) for b in seq]
    lru = lru_hits(stream, ways)
    opt = belady_hits(stream, ways)

    # OPTgen labels each reuse: would OPT have kept the line since its
    # previous access? (exact tags, capacity = ways)
    og = OptGenModel(capacity=ways, vector_size=8 * ways, exact_tags=True)
    labels = []
    for blk in seq:
        r = og.access(0, ord(blk) << 6, pc=0)
        labels.append("-" if r is None else ("hit" if r[1] else "miss"))

    print(f"One set with {ways} ways, accesses {' '.join(seq)}\n")
    print(f"{'access':>7} {'LRU':>5} {'OPT':>5} {'OPTgen':>7}")
    for i, blk in enumerate(seq):
        print(f"{blk:>7} {'hit' if lru[i] else 'miss':>5} "
              f"{'hit' if opt[i] else 'miss':>5} {labels[i]:>7}")
    print(f"\nLRU hits: {sum(lru)}/{len(seq)}   OPT hits: {sum(opt)}/{len(seq)}")
    print("OPTgen labels the same reuses as OPT, but only by looking at the "
          "past.")


# ----------------------------------------------------------------------
# check against a gem5 Hawkeye debug log
# ----------------------------------------------------------------------

FILL_RE = re.compile(r"(fill|hit) set (\d+) addr (0x[0-9a-f]+) pc (0x[0-9a-f]+|0)")
OPT_RE = re.compile(r"OPTgen set (\d+) addr (0x[0-9a-f]+): reuse after \d+, "
                    r"OPT (hit|miss), train pc (0x[0-9a-f]+|0)")


def check(args):
    accesses = []   # (set, addr, pc) for every demand access, in order
    gem5_labels = []  # (set, addr, pc_trained, opt_hit) in order
    with open(args.log) as f:
        for line in f:
            m = OPT_RE.search(line)
            if m:
                gem5_labels.append((int(m.group(1)), int(m.group(2), 16),
                                    int(m.group(4), 16), m.group(3) == "hit"))
                continue
            m = FILL_RE.search(line)
            if m:
                accesses.append((int(m.group(2)), int(m.group(3), 16),
                                 int(m.group(4), 16)))

    stride = args.sets // args.sampled_sets
    sampled = lambda s: (s % stride) == ((s // stride) % stride)
    og = OptGenModel(capacity=args.ways - 2, vector_size=8 * args.ways)
    ref_labels = []
    for s, addr, pc in accesses:
        if sampled(s):
            r = og.access(s, addr, pc)
            if r is not None:
                ref_labels.append((s, addr, r[0], r[1]))

    mismatches = sum(1 for a, b in zip(ref_labels, gem5_labels) if a != b)
    mismatches += abs(len(ref_labels) - len(gem5_labels))
    print(f"demand accesses in log:  {len(accesses)}")
    print(f"OPTgen labels (gem5/ref): {len(gem5_labels)}/{len(ref_labels)}")
    print(f"label mismatches:         {mismatches}")
    for i, (a, b) in enumerate(zip(ref_labels, gem5_labels)):
        if a != b:
            print(f"first mismatch at label {i}: ref {a} gem5 {b}")
            break

    stream = [(s, addr >> 6) for s, addr, _ in accesses]
    n = len(stream)
    if n:
        lru = sum(lru_hits(stream, args.ways))
        opt = sum(belady_hits(stream, args.ways))
        print(f"LRU miss rate on this stream:  {1 - lru / n:.4f}")
        print(f"OPT miss rate on this stream:  {1 - opt / n:.4f}")
    return 1 if mismatches else 0


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawTextHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("demo")
    c = sub.add_parser("check")
    c.add_argument("log")
    c.add_argument("--ways", type=int, default=16)
    c.add_argument("--sets", type=int, default=2048)
    c.add_argument("--sampled-sets", type=int, default=64)
    args = p.parse_args()
    if args.cmd == "demo":
        demo()
        return 0
    return check(args)


if __name__ == "__main__":
    sys.exit(main())
