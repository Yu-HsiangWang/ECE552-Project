# Three-level cache system for the Hawkeye replication (gem5 v23, X86, SE mode).
#
# Follows Table 2 of Jain and Lin, ISCA 2016: 32 kB 4-way L1I/L1D, 256 kB 8-way
# L2, 2 MB 16-way LLC. Only the LLC replacement policy changes between runs.
#
# Example:
#   gem5.opt -d out hk_se.py --cmd=./mcf_s --options="inp.in" \
#       --rp=DRRIP --fast-forward=1000000000 --warmup=10000000 \
#       --measure=50000000
#
# With --fast-forward, an atomic CPU runs first (the caches still see its
# accesses), then an O3CPU takes over for the warmup and the measurement.

import argparse
import os

import m5
from m5.objects import *

parser = argparse.ArgumentParser()
parser.add_argument("--cmd", required=True, help="binary to run")
parser.add_argument("--options", default="", help="arguments to the binary")
parser.add_argument("--input", default="", help="file to use as stdin")
parser.add_argument("--rp", default="LRU", help="LLC replacement policy")
parser.add_argument("--llc-size", default="2MB")
parser.add_argument("--llc-assoc", type=int, default=16)
parser.add_argument("--fast-forward", type=int, default=0,
                    help="instructions to run on the atomic CPU first")
parser.add_argument("--warmup", type=int, default=0,
                    help="instructions to run before resetting stats")
parser.add_argument("--measure", type=int, default=0,
                    help="instructions to measure (0: run to completion)")
parser.add_argument("--mem-size", default="8GB")
parser.add_argument("--cpu-clock", default="2GHz")
args = parser.parse_args()

# LLC replacement policies. SHiP uses the PC signature (SHiP-PC).
POLICIES = {
    "LRU": LRURP,
    "Random": RandomRP,
    "SRRIP": RRIPRP,
    "BRRIP": BRRIPRP,
    "DRRIP": DRRIPRP,
    "SHiP": SHiPPCRP,
    "Hawkeye": HawkeyeRP,
}
if args.rp not in POLICIES:
    m5.fatal(f"unknown --rp {args.rp}; choose from {sorted(POLICIES)}")


class L1ICache(Cache):
    size = "32kB"
    assoc = 4
    tag_latency = 1
    data_latency = 1
    response_latency = 1
    mshrs = 8
    tgts_per_mshr = 20


class L1DCache(Cache):
    size = "32kB"
    assoc = 4
    tag_latency = 1
    data_latency = 1
    response_latency = 1
    mshrs = 16
    tgts_per_mshr = 20


class L2Cache(Cache):
    size = "256kB"
    assoc = 8
    tag_latency = 4
    data_latency = 6
    response_latency = 4
    mshrs = 32
    tgts_per_mshr = 12


class LLCache(Cache):
    size = args.llc_size
    assoc = args.llc_assoc
    tag_latency = 8
    data_latency = 12
    response_latency = 8
    mshrs = 64
    tgts_per_mshr = 12


system = System()
system.clk_domain = SrcClockDomain(clock=args.cpu_clock,
                                   voltage_domain=VoltageDomain())
system.mem_mode = "atomic" if args.fast_forward > 0 else "timing"
system.mem_ranges = [AddrRange(args.mem_size)]

system.cpu = X86AtomicSimpleCPU() if args.fast_forward > 0 else X86O3CPU()
system.cpu.icache = L1ICache()
system.cpu.dcache = L1DCache()
system.cpu.icache_port = system.cpu.icache.cpu_side
system.cpu.dcache_port = system.cpu.dcache.cpu_side

system.l2bus = L2XBar()
system.cpu.icache.mem_side = system.l2bus.cpu_side_ports
system.cpu.dcache.mem_side = system.l2bus.cpu_side_ports
system.l2cache = L2Cache()
system.l2cache.cpu_side = system.l2bus.mem_side_ports
# x86 page-table walkers share the L2 bus with the L1s (as in
# BaseCPU.addPrivateSplitL1Caches). A connected walker port is also needed
# for the CPU switch after a fast-forward.
system.cpu.mmu.connectWalkerPorts(system.l2bus.cpu_side_ports,
                                  system.l2bus.cpu_side_ports)

system.l3bus = L2XBar()
system.l2cache.mem_side = system.l3bus.cpu_side_ports
system.llc = LLCache()
from m5.util.convert import toMemorySize

llc_lines = toMemorySize(args.llc_size) // 64
llc_rp = POLICIES[args.rp]()
if args.rp == "DRRIP":
    # Set dueling with 32 sampled sets per policy, as in the RRIP paper
    # (see the DRRIPRP comment in ReplacementPolicies.py).
    llc_rp.constituency_size = llc_lines // (32 * args.llc_assoc)
    llc_rp.team_size = args.llc_assoc
elif args.rp == "Hawkeye":
    llc_rp.num_sets = llc_lines // args.llc_assoc
    # 8x history; OPT may keep ways - 2 lines, as in the CRC2 code.
    llc_rp.optgen_vector_size = 8 * args.llc_assoc
    llc_rp.optgen_capacity = args.llc_assoc - 2
system.llc.replacement_policy = llc_rp
system.llc.cpu_side = system.l3bus.mem_side_ports

system.membus = SystemXBar()
system.llc.mem_side = system.membus.cpu_side_ports
system.system_port = system.membus.cpu_side_ports

system.cpu.createInterruptController()
system.cpu.interrupts[0].pio = system.membus.mem_side_ports
system.cpu.interrupts[0].int_requestor = system.membus.cpu_side_ports
system.cpu.interrupts[0].int_responder = system.membus.mem_side_ports

system.mem_ctrl = MemCtrl()
system.mem_ctrl.dram = DDR4_2400_8x8()
system.mem_ctrl.dram.range = system.mem_ranges[0]
system.mem_ctrl.port = system.membus.mem_side_ports

process = Process(pid=100)
process.executable = args.cmd
process.cmd = [args.cmd] + args.options.split()
process.cwd = os.getcwd()
if args.input:
    process.input = args.input
system.workload = SEWorkload.init_compatible(args.cmd)
system.cpu.workload = process
system.cpu.createThreads()

# The detailed CPU that takes over after the fast-forward (as in
# configs/common/Simulation.py).
if args.fast_forward > 0:
    system.switch_cpu = X86O3CPU(switched_out=True, cpu_id=0)
    system.switch_cpu.workload = process
    system.switch_cpu.clk_domain = system.cpu.clk_domain
    system.switch_cpu.isa = system.cpu.isa
    system.switch_cpu.createThreads()

root = Root(full_system=False, system=system)
m5.instantiate()

cpu = system.cpu
if args.fast_forward > 0:
    system.cpu.scheduleInstStop(0, args.fast_forward, "fast-forward done")
    event = m5.simulate()
    print(f"Fast-forward: exiting @ tick {m5.curTick()} because "
          f"{event.getCause()}")
    if event.getCause() != "fast-forward done":
        m5.stats.dump()
        raise SystemExit(0)
    m5.switchCpus(system, [(system.cpu, system.switch_cpu)])
    cpu = system.switch_cpu

if args.warmup > 0:
    cpu.scheduleInstStop(0, args.warmup, "warmup done")
    event = m5.simulate()
    print(f"Warmup: exiting @ tick {m5.curTick()} because {event.getCause()}")
    if event.getCause() != "warmup done":
        m5.stats.dump()
        raise SystemExit(0)
    m5.stats.reset()

if args.measure > 0:
    cpu.scheduleInstStop(0, args.measure, "measure done")
event = m5.simulate()
print(f"Exiting @ tick {m5.curTick()} because {event.getCause()}")
