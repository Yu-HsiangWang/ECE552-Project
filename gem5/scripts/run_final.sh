#!/bin/bash
# Runs added for the final report (2026-11-17).
#
#  1. Microbenchmarks, 6 passes, with debug traces for the reference-model
#     checks: Hawkeye and HawkeyeI (flag Hawkeye), Mockingjay (flag
#     Mockingjay); MockingjayI without a trace.        -> ~/hawkeye/micro_dbg
#  2. SPEC CPU2017 from the start (30M instructions, no fast-forward), traced,
#     to run the same checks on real programs.          -> <bench>/<rp>_check
#  3. SPEC CPU2017 with the usual 1B fast-forward, 50M warmup, 200M measured,
#     and an LLC trace from the end of the fast-forward, for the offline
#     analyses: Mockingjay at 2 MB on all six benchmarks, at 1 MB and 4 MB on
#     mcf, at 4 MB on xalancbmk; Hawkeye at 2 MB on omnetpp.
#                                                       -> <bench>/<rp>_trace*
#  4. Microbenchmarks, 20 passes, every policy.         -> ~/hawkeye/micro_p20
#
# Usage: run_final.sh            (runs everything; finished jobs are skipped)
# Pools as in run_all_spec.sh: mcf 2 at a time (4 GB cap), the rest 5 (3 GB).

GEM5=~/gem5/build/X86/gem5.opt
CONFIG=~/hawkeye/configs/hk_se.py
BIN=~/hawkeye/micro/llc_patterns
FF=1000000000
WARMUP=50000000
MEASURE=200000000
CHECK=30000000

micro() {  # micro <dir> <pattern> <passes> <policy> [debug flag]
    local out=~/hawkeye/$1/$2/$4 p=$3 args
    case $2 in
        fit)    args="fit 1024 $p" ;;
        thrash) args="thrash 3072 $p" ;;
        mix)    args="mix 1024 $((4096 * p)) $p" ;;
    esac
    grep -qs "last active thread context" "$out/log.txt" && return 0
    mkdir -p "$out"
    $GEM5 -q --outdir="$out" ${5:+--debug-flags=$5 --debug-file=trace.txt.gz} \
        "$CONFIG" --cmd="$BIN" --options="$args" --rp="$4" > "$out/log.txt" 2>&1
    grep -qs "last active thread context" "$out/log.txt"
}

spec() {  # spec <bench> <policy> <llc> <ff> <warmup> <measure> <tag> [flag]
    grep -qs "measure done" ~/hawkeye/out/$1/$2_$7/log.txt && return 0
    TAG=$7 LLC_SIZE=$3 DEBUG=$8 bash ~/hawkeye/scripts/run_spec.sh \
        "$1" "$2" "$4" "$5" "$6"
}

if [ "$1" = job ]; then
    shift
    kind=$1
    shift
    if "$kind" "$@"; then echo "done $kind $*"; else echo "FAILED $kind $*"; fi
    exit 0
fi

jobs_mcf() {
    for llc in 2MB 4MB 1MB; do
        tag=trace
        [ $llc != 2MB ] && tag=trace_llc$llc
        echo "spec 605.mcf_s Mockingjay $llc $FF $WARMUP $MEASURE $tag Mockingjay"
    done
}

jobs_light() {
    for pat in fit thrash mix; do
        echo "micro micro_dbg $pat 6 Hawkeye Hawkeye"
        echo "micro micro_dbg $pat 6 HawkeyeI Hawkeye"
        echo "micro micro_dbg $pat 6 Mockingjay Mockingjay"
        echo "micro micro_dbg $pat 6 MockingjayI"
    done
    for b in 502.gcc_r 620.omnetpp_s; do
        echo "spec $b Hawkeye 2MB 0 0 $CHECK check Hawkeye"
        echo "spec $b Mockingjay 2MB 0 0 $CHECK check Mockingjay"
    done
    echo "spec 502.gcc_r HawkeyeI 2MB 0 0 $CHECK check Hawkeye"
    for b in 620.omnetpp_s 623.xalancbmk_s 502.gcc_r 557.xz_r 531.deepsjeng_r; do
        echo "spec $b Mockingjay 2MB $FF $WARMUP $MEASURE trace Mockingjay"
    done
    echo "spec 623.xalancbmk_s Mockingjay 4MB $FF $WARMUP $MEASURE trace_llc4MB Mockingjay"
    echo "spec 620.omnetpp_s Hawkeye 2MB $FF $WARMUP $MEASURE trace Hawkeye"
    for pat in mix thrash fit; do
        for rp in LRU SRRIP BRRIP DRRIP SHiP Hawkeye HawkeyeI Mockingjay MockingjayI; do
            echo "micro micro_p20 $pat 20 $rp"
        done
    done
}

run_pool() {
    xargs -P "$1" -L 1 env MEM_MAX="$2" bash ~/hawkeye/scripts/run_final.sh job
}

mkdir -p ~/hawkeye/micro
gcc -O2 -static -o "$BIN" ~/hawkeye/tools/microbench/llc_patterns.c || exit 1
jobs_mcf | run_pool 2 4G &
jobs_light | run_pool 5 3G &
wait
echo "all done"
