#!/bin/bash
# Run every (benchmark, policy) pair on the EC2 instance (8 vCPU, 15 GB).
#
# Usage: run_all_spec.sh [fast_forward] [warmup] [measure] [tag]
#   default: 1B fast-forward, 50M detailed warmup, 200M measured (as in the
#   Hawkeye paper's 50M warmup + 200M measurement)
# Output: ~/hawkeye/out/<benchmark>/<policy>_<tag>/
#
# Memory: the instance has no swap, and when it ran out of memory the network
# went down and the instance hung (10-30). Benchmarks that need ~7 GB run one
# at a time in the heavy pool, the rest five at a time, and every run has a
# memory cap so only that run is killed. 657.xz_s (>15 GB) and
# 631.deepsjeng_s (7 GB) are replaced by their rate versions (~0.7 GB).
# Runs whose log already says "measure done" are skipped.

FF=${1:-1000000000}
WARMUP=${2:-50000000}
MEASURE=${3:-200000000}
export TAG=${4:-main}

HEAVY="607.cactuBSSN_s"
LIGHT="605.mcf_s 620.omnetpp_s 623.xalancbmk_s 531.deepsjeng_r 557.xz_r"
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

jobs "$HEAVY" | run_pool 1 8G &
jobs "$LIGHT" | run_pool 5 4G &
wait
