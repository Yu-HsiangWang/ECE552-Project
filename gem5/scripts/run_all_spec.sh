#!/bin/bash
# Run every (benchmark, policy) pair, 7 at a time, on the EC2 instance.
#
# Usage: run_all_spec.sh [fast_forward] [warmup] [measure] [tag]
#   default: 1B fast-forward, 50M detailed warmup, 200M measured (as in the
#   Hawkeye paper's 50M warmup + 200M measurement)
# Output: ~/hawkeye/out/<benchmark>/<policy>_<tag>/

FF=${1:-1000000000}
WARMUP=${2:-50000000}
MEASURE=${3:-200000000}
export TAG=${4:-main}

BENCHES="605.mcf_s 620.omnetpp_s 623.xalancbmk_s 607.cactuBSSN_s 631.deepsjeng_s 657.xz_s"
POLICIES="LRU SRRIP BRRIP DRRIP SHiP Hawkeye"

for b in $BENCHES; do
    for rp in $POLICIES; do
        echo "$b $rp"
    done
done | xargs -P 7 -L 1 bash -c \
    'bash ~/hawkeye/scripts/run_spec.sh "$0" "$1" '"$FF $WARMUP $MEASURE"' && echo "done $0 $1"'
