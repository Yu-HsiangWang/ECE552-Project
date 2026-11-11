#!/usr/bin/env python3
"""Reference model of Mockingjay (Shah, Jain, and Lin, HPCA 2022), used to
plan and later validate the gem5 implementation.

  python3 mockingjay_ref.py micro [--passes 6] [--check-lazy]
      Builds LLC access streams that follow tools/microbench/llc_patterns.c
      (fit, thrash, mix) and runs them through LRU, Belady's OPT, and
      Mockingjay. Prints the miss rates and what the predictor learned.

  python3 mockingjay_ref.py log <gem5 log made with --debug-flags=Hawkeye>
      Replays the LLC demand accesses of a gem5 run through the same
      policies.

  python3 mockingjay_ref.py storage [--sets 2048 --ways 16]
      Prints the storage of each hardware structure.

The model is a rewrite (not a copy) of a public single-core ChampSim
implementation of Mockingjay (Apache 2.0) whose storage matches the paper's
31.91 KB, and uses the same parameters:
32 sampled sets for a 2 MB LLC, a sampled cache of 16 sets x 5 ways per
sampled set, 8-bit timestamps, 11-bit PC signatures that include the hit
bit, a reuse-distance predictor (RDP) trained by temporal difference,
and a 5-bit signed ETR per line that is aged once every 8 accesses to its
set.

Two options model the differences we expect in gem5:
  bypass=False  gem5 cannot refuse a fill, so a line that Mockingjay would
                bypass is inserted. Its ETR is then the largest in the set,
                so it becomes the next victim.
  lazy=True     gem5 passes only the accessed line to the policy, so the
                set cannot be aged in place. Each line instead records the
                set's aging count when its ETR was set, and the current ETR
                is computed from it. --check-lazy runs both versions side
                by side and compares every decision.
"""

import argparse
import sys
from collections import Counter

from hawkeye_ref import FILL_RE, belady_hits, lru_hits

CRC_POLY = 3988292384


def crc3(value):
    """The 3-step CRC hash of the ChampSim implementation."""
    for _ in range(3):
        value = (value >> 1) ^ CRC_POLY if value & 1 else value >> 1
    return value


class Mockingjay:
    HISTORY = 8          # reuse distances are tracked up to 8 x ways
    GRANULARITY = 8      # one ETR step = 8 accesses to the set
    SC_WAYS = 5
    LOG2_SC_SETS = 4     # sampled-cache sets per sampled LLC set
    TS_BITS = 8
    FLEXMIN_PENALTY = 2.0

    def __init__(self, sets, ways, block=64, bypass=True, lazy=False):
        self.sets, self.ways = sets, ways
        self.bypass, self.lazy = bypass, lazy
        self.log2_sets = sets.bit_length() - 1
        self.log2_block = block.bit_length() - 1
        log2_size = self.log2_sets + (ways.bit_length() - 1) + self.log2_block
        self.log2_sampled = log2_size - 16
        self.inf_rd = ways * self.HISTORY - 1
        self.inf_etr = ways * self.HISTORY // self.GRANULARITY - 1
        self.max_rd = self.inf_rd - 22
        self.tag_bits = 31 - log2_size
        self.sig_bits = log2_size - 10

        self.blocks = [[None] * ways for _ in range(sets)]
        self.etr = [[0] * ways for _ in range(sets)]
        self.clock = [self.GRANULARITY] * sets
        self.timestamp = [0] * sets
        self.ticks = [0] * sets                    # lazy aging only
        self.etr_tick = [[0] * ways for _ in range(sets)]
        self.rdp = {}
        self.sampled_cache = {}
        self.stats = Counter()

    # -- addressing ----------------------------------------------------
    def is_sampled(self, s):
        n = self.log2_sets - self.log2_sampled
        mask = (1 << n) - 1
        return (s & mask) == ((s >> (self.log2_sets - n)) & mask)

    def signature(self, pc, hit, prefetch=False):
        v = (((pc << 1) | int(hit)) << 1) | int(prefetch)
        return crc3(v & (2**64 - 1)) & ((1 << self.sig_bits) - 1)

    def sc_index(self, addr):
        return (addr >> self.log2_block) & ((1 << (self.LOG2_SC_SETS + self.log2_sets)) - 1)

    def sc_tag(self, addr):
        shift = self.log2_sets + self.log2_block + self.LOG2_SC_SETS
        return (addr >> shift) & ((1 << self.tag_bits) - 1)

    # -- ETR, with eager or lazy aging --------------------------------
    def get_etr(self, s, w):
        if not self.lazy:
            return self.etr[s][w]
        e = self.etr[s][w]
        if abs(e) >= self.inf_etr:
            return e
        return max(e - (self.ticks[s] - self.etr_tick[s][w]), -self.inf_etr)

    def set_etr(self, s, w, value):
        self.etr[s][w] = value
        self.etr_tick[s][w] = self.ticks[s]

    def age(self, s, accessed_way):
        if self.clock[s] == self.GRANULARITY:
            if self.lazy:
                # The accessed line is skipped by the eager version. It gets
                # a new ETR right after this, so only freeze it when it is
                # bypassed (accessed_way is None: every line is aged).
                if accessed_way is not None:
                    w = accessed_way
                    self.etr[s][w] = self.get_etr(s, w)
                    self.etr_tick[s][w] = self.ticks[s] + 1
                self.ticks[s] += 1
            else:
                for w in range(self.ways):
                    e = self.etr[s][w]
                    if w != accessed_way and abs(e) < self.inf_etr:
                        self.etr[s][w] = e - 1
            self.clock[s] = 0
        self.clock[s] += 1

    # -- the policy ----------------------------------------------------
    def find_victim(self, s, pc, writeback, prefetch):
        max_etr, victim = 0, 0
        for w in range(self.ways):
            e = self.get_etr(s, w)
            if abs(e) > max_etr or (abs(e) == max_etr and e < 0):
                max_etr, victim = abs(e), w
        sig = self.signature(pc, False, prefetch)
        rd = self.rdp.get(sig)
        if (not writeback and rd is not None and
                (rd > self.max_rd or rd // self.GRANULARITY > max_etr)):
            self.stats["bypass"] += 1
            if self.bypass:
                return None
        return victim

    def detrain(self, lines, w):
        line = lines[w]
        if not line[0]:
            return
        sig = line[2]
        self.rdp[sig] = min(self.rdp[sig] + 1, self.inf_rd) if sig in self.rdp else self.inf_rd
        line[0] = False
        self.stats["detrain"] += 1

    def temporal_difference(self, init, sample):
        if sample > init:
            return min(init + min(1, (sample - init) // 16), self.inf_rd)
        if sample < init:
            return max(init - min(1, (init - sample) // 16), 0)
        return init

    def elapsed(self, now, then):
        return now - then if now >= then else now + (1 << self.TS_BITS) - then

    def train(self, s, addr, sig, prefetch):
        idx, tag = self.sc_index(addr), self.sc_tag(addr)
        lines = self.sampled_cache.setdefault(
            idx, [[False, 0, 0, 0] for _ in range(self.SC_WAYS)])
        now = self.timestamp[s]
        for line in lines:
            if line[0] and line[1] == tag:
                sample = self.elapsed(now, line[3])
                if sample <= self.inf_rd:
                    if prefetch:
                        sample = int(sample * self.FLEXMIN_PENALTY)
                    last = line[2]
                    self.rdp[last] = (self.temporal_difference(self.rdp[last], sample)
                                      if last in self.rdp else sample)
                    line[0] = False
                    self.stats["train"] += 1
                break
        lru_way, lru_rd = -1, -1
        for w, line in enumerate(lines):
            if not line[0]:
                lru_way, lru_rd = w, self.inf_rd + 1
                continue
            sample = self.elapsed(now, line[3])
            if sample > self.inf_rd:
                lru_way, lru_rd = w, self.inf_rd + 1
                self.detrain(lines, w)
            elif sample > lru_rd:
                lru_way, lru_rd = w, sample
        self.detrain(lines, lru_way)
        for line in lines:
            if not line[0]:
                line[:] = [True, tag, sig, now]
                break
        self.timestamp[s] = (now + 1) % (1 << self.TS_BITS)

    def access(self, addr, pc, writeback=False, prefetch=False):
        """One LLC access. Returns (hit, way); way is None when bypassed."""
        s = (addr >> self.log2_block) & (self.sets - 1)
        blk = addr >> self.log2_block
        row = self.blocks[s]
        if blk in row:
            hit, way = True, row.index(blk)
        else:
            hit = False
            way = row.index(None) if None in row else self.find_victim(
                s, pc, writeback, prefetch)
            if way is not None:
                row[way] = blk

        if writeback:
            if not hit and way is not None:
                self.set_etr(s, way, -self.inf_etr)
            return hit, way

        sig = self.signature(pc, hit, prefetch)
        if self.is_sampled(s):
            self.train(s, addr, sig, prefetch)
        self.age(s, way)
        if way is not None:
            rd = self.rdp.get(sig)
            if rd is None:
                self.set_etr(s, way, 0)
            elif rd > self.max_rd:
                self.set_etr(s, way, self.inf_etr)
            else:
                self.set_etr(s, way, rd // self.GRANULARITY)
        return hit, way

    # -- storage -------------------------------------------------------
    def storage_bits(self):
        n_sampled = 1 << self.log2_sampled
        sc_entries = n_sampled * (1 << self.LOG2_SC_SETS) * self.SC_WAYS
        sc_bits = 1 + self.tag_bits + self.sig_bits + self.TS_BITS
        rd_bits = self.inf_rd.bit_length()
        etr_bits = (self.inf_etr.bit_length()) + 1   # signed
        clock_bits = (self.GRANULARITY - 1).bit_length()
        return [
            ("ETR per line", self.sets * self.ways, etr_bits),
            ("aging clock per set", self.sets, clock_bits),
            ("RDP", 1 << self.sig_bits, rd_bits),
            ("sampled cache", sc_entries, sc_bits),
            ("timestamp per sampled set", n_sampled, self.TS_BITS),
        ]


# ----------------------------------------------------------------------
# streams
# ----------------------------------------------------------------------

LINE = 64
# Load PCs of the three inlined copies of pass() and of the two alloc()
# loops; any distinct values work, these follow the -O2 code layout.
PC_INIT, PC_INIT2 = 0x401040, 0x401080
PC_PASS, PC_REUSE, PC_STREAM = 0x4011a8, 0x4010d9, 0x401108


def scan(base, nbytes, pc):
    return [(base + i, pc) for i in range(0, nbytes, LINE)]


def micro_stream(pattern, passes=6):
    """LLC demand accesses of llc_patterns.c with the arguments of
    run_micro.sh (fit 1 MB, thrash 3 MB, mix 1 MB + 4 MB of stream per
    pass): every line of an array larger than the L2 misses there once per
    pass. alloc() writes every byte first, so each array also has an
    initial pass."""
    kb = 1024
    if pattern == "fit":
        arr = scan(0x10000000, 1024 * kb, PC_PASS)
        return scan(0x10000000, 1024 * kb, PC_INIT) + arr * passes
    if pattern == "thrash":
        arr = scan(0x10000000, 3072 * kb, PC_PASS)
        return scan(0x10000000, 3072 * kb, PC_INIT) + arr * passes
    if pattern == "mix":
        reuse, stream = 1024 * kb, 4 * 1024 * kb * passes
        r, s = 0x10000000, 0x40000000
        out = scan(r, reuse, PC_INIT) + scan(s, stream, PC_INIT2)
        chunk = stream // passes
        for p in range(passes):
            out += scan(r, reuse, PC_REUSE)
            out += scan(s + p * chunk, chunk, PC_STREAM)
        return out
    raise ValueError(pattern)


def run_mockingjay(stream, sets, ways, **kw):
    mj = Mockingjay(sets, ways, **kw)
    hits = sum(mj.access(addr, pc)[0] for addr, pc in stream)
    return hits, mj


def check_lazy(stream, sets, ways, bypass):
    eager = Mockingjay(sets, ways, bypass=bypass)
    lazy = Mockingjay(sets, ways, bypass=bypass, lazy=True)
    for i, (addr, pc) in enumerate(stream):
        a, b = eager.access(addr, pc), lazy.access(addr, pc)
        if a != b:
            return i
    return -1


def report(name, stream, sets, ways, lazy_check):
    n = len(stream)
    ss = [((addr >> 6) & (sets - 1), addr >> 6) for addr, _ in stream]
    rates = {
        "LRU": 1 - sum(lru_hits(ss, ways)) / n,
        "OPT": 1 - sum(belady_hits(ss, ways)) / n,
    }
    mjs = {}
    for label, bypass in (("Mockingjay", True), ("Mockingjay, no bypass", False)):
        hits, mj = run_mockingjay(stream, sets, ways, bypass=bypass)
        rates[label] = 1 - hits / n
        mjs[label] = mj
    print(f"{name}: {n} accesses")
    for k, v in rates.items():
        print(f"  {k:<22} miss rate {v:.4f}")
    mj = mjs["Mockingjay"]
    print(f"  bypassed fills {mj.stats['bypass']}, RDP updates "
          f"{mj.stats['train']}, detrains {mj.stats['detrain']}")
    for pc_name, pc in (("init", PC_INIT), ("init2", PC_INIT2), ("pass", PC_PASS),
                        ("reuse", PC_REUSE), ("stream", PC_STREAM)):
        rd = [mj.rdp.get(mj.signature(pc, h)) for h in (False, True)]
        if rd != [None, None]:
            print(f"  RDP[{pc_name} pc] miss/hit: {rd[0]} / {rd[1]}")
    if lazy_check:
        for bypass in (True, False):
            i = check_lazy(stream, sets, ways, bypass)
            print(f"  lazy aging (bypass={bypass}): "
                  + ("identical decisions" if i < 0 else f"differs at access {i}"))
    return rates


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawTextHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in ("micro", "log", "storage"):
        c = sub.add_parser(name)
        c.add_argument("--sets", type=int, default=2048)
        c.add_argument("--ways", type=int, default=16)
        if name == "log":
            c.add_argument("log")
        if name != "storage":
            c.add_argument("--check-lazy", action="store_true")
        if name == "micro":
            c.add_argument("--passes", type=int, default=6)
    args = p.parse_args()

    if args.cmd == "storage":
        total = 0
        for name, n, bits in Mockingjay(args.sets, args.ways).storage_bits():
            total += n * bits
            print(f"{name:<26} {n:>6} x {bits:>2} bit = {n * bits / 8192:7.2f} KB")
        print(f"{'total':<26} {total / 8192:27.2f} KB")
        return 0

    if args.cmd == "micro":
        for pattern in ("fit", "thrash", "mix"):
            report(pattern, micro_stream(pattern, args.passes), args.sets,
                   args.ways, args.check_lazy)
        return 0

    stream = []
    with open(args.log) as f:
        for line in f:
            m = FILL_RE.search(line)
            if m:
                stream.append((int(m.group(3), 16), int(m.group(4), 16)))
    report(args.log, stream, args.sets, args.ways, args.check_lazy)
    return 0


if __name__ == "__main__":
    sys.exit(main())
