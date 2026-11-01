#!/usr/bin/env python3
"""Install the Hawkeye replacement policy into a gem5 v23 source tree.

Copies hawkeye_rp.{hh,cc} and registers HawkeyeRP in ReplacementPolicies.py
and the SConscript. Also fixes two gem5 problems (see below): x86-64
newfstatat in SE mode, and software prefetches that lose their PC.
Safe to run more than once.

Usage: python3 install_hawkeye.py <gem5 dir> [<this repo's gem5 dir>]
"""

import shutil
import sys
from pathlib import Path

PY_CLASS = '''

class HawkeyeRP(BaseReplacementPolicy):
    type = "HawkeyeRP"
    cxx_class = "gem5::replacement_policy::Hawkeye"
    cxx_header = "mem/cache/replacement_policies/hawkeye_rp.hh"

    # Defaults follow the authors' CRC2 code. The ISCA 2016 paper uses
    # predictor_entries = 8192 and counter_bits = 3.
    num_sets = Param.Unsigned("Number of sets in the cache")
    block_size = Param.Unsigned(64, "Cache line size in bytes")
    num_rrpv_bits = Param.Unsigned(3, "Bits per RRPV")
    num_sampled_sets = Param.Unsigned(64, "Sets observed by OPTgen")
    optgen_vector_size = Param.Unsigned(
        128, "Occupancy vector length (8x the associativity)"
    )
    optgen_capacity = Param.Unsigned(
        14, "Lines OPT may keep per set (CRC2 uses ways - 2)"
    )
    timer_size = Param.Unsigned(1024, "Range of the per-set access timer")
    sampler_entries = Param.Unsigned(2800, "Sampler entries")
    sampler_ways = Param.Unsigned(8, "Sampler associativity")
    predictor_entries = Param.Unsigned(2048, "Predictor table entries")
    counter_bits = Param.Unsigned(5, "Bits per predictor counter")
    upper_eviction_refresh = Param.Unsigned(
        0,
        "When the upper cache evicts its copy of a line, refresh no line (0), "
        "lines predicted cache-friendly (1), or every line (2) "
        "(not in the paper; see hawkeye_rp.cc)",
    )
'''


def main():
    gem5 = Path(sys.argv[1]).expanduser()
    src = Path(sys.argv[2] if len(sys.argv) > 2 else Path(__file__).parent)
    rp_dir = gem5 / "src/mem/cache/replacement_policies"
    for name in ("hawkeye_rp.hh", "hawkeye_rp.cc"):
        shutil.copy(src / "src/mem/cache/replacement_policies" / name, rp_dir)

    py = rp_dir / "ReplacementPolicies.py"
    text = py.read_text()
    # The class is appended at the end, so a reinstall replaces it.
    text = text.split("\n\nclass HawkeyeRP")[0]
    py.write_text(text.rstrip("\n") + "\n" + PY_CLASS)

    sc = rp_dir / "SConscript"
    text = sc.read_text()
    if "'HawkeyeRP'" not in text:
        text = text.replace("'WeightedLRURP'])", "'WeightedLRURP', 'HawkeyeRP'])")
        text = text.replace(
            "Source('fifo_rp.cc')", "Source('fifo_rp.cc')\nSource('hawkeye_rp.cc')"
        )
        text = text.replace(
            "GTest(", "DebugFlag('Hawkeye')\n\nGTest(", 1
        )
        assert "'HawkeyeRP'" in text and "hawkeye_rp.cc" in text
        sc.write_text(text)
    print("Hawkeye installed into", rp_dir)

    # gem5 v23 serves x86-64 newfstatat with the generic Linux stat layout,
    # so st_mode lands at the wrong offset. glibc's fstat uses newfstatat,
    # opendir() then sees "not a directory", and omnetpp (NED folder scan)
    # and gcc (include dirs) fail. The x86-64 layout is tgt_stat64.
    tbl = gem5 / "src/arch/x86/linux/syscall_tbl64.cc"
    old = '{ 262, "newfstatat", newfstatatFunc<X86Linux64> }'
    new = '{ 262, "newfstatat", fstatat64Func<X86Linux64> }'
    text = tbl.read_text()
    if old in text:
        tbl.write_text(text.replace(old, new))
        print("patched newfstatat in", tbl)

    # On a software-prefetch miss, the cache answers the CPU at once and
    # sends a copy of the request down, but the copy has no PC. The LLC then
    # sees these prefetches without a PC, so PC-based policies (Hawkeye,
    # SHiP) put them all under one signature. 620.omnetpp_s issues many of
    # them (28% of its LLC accesses). Keep the PC on the copy.
    cache = gem5 / "src/mem/cache/cache.cc"
    old = """                                                    pkt->req->requestorId());
            pf = new Packet(req, pkt->cmd);"""
    new = """                                                    pkt->req->requestorId());
            if (pkt->req->hasPC())
                req->setPC(pkt->req->getPC());
            pf = new Packet(req, pkt->cmd);"""
    text = cache.read_text()
    if old in text:
        cache.write_text(text.replace(old, new))
        print("patched software-prefetch PC in", cache)


if __name__ == "__main__":
    main()
