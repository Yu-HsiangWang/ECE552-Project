#!/bin/bash
# Run every (benchmark, policy) pair on the EC2 instance (8 vCPU, 15 GB).
#
# Usage: run_all_spec.sh [fast_forward] [warmup] [measure] [tag]
#   default: 1B fast-forward, 50M detailed warmup, 200M measured (as in the
#   Hawkeye paper's 50M warmup + 200M measurement)
# Output: ~/hawkeye/out/<benchmark>/<policy>_<tag>/
#
# Memory: the instance has no swap, and when it ran out of memory the network
# went down and the instance hung (10-30). Each run has a memory cap, so only
# that run is killed, and the pools below keep the total under ~14 GB.
# Native footprints: mcf_s 2.6 GB; omnetpp_s, xalancbmk_s 0.3 GB; gcc_r,
# deepsjeng_r, xz_r ~1 GB. gcc_s, cactuBSSN_s and deepsjeng_s need ~7 GB and
# xz_s >15 GB, so the rate versions of gcc, deepsjeng and xz are used, and
# cactuBSSN_s (streaming, every LLC access misses) is left out.
# Runs whose log already says "measure done" are skipped.

FF=${1:-1000000000}
WARMUP=${2:-50000000}
MEASURE=${3:-200000000}
export TAG=${4:-main}

MEDIUM="605.mcf_s"
LIGHT="620.omnetpp_s 623.xalancbmk_s 502.gcc_r 531.deepsjeng_r 557.xz_r"
POLICIES="LRU SRRIP BRRIP DRRIP SHiP Hawkeye"

jobs() {
    for b in $1; do
        for rp in $POLICIES; do
            grep -qs "measure done" ~/hawkeye/out/$b/${rp}_$TAG/log.txt || echo "$b $rp"
        done
    done
}

run_pool() {
    xargs -P "$1" -L 1 env MEM_MAX="$2" bash -c \
        'bash ~/hawkeye/scripts/run_spec.sh "$0" "$1" '"$FF $WARMUP $MEASURE"' && echo "done $0 $1" || echo "FAILED $0 $1"'
}

jobs "$MEDIUM" | run_pool 2 4G &
jobs "$LIGHT" | run_pool 5 3G &
wait
