#!/usr/bin/env python3
"""Install the Mockingjay replacement policy into a gem5 v23 source tree.

Copies mockingjay_rp.{hh,cc} and registers MockingjayRP and the debug flag
Mockingjay in ReplacementPolicies.py and the SConscript. Run
install_hawkeye.py first (it also applies the gem5 fixes that both policies
need). Safe to run more than once.

Usage: python3 install_mockingjay.py <gem5 dir> [<this repo's gem5 dir>]
"""

import shutil
import sys
from pathlib import Path

PY_CLASS = '''

class MockingjayRP(BaseReplacementPolicy):
    type = "MockingjayRP"
    cxx_class = "gem5::replacement_policy::Mockingjay"
    cxx_header = "mem/cache/replacement_policies/mockingjay_rp.hh"

    # Every other parameter (sampled sets, RDP size, INF_RD, ETR width) is
    # derived from the geometry, as in the ChampSim code.
    num_sets = Param.Unsigned("Number of sets in the cache")
    num_ways = Param.Unsigned("Associativity of the cache")
    block_size = Param.Unsigned(64, "Cache line size in bytes")
    inst_no_predict = Param.Bool(
        False,
        "Insert instruction-fetch lines with ETR 0 and keep their fetch "
        "addresses out of the sampled cache (not in the paper)",
    )
'''


def main():
    gem5 = Path(sys.argv[1]).expanduser()
    src = Path(sys.argv[2] if len(sys.argv) > 2 else Path(__file__).parent)
    rp_dir = gem5 / "src/mem/cache/replacement_policies"
    for name in ("mockingjay_rp.hh", "mockingjay_rp.cc"):
        shutil.copy(src / "src/mem/cache/replacement_policies" / name, rp_dir)

    py = rp_dir / "ReplacementPolicies.py"
    text = py.read_text()
    assert "class HawkeyeRP" in text, "run install_hawkeye.py first"
    if "\n\nclass MockingjayRP" in text:
        head, tail = text.split("\n\nclass MockingjayRP", 1)
        # Drop the old MockingjayRP class (up to the next class, if any).
        rest = tail.split("\n\nclass ", 1)
        text = head + ("\n\nclass " + rest[1] if len(rest) > 1 else "")
    py.write_text(text.rstrip("\n") + "\n" + PY_CLASS)

    sc = rp_dir / "SConscript"
    text = sc.read_text()
    if "'MockingjayRP'" not in text:
        text = text.replace("'HawkeyeRP'])", "'HawkeyeRP', 'MockingjayRP'])")
        text = text.replace(
            "Source('lru_rp.cc')", "Source('lru_rp.cc')\nSource('mockingjay_rp.cc')"
        )
        text = text.replace("DebugFlag('Hawkeye')",
                            "DebugFlag('Hawkeye')\nDebugFlag('Mockingjay')")
        assert ("'MockingjayRP'" in text and "mockingjay_rp.cc" in text
                and "DebugFlag('Mockingjay')" in text)
        sc.write_text(text)
    print("Mockingjay installed into", rp_dir)


if __name__ == "__main__":
    main()
