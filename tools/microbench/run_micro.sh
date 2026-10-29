#!/bin/bash
# Run the LLC pattern microbenchmarks under every LLC policy on EC2.
#
# Usage: run_micro.sh [policies...]   (default: LRU SRRIP BRRIP DRRIP SHiP Hawkeye)
# Output: ~/hawkeye/micro/<pattern>/<policy>/{stats.txt,log.txt}
#
# Sizes against the 2 MB, 16-way LLC (L2 is 256 kB):
#   fit    1 MB array, 6 passes
#   thrash 3 MB array, 6 passes (1.5x the LLC)
#   mix    1 MB reused array, 24 MB stream, 6 passes

GEM5=~/gem5/build/X86/gem5.opt
CONFIG=~/hawkeye/configs/hk_se.py
BIN=~/hawkeye/micro/llc_patterns
POLICIES=${*:-LRU SRRIP BRRIP DRRIP SHiP Hawkeye}

mkdir -p ~/hawkeye/micro
gcc -O2 -static -o "$BIN" ~/hawkeye/tools/microbench/llc_patterns.c || exit 1

declare -A ARGS=(
    [fit]="fit 1024 6"
    [thrash]="thrash 3072 6"
    [mix]="mix 1024 24576 6"
)

for pat in fit thrash mix; do
    for rp in $POLICIES; do
        out=~/hawkeye/micro/$pat/$rp
        mkdir -p "$out"
        $GEM5 -q --outdir="$out" "$CONFIG" --cmd="$BIN" \
            --options="${ARGS[$pat]}" --rp="$rp" > "$out/log.txt" 2>&1 &
    done
    wait
done
