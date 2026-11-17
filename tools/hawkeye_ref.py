#!/usr/bin/env python3
"""Reference models for validating the gem5 Hawkeye implementation.

  python3 hawkeye_ref.py demo
      Toy example: LRU, Belady's OPT, and OPTgen side by side on one set.

  python3 hawkeye_ref.py check <gem5 log> [--ways 16 --sets 2048 ...]
      Reads a gem5 log made with --debug-flags=Hawkeye, replays the LLC
      demand accesses through a Python copy of OPTgen and the sampler, and
      compares every OPT hit/miss label with gem5's. Also reports the miss
      rates of LRU and Belady's OPT on the same access stream.

  python3 hawkeye_ref.py replay <gem5 log> [--inst-friendly] [...]
      Drives a full Python Hawkeye (OPTgen, sampler, predictor, RRPVs and
      victim choice) with gem5's own sequence of policy events (fills and
      hits in the ways gem5 used, writebacks, invalidations) and compares
      every OPTgen label, prediction, counter value, RRPV and victim.
      Needs the log format of hawkeye_rp.cc from 11-17 (way, ctr, inst).
      --inst-friendly checks HawkeyeI.

OPTgen here follows hawkeye_rp.cc (and the authors' CRC2 code): a 128-entry
occupancy vector per sampled set, a capacity of ways - 2, a 1024-entry timer,
and a 2800-entry, 8-way sampler tagged by crc(addr >> 12) % 256.
"""

import argparse
import gzip
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

    def access(self, cache_set, addr, pc, inst=False):
        """Returns (pc_trained, opt_hit, inst_of_that_entry) when a usage
        interval ends, otherwise None."""
        occ = self.occupancy[cache_set]
        now = self.timer[cache_set]
        curr = now % self.vector_size
        sset = self.sampler[(addr >> 6) % self.sampler_sets]
        tag = addr if self.exact_tags else crc_hash(addr >> 12) % 256
        result = None

        if tag in sset:
            last_time, last_pc, lru, last_inst = sset[tag]
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
            result = (last_pc, opt_hit, last_inst)
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
            sset[tag] = [0, 0, 0, False]

        occ[curr] = 0
        sset[tag] = [now, pc, 0, inst]
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


def open_log(path):
    return gzip.open(path, "rt") if path.endswith(".gz") else open(path)


def check(args):
    accesses = []   # (set, addr, pc) for every demand access, in order
    gem5_labels = []  # (set, addr, pc_trained, opt_hit) in order
    with open_log(args.log) as f:
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


# ----------------------------------------------------------------------
# replay: the whole policy, driven by gem5's event sequence
# ----------------------------------------------------------------------

ACC_RE = re.compile(
    r"(fill|hit) set (\d+) addr (0x[0-9a-f]+|0) pc (0x[0-9a-f]+|0): "
    r"(friendly|averse), rrpv (\d+), way (\d+), ctr (\d+), inst (\d)")
VICTIM_RE = re.compile(r"victim set (\d+) way (\d+): (invalid|averse|oldest friendly)")
WB_RE = re.compile(r"writeback set (\d+) way (\d+) addr (0x[0-9a-f]+|0): (insert|hit)")
INVAL_RE = re.compile(r"invalidate set (\d+) way (\d+)")


class HawkeyeModel:
    """hawkeye_rp.cc with the default parameters (CRC2 configuration)."""

    def __init__(self, sets, ways, sampled_sets=64, predictor_entries=2048,
                 counter_bits=5, rrpv_bits=3, inst_friendly=False):
        self.sets, self.ways = sets, ways
        self.stride = sets // sampled_sets
        self.entries = predictor_entries
        self.counter_max = (1 << counter_bits) - 1
        self.threshold = (self.counter_max + 1) // 2
        self.counters = [self.threshold] * predictor_entries
        self.max_rrpv = (1 << rrpv_bits) - 1
        self.inst_friendly = inst_friendly
        self.og = OptGenModel(capacity=ways - 2, vector_size=8 * ways)
        self.blocks = [[None] * ways for _ in range(sets)]
        self.rrpv = [[self.max_rrpv] * ways for _ in range(sets)]
        self.pc = [[0] * ways for _ in range(sets)]
        self.inst = [[False] * ways for _ in range(sets)]
        self.last_victim_set = None

    def sampled(self, s):
        return (s % self.stride) == ((s // self.stride) % self.stride)

    def index(self, pc):
        return crc_hash(pc) % self.entries

    def train(self, pc, friendly):
        i = self.index(pc)
        c = self.counters[i]
        if friendly and c < self.counter_max:
            self.counters[i] = c + 1
        elif not friendly and c > 0:
            self.counters[i] = c - 1

    def victim(self, s):
        """Returns (way, kind) as getVictim() would, detraining on a
        friendly victim in a sampled set."""
        self.last_victim_set = s
        row = self.blocks[s]
        if None in row:
            return row.index(None), "invalid"
        rr = self.rrpv[s]
        for w in range(self.ways):
            if rr[w] == self.max_rrpv:
                return w, "averse"
        w = max(range(self.ways), key=lambda x: (rr[x], x))
        if self.sampled(s) and not (self.inst_friendly and self.inst[s][w]):
            self.train(self.pc[s][w], False)
        return w, "oldest friendly"

    def demand(self, s, w, addr, pc, hit, inst):
        """A fill or a hit in way w. Returns (OPTgen label or None,
        friendly, counter value, new RRPV)."""
        label = None
        if self.sampled(s):
            r = self.og.access(s, addr, pc, inst)
            if r is not None:
                label = (s, addr, r[0], r[1])
                if not (self.inst_friendly and r[2]):
                    self.train(r[0], r[1])
        ctr = self.counters[self.index(pc)]
        friendly = (self.inst_friendly and inst) or ctr >= self.threshold
        if not hit:
            self.blocks[s][w] = addr >> 6
            self.inst[s][w] = inst
        self.pc[s][w] = pc
        rr = self.rrpv[s]
        if not friendly:
            rr[w] = self.max_rrpv
        else:
            rr[w] = 0
            if not hit and self.last_victim_set == s:
                others = [x for x in range(self.ways)
                          if x != w and self.blocks[s][x] is not None]
                if not any(rr[x] == self.max_rrpv - 1 for x in others):
                    for x in others:
                        if rr[x] < self.max_rrpv - 1:
                            rr[x] += 1
        if not hit:
            self.last_victim_set = None
        return label, friendly, ctr, rr[w]

    def writeback(self, s, w, addr, hit):
        if not hit:
            self.blocks[s][w] = addr >> 6
            self.rrpv[s][w] = self.max_rrpv
            self.pc[s][w] = 0
            self.inst[s][w] = False
            self.last_victim_set = None


def replay(args):
    m = HawkeyeModel(args.sets, args.ways, args.sampled_sets,
                     inst_friendly=args.inst_friendly)
    n = defaultdict(int)
    bad = []
    pending = []    # gem5's OPTgen labels for the next demand access

    def mismatch(lineno, what, line):
        n["mismatch " + what] += 1
        if len(bad) < args.show:
            bad.append(f"line {lineno}: {what}: {line.strip()}")

    with open_log(args.log) as f:
        for lineno, line in enumerate(f, 1):
            g = OPT_RE.search(line)
            if g:
                pending.append((int(g.group(1)), int(g.group(2), 16),
                                int(g.group(4), 16), g.group(3) == "hit"))
                continue
            g = ACC_RE.search(line)
            if g:
                kind, s, addr = g.group(1), int(g.group(2)), int(g.group(3), 16)
                pc, w = int(g.group(4), 16), int(g.group(7))
                hit, inst = kind == "hit", g.group(9) == "1"
                n["demand " + kind] += 1
                if hit and m.blocks[s][w] != addr >> 6:
                    mismatch(lineno, "hit on a line the model does not hold", line)
                label, friendly, ctr, rrpv = m.demand(s, w, addr, pc, hit, inst)
                if label is not None:
                    n["OPTgen labels"] += 1
                if pending != ([label] if label else []):
                    mismatch(lineno, "OPTgen label", line)
                pending = []
                if friendly != (g.group(5) == "friendly"):
                    mismatch(lineno, "prediction", line)
                if ctr != int(g.group(8)):
                    mismatch(lineno, f"counter (model {ctr})", line)
                if rrpv != int(g.group(6)):
                    mismatch(lineno, f"RRPV (model {rrpv})", line)
                continue
            g = VICTIM_RE.search(line)
            if g:
                s, w = int(g.group(1)), int(g.group(2))
                want, kind = m.victim(s)
                n["victims " + kind] += 1
                if (want, kind) != (w, g.group(3)):
                    mismatch(lineno, f"victim (model way {want}, {kind})", line)
                continue
            g = WB_RE.search(line)
            if g:
                s, w, addr = int(g.group(1)), int(g.group(2)), int(g.group(3), 16)
                hit = g.group(4) == "hit"
                n["writeback " + g.group(4)] += 1
                if hit and m.blocks[s][w] != addr >> 6:
                    mismatch(lineno, "writeback hit on a line the model does not hold", line)
                m.writeback(s, w, addr, hit)
                continue
            g = INVAL_RE.search(line)
            if g:
                m.blocks[int(g.group(1))][int(g.group(2))] = None
                n["invalidations"] += 1
    total = sum(v for k, v in n.items() if k.startswith("mismatch"))
    for k in sorted(n):
        print(f"  {k:<44} {n[k]}")
    print(f"  mismatches: {total}")
    for b in bad:
        print("    " + b)
    return 1 if total else 0


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
    r = sub.add_parser("replay")
    r.add_argument("log")
    r.add_argument("--ways", type=int, default=16)
    r.add_argument("--sets", type=int, default=2048)
    r.add_argument("--sampled-sets", type=int, default=64)
    r.add_argument("--inst-friendly", action="store_true",
                   help="check HawkeyeI (inst_always_friendly)")
    r.add_argument("--show", type=int, default=10)
    args = p.parse_args()
    if args.cmd == "demo":
        demo()
        return 0
    if args.cmd == "replay":
        return replay(args)
    return check(args)


if __name__ == "__main__":
    sys.exit(main())
