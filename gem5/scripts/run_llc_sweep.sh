#!/bin/bash
# LLC-size sweep: one smaller and one larger LLC (16-way) on mcf, omnetpp and
# xalancbmk, with every policy of the main runs.
#
# Usage: run_llc_sweep.sh [fast_forward] [warmup] [measure]
#        SIZES / POLICIES env vars override the lists below,
#        e.g. POLICIES=HawkeyeI run_llc_sweep.sh
# Output: ~/hawkeye/out/<benchmark>/<policy>_llc<size>/
# Memory pools as in run_all_spec.sh. Runs whose log already says
# "measure done" are skipped.

FF=${1:-1000000000}
WARMUP=${2:-50000000}
MEASURE=${3:-200000000}

SIZES=${SIZES:-"1MB 4MB"}
POLICIES=${POLICIES:-"LRU SRRIP BRRIP DRRIP SHiP Hawkeye"}

jobs() {
    for s in $SIZES; do
        for b in $1; do
            for rp in $POLICIES; do
                grep -qs "measure done" ~/hawkeye/out/$b/${rp}_llc$s/log.txt ||
                    echo "$b $rp $s"
            done
        done
    done
}

run_pool() {
    xargs -P "$1" -L 1 env MEM_MAX="$2" bash -c \
        'TAG=llc$2 LLC_SIZE=$2 bash ~/hawkeye/scripts/run_spec.sh "$0" "$1" '"$FF $WARMUP $MEASURE"' && echo "done $0 $1 $2" || echo "FAILED $0 $1 $2"'
}

jobs "605.mcf_s" | run_pool 2 4G &
jobs "620.omnetpp_s 623.xalancbmk_s" | run_pool 5 3G &
wait
