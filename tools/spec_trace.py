#!/usr/bin/env python3
"""Offline analyses of gem5 LLC traces of SPEC CPU2017 runs.

The traces come from run_final.sh: a debug trace of the LLC replacement
policy from the end of the fast-forward, i.e. the 50M-instruction warmup and
the 200M measured instructions. Only demand misses after the warmup (the tick
where gem5 reset its statistics) are counted; the warmup warms the models.

  python3 spec_trace.py mockingjay <run dir> [--sets N] [--ways 16]
      <run dir> holds trace.txt.gz, log.txt and stats.txt of a Mockingjay
      run. Replays the LLC events (demand accesses, L2 writebacks, clean
      eviction notices) through
        - the Mockingjay reference model with true bypass (the paper's design)
          and without bypass (our gem5 version),
        - LRU, which also counts writebacks and clean-eviction notices as
          uses, as gem5's LRU does,
        - Belady's OPT on the demand accesses alone,
      and reports demand misses in the measured region. The model without
      bypass is a sanity check against gem5's own Mockingjay misses. Also
      explains the misses that Mockingjay has and LRU does not: for each one,
      how Mockingjay last evicted the line (overdue, predicted not reused,
      reused furthest, inserted by a writeback, or bypassed), both for the
      model and for gem5's own victims, and how many accesses to the set
      passed since the line's previous use.

  python3 spec_trace.py hawkeye <run dir>
      <run dir> of a Hawkeye run. Compares every prediction gem5's Hawkeye
      made in the measured region with the decision of Belady's OPT on the
      same demand stream (does OPT keep the line until its next use?), split
      into instruction and data accesses, and reports LRU and OPT misses.
      Explains the misses that Hawkeye has and LRU does not by Hawkeye's
      prediction at the line's previous access, and counts those that come
      from PCs that never access a sampled set (whose counters cannot be
      trained); lists the PCs most often predicted averse when OPT keeps the
      line.

The LLC demand stream hardly depends on the LLC policy (across policies the
LLC sees the same number of accesses within 0.3%), so replaying one run's
stream through another policy is a fair comparison.
"""

import argparse
import gzip
import os
import re
import sys
from collections import Counter, OrderedDict, defaultdict
import multiprocessing

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from hawkeye_ref import belady_hits  # noqa: E402
from mockingjay_ref import Mockingjay  # noqa: E402

TICK_RE = re.compile(r"^\s*(\d+): ")
MJ_RE = re.compile(r"MJ (fill|hit|wbfill|wbhit|cleanevict) set \d+ way \d+ "
                   r"addr (0x[0-9a-f]+|0)(?: pc (0x[0-9a-f]+|0))?")
HK_ACC_RE = re.compile(r"(fill|hit) set \d+ addr (0x[0-9a-f]+|0) "
                       r"pc (0x[0-9a-f]+|0): (friendly|averse), .* inst (\d)")
HK_OTHER_RE = re.compile(r"(writeback|cleanevict) set \d+ way \d+ addr (0x[0-9a-f]+|0)"
                         r"(?:: (hit|insert))?")

DEMAND, WRITEBACK, CLEAN = 0, 1, 2


def warmup_end(run):
    """Tick where gem5 reset its statistics; -1 for a run without a warmup
    (the check runs from the start), where every access is measured."""
    with open(os.path.join(run, "log.txt")) as f:
        for line in f:
            m = re.search(r"Warmup: exiting @ tick (\d+)", line)
            if m:
                return int(m.group(1))
    return -1


def gem5_stats(run):
    out = {}
    with open(os.path.join(run, "stats.txt")) as f:
        for line in f:
            m = re.match(r"system\.llc\.(demandMisses|demandAccesses)::total\s+(\d+)", line)
            if m:
                out[m.group(1)] = int(m.group(2))
    return out


def read_trace(run, policy):
    """Returns parallel lists: kind, block address, pc, measured?, and for
    Hawkeye traces also friendly?, inst? and gem5 hit? (None for events that
    are not demand accesses)."""
    end = warmup_end(run)
    kind, addr, pc, meas, friendly, inst, ghit = [], [], [], [], [], [], []
    with gzip.open(os.path.join(run, "trace.txt.gz"), "rt") as f:
        for line in f:
            t = TICK_RE.match(line)
            if not t:
                continue
            if policy == "mockingjay":
                m = MJ_RE.search(line)
                if not m:
                    continue
                k = m.group(1)
                kind.append(DEMAND if k in ("fill", "hit") else
                            CLEAN if k == "cleanevict" else WRITEBACK)
                addr.append(int(m.group(2), 16))
                pc.append(int(m.group(3), 16) if m.group(3) else 0)
            else:
                m = HK_ACC_RE.search(line)
                if m:
                    kind.append(DEMAND)
                    addr.append(int(m.group(2), 16))
                    pc.append(int(m.group(3), 16))
                    friendly.append(m.group(4) == "friendly")
                    inst.append(m.group(5) == "1")
                    ghit.append(m.group(1) == "hit")
                else:
                    m = HK_OTHER_RE.search(line)
                    if not m:
                        continue
                    kind.append(WRITEBACK if m.group(1) == "writeback" else CLEAN)
                    addr.append(int(m.group(2), 16))
                    pc.append(0)
                    # "wb" marks a writeback that inserted the line (RRPV 7)
                    friendly.append("wb" if m.group(3) == "insert" else None)
                    inst.append(False)
                    ghit.append(None)
            meas.append(int(t.group(1)) > end)
    return kind, addr, pc, meas, friendly, inst, ghit


# ----------------------------------------------------------------------
# policies on the trace (globals are shared with the worker processes)
# ----------------------------------------------------------------------

T = None


# How a line left the cache, for the misses that the no-bypass model has
# and LRU does not. 0 means a hit.
HIT, FIRST, BYPASSED, WBINS, OVERDUE, NOREUSE, FURTHEST = range(7)
CAUSES = {FIRST: "first use in the trace", BYPASSED: "bypassed",
          WBINS: "inserted by a writeback (ETR -15), not used since",
          OVERDUE: "evicted overdue (ETR < 0)",
          NOREUSE: "evicted as not reused (ETR = 15)",
          FURTHEST: "evicted as reused furthest (0 <= ETR < 15)"}


class TracingMockingjay(Mockingjay):
    """Remembers how each line left the cache, to explain misses."""

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.left = {}     # block -> cause code
        self.wb_only = set()   # inserted by a writeback, no demand use since

    def find_victim(self, s, pc, writeback, prefetch):
        w = super().find_victim(s, pc, writeback, prefetch)
        if w is None:
            return None
        blk = self.blocks[s][w]
        if blk is not None:
            e = self.get_etr(s, w)
            self.left[blk] = (WBINS if blk in self.wb_only else
                              OVERDUE if e < 0 else
                              NOREUSE if e >= self.inf_etr else FURTHEST)
        return w


def run_mockingjay(bypass):
    """Returns (measured misses, bypassed measured misses, one cause code per
    measured demand access)."""
    kind, addr, pc, meas = T["kind"], T["addr"], T["pc"], T["meas"]
    m = TracingMockingjay(T["sets"], T["ways"], bypass=bypass, lazy=True)
    misses, bypassed = 0, 0
    causes = bytearray()
    for i in range(len(kind)):
        k = kind[i]
        if k == CLEAN:
            continue
        a = addr[i]
        blk = a >> 6
        if k == WRITEBACK:
            hit, way = m.access(a, 0, writeback=True)
            if not hit and way is not None:
                m.wb_only.add(blk)
            continue
        m.wb_only.discard(blk)
        cause = m.left.get(blk, FIRST)
        hit, way = m.access(a, pc[i])
        if way is None:
            m.left[blk] = BYPASSED
        if meas[i]:
            causes.append(HIT if hit else cause)
            if not hit:
                misses += 1
                bypassed += way is None
    return misses, bypassed, causes


GEM5_MJ_RE = re.compile(r"^\s*(\d+): .*MJ (fill|hit|wbfill|wbhit|victim) set (\d+) "
                        r"way (\d+)(?: addr (0x[0-9a-f]+|0))?.* etr (-?\d+)")


def gem5_mockingjay_causes(run, inf_etr):
    """Same as the cause codes of run_mockingjay, but for gem5's own run:
    reads gem5's victims (and their ETR at eviction) from the trace. Also
    returns, per measured demand access, the number of demand accesses to
    its set since the line's previous demand use (-1 if none)."""
    end = warmup_end(run)
    where = {}             # (set, way) -> block
    left, wb_only = {}, set()
    causes = bytearray()
    set_count, last_use, dist = Counter(), {}, []
    with gzip.open(os.path.join(run, "trace.txt.gz"), "rt") as f:
        for line in f:
            m = GEM5_MJ_RE.match(line)
            if not m:
                continue
            k, sw = m.group(2), (int(m.group(3)), int(m.group(4)))
            if k == "victim":
                blk = where.pop(sw, None)
                if blk is not None:
                    e = int(m.group(6))
                    left[blk] = (WBINS if blk in wb_only else
                                 OVERDUE if e < 0 else
                                 NOREUSE if e >= inf_etr else FURTHEST)
                continue
            blk = int(m.group(5), 16) >> 6
            where[sw] = blk
            if k == "wbfill":
                wb_only.add(blk)
            elif k in ("fill", "hit"):
                wb_only.discard(blk)
                s = sw[0]
                if int(m.group(1)) > end:
                    causes.append(HIT if k == "hit" else left.get(blk, FIRST))
                    dist.append(set_count[s] - last_use[blk] if blk in last_use else -1)
                set_count[s] += 1
                last_use[blk] = set_count[s]
    return causes, dist


def run_lru():
    """Returns (measured misses, one flag per measured demand access)."""
    kind, addr, meas, sets, ways = T["kind"], T["addr"], T["meas"], T["sets"], T["ways"]
    cache = defaultdict(OrderedDict)
    misses = 0
    flags = bytearray()
    for i in range(len(kind)):
        blk = addr[i] >> 6
        lines = cache[blk & (sets - 1)]
        if blk in lines:
            lines.move_to_end(blk)
            if kind[i] == DEMAND and meas[i]:
                flags.append(0)
            continue
        if kind[i] == CLEAN:
            continue            # a notice for a line the LLC does not hold
        if len(lines) == ways:
            lines.popitem(last=False)
        lines[blk] = True
        if kind[i] == DEMAND and meas[i]:
            misses += 1
            flags.append(1)
    return misses, flags


def demand_stream():
    sets = T["sets"]
    idx = [i for i, k in enumerate(T["kind"]) if k == DEMAND]
    stream = [((T["addr"][i] >> 6) & (sets - 1), T["addr"][i] >> 6) for i in idx]
    return idx, stream


def run_opt():
    idx, stream = demand_stream()
    hits = belady_hits(stream, T["ways"])
    return sum(1 for j, i in enumerate(idx) if T["meas"][i] and not hits[j])


def job(name):
    if name == "gem5":
        return name, gem5_mockingjay_causes(T["run"], T["inf_etr"])
    if name == "bypass":
        return name, run_mockingjay(True)
    if name == "nobypass":
        return name, run_mockingjay(False)
    if name == "lru":
        return name, run_lru()
    return name, run_opt()


def mockingjay(args):
    global T
    kind, addr, pc, meas, _, _, _ = read_trace(args.run, "mockingjay")
    T = dict(kind=kind, addr=addr, pc=pc, meas=meas, sets=args.sets, ways=args.ways,
             run=args.run, inf_etr=Mockingjay(args.sets, args.ways).inf_etr)
    n_meas = sum(1 for k, m in zip(kind, meas) if k == DEMAND and m)
    # fork, so that the workers share the trace (T) without copying it
    with multiprocessing.get_context("fork").Pool(4) as p:
        r = dict(p.map(job, ["bypass", "nobypass", "lru", "opt", "gem5"]))
    st = gem5_stats(args.run)
    seen, first = set(), 0
    for k, a, m in zip(kind, addr, meas):
        if k != CLEAN and a >> 6 not in seen:
            seen.add(a >> 6)
            first += k == DEMAND and m
    print(f"run {args.run}")
    print(f"events {len(kind)}: demand {kind.count(DEMAND)}, writebacks "
          f"{kind.count(WRITEBACK)}, clean-eviction notices {kind.count(CLEAN)}")
    print(f"measured demand accesses: trace {n_meas}, gem5 {st.get('demandAccesses')}")
    print(f"  lines in the trace {len(seen)} (the LLC holds {args.sets * args.ways}); "
          f"measured accesses that are a line's first use in the trace {first}")
    rows = [("gem5 Mockingjay (no bypass)", st.get("demandMisses")),
            ("model, no bypass", r["nobypass"][0]),
            ("model, true bypass", r["bypass"][0]),
            ("LRU (+ writebacks, notices)", r["lru"][0]),
            ("OPT (demand only)", r["opt"])]
    for name, v in rows:
        print(f"  {name:<30} {v:>10}  ({100 * v / n_meas:.2f}%)")
    nb, b = r["nobypass"][0], r["bypass"][0]
    print(f"  true bypass removes {nb - b} misses ({100 * (nb - b) / nb:.2f}% of "
          f"the no-bypass misses); bypassed fills {r['bypass'][1]}")
    lru = r["lru"][1]
    gem5_causes, gem5_dist = r["gem5"]
    for who, causes in (("the model without bypass", r["nobypass"][2]),
                        ("gem5's Mockingjay", gem5_causes)):
        assert len(causes) == len(lru) == n_meas
        extra = Counter(c for c, l in zip(causes, lru) if c != HIT and not l)
        tot = sum(extra.values())
        print(f"  misses of {who} that LRU hits, by how Mockingjay had "
              "evicted the line:")
        for c, n in extra.most_common():
            print(f"    {CAUSES[c]:<52} {n:>9} ({100 * n / max(tot, 1):.1f}%)")
        print(f"    total {tot}; LRU misses that Mockingjay hits: "
              f"{sum(1 for c, l in zip(causes, lru) if l and c == HIT)}")
    bins = Counter()
    for c, l, d in zip(gem5_causes, lru, gem5_dist):
        if c not in (HIT, WBINS) and not l and d >= 0:
            bins["<= 16" if d <= 16 else "17-127" if d < 128 else ">= 128"] += 1
    bt = sum(bins.values())
    print("    (not inserted by a writeback) demand accesses to the set since the "
          "line's previous use: " + ", ".join(
              f"{b} {100 * bins[b] / max(bt, 1):.1f}%" for b in ("<= 16", "17-127", ">= 128")))
    return 0


def hawkeye(args):
    global T
    kind, addr, pc, meas, friendly, inst, ghit = read_trace(args.run, "hawkeye")
    T = dict(kind=kind, addr=addr, pc=pc, meas=meas, sets=args.sets, ways=args.ways)
    idx, stream = demand_stream()
    hits = belady_hits(stream, args.ways)
    # OPT keeps the line until its next use iff that next use hits
    nxt = {}
    keep = [False] * len(stream)
    for j in range(len(stream) - 1, -1, -1):
        blk = stream[j][1]
        n = nxt.get(blk)
        keep[j] = n is not None and hits[n]
        nxt[blk] = j
    conf = Counter()
    by_pc = Counter()
    pc_n, pc_keep, pc_friendly = Counter(), Counter(), Counter()
    for j, i in enumerate(idx):
        if not meas[i]:
            continue
        cls = "inst" if inst[i] else "data"
        pred = "friendly" if friendly[i] else "averse"
        opt = "keep" if keep[j] else "evict"
        conf[(cls, pred, opt)] += 1
        pc_n[pc[i]] += 1
        pc_keep[pc[i]] += keep[j]
        pc_friendly[pc[i]] += pred == "friendly"
        if pred == "averse" and opt == "keep":
            by_pc[(cls, pc[i])] += 1
    opt_misses = sum(1 for j, i in enumerate(idx) if meas[i] and not hits[j])
    lru_misses, lru_flags = run_lru()
    # The measured misses of gem5's Hawkeye that LRU hits, by what Hawkeye
    # last did with the line: its prediction at the line's previous demand
    # access (and whether OPT kept the line from there), or a writeback that
    # inserted it with RRPV 7.
    last, lost, won = {}, Counter(), Counter()
    # PCs with at least one demand access to a sampled set (64 sets, every
    # 32nd on the diagonal, as in hawkeye_rp.cc): only they can be trained
    stride = args.sets // 64
    trained = {pc[i] for i in idx
               if (addr[i] >> 6) % stride == ((addr[i] >> 6) & (args.sets - 1)) // stride % stride}
    unsampled = Counter()
    # demand accesses to the set between the line's previous use and the miss
    set_count, last_use, dist = Counter(), {}, Counter()
    j = f = 0
    for i in range(len(kind)):
        blk = addr[i] >> 6
        if kind[i] == WRITEBACK:
            if friendly[i] == "wb":
                last[blk] = ("inserted by a writeback", None, None)
            continue
        if kind[i] != DEMAND:
            continue
        if meas[i]:
            cls = "inst" if inst[i] else "data"
            if not ghit[i] and not lru_flags[f]:
                how, pj, ppc = last.get(blk, ("first use in the trace", None, None))
                if how == "predicted averse" and ppc not in trained:
                    unsampled[cls] += 1
                if pj is not None:
                    how = f"{how}, OPT {'keeps' if keep[pj] else 'evicts'} it"
                lost[(cls, how)] += 1
                if blk in last_use:
                    d = set_count[blk & (args.sets - 1)] - last_use[blk]
                    dist[(cls, "<= 16" if d <= 16 else "17-127" if d < 128
                          else ">= 128")] += 1
            elif ghit[i] and lru_flags[f]:
                won[cls] += 1
            f += 1
        last[blk] = ("predicted friendly" if friendly[i] else "predicted averse", j, pc[i])
        set_count[blk & (args.sets - 1)] += 1
        last_use[blk] = set_count[blk & (args.sets - 1)]
        j += 1
    st = gem5_stats(args.run)
    n_meas = sum(1 for i in idx if meas[i])
    print(f"run {args.run}")
    print(f"measured demand accesses: trace {n_meas}, gem5 {st.get('demandAccesses')}")
    print(f"  gem5 Hawkeye misses        {st.get('demandMisses'):>9} ({100 * st.get('demandMisses') / n_meas:.2f}%)")
    print(f"  LRU (+ writebacks, notices) {lru_misses:>8} ({100 * lru_misses / n_meas:.2f}%)")
    print(f"  OPT (demand only)          {opt_misses:>9} ({100 * opt_misses / n_meas:.2f}%)")
    print("  Hawkeye prediction vs OPT's decision (measured accesses):")
    for cls in ("data", "inst"):
        tot = sum(v for k, v in conf.items() if k[0] == cls)
        if not tot:
            continue
        right = conf[(cls, "friendly", "keep")] + conf[(cls, "averse", "evict")]
        print(f"    {cls}: {tot} accesses, agree {100 * right / tot:.1f}%; "
              f"averse but OPT keeps {conf[(cls, 'averse', 'keep')]} "
              f"({100 * conf[(cls, 'averse', 'keep')] / tot:.1f}%), "
              f"friendly but OPT evicts {conf[(cls, 'friendly', 'evict')]} "
              f"({100 * conf[(cls, 'friendly', 'evict')] / tot:.1f}%)")
        keep_tot = conf[(cls, 'friendly', 'keep')] + conf[(cls, 'averse', 'keep')]
        print(f"      OPT keeps {keep_tot} ({100 * keep_tot / tot:.1f}%); "
              f"Hawkeye predicts friendly {conf[(cls, 'friendly', 'keep')] + conf[(cls, 'friendly', 'evict')]}")
    print("  misses of gem5's Hawkeye that LRU hits, by what Hawkeye last did "
          "with the line:")
    for cls in ("data", "inst"):
        tot = sum(v for k, v in lost.items() if k[0] == cls)
        print(f"    {cls}: {tot} (LRU misses that Hawkeye hits: {won[cls]})")
        for (c, how), n in sorted(lost.items(), key=lambda kv: -kv[1]):
            if c == cls:
                print(f"      {how:<40} {n:>8} ({100 * n / tot:.1f}%)")
        print(f"      of the 'predicted averse' ones, {unsampled[cls]} come from PCs "
              "that never access a sampled set in the trace")
        dt = sum(v for k, v in dist.items() if k[0] == cls)
        print("      demand accesses to the set since the line's previous use: "
              + ", ".join(f"{b} {100 * dist[(cls, b)] / max(dt, 1):.1f}%"
                          for b in ("<= 16", "17-127", ">= 128")))
    top = by_pc.most_common(10)
    tot = sum(by_pc.values())
    print(f"  'averse but OPT keeps' by PC: {len(by_pc)} PCs, top 10 hold "
          f"{100 * sum(c for _, c in top) / max(tot, 1):.1f}%")
    for (cls, p), c in top:
        print(f"    {cls} pc {p:#x}: {c} of {pc_n[p]} accesses; OPT keeps "
              f"{100 * pc_keep[p] / pc_n[p]:.0f}%, Hawkeye predicts friendly "
              f"{100 * pc_friendly[p] / pc_n[p]:.0f}%")
    return 0


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("policy", choices=["mockingjay", "hawkeye"])
    p.add_argument("run")
    p.add_argument("--sets", type=int, default=2048)
    p.add_argument("--ways", type=int, default=16)
    args = p.parse_args()
    return mockingjay(args) if args.policy == "mockingjay" else hawkeye(args)


if __name__ == "__main__":
    sys.exit(main())
