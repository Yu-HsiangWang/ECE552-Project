#!/bin/bash
# Run the LLC pattern microbenchmarks under every LLC policy on EC2.
#
# Usage: [PASSES=n] [DEBUG=flags] run_micro.sh [policies...]
#        (default policies: LRU SRRIP BRRIP DRRIP SHiP Hawkeye)
# Output: ~/hawkeye/micro/<pattern>/<policy>/{stats.txt,log.txt}
#         (~/hawkeye/micro_p<n>/... when PASSES is not 6)
# PASSES  passes over each array (default 6); mix streams 4 MB per pass.
# DEBUG   gem5 debug flags (e.g. Mockingjay); the trace goes to
#         <out>/trace.txt.gz.
#
# Sizes against the 2 MB, 16-way LLC (L2 is 256 kB):
#   fit    1 MB array, 6 passes
#   thrash 3 MB array, 6 passes (1.5x the LLC)
#   mix    1 MB reused array, 24 MB stream, 6 passes

GEM5=~/gem5/build/X86/gem5.opt
CONFIG=~/hawkeye/configs/hk_se.py
BIN=~/hawkeye/micro/llc_patterns
POLICIES=${*:-LRU SRRIP BRRIP DRRIP SHiP Hawkeye}
PASSES=${PASSES:-6}
if [ "$PASSES" = 6 ]; then MICRO=~/hawkeye/micro; else MICRO=~/hawkeye/micro_p$PASSES; fi
DBG=()
if [ -n "$DEBUG" ]; then DBG=(--debug-flags="$DEBUG" --debug-file=trace.txt.gz); fi

mkdir -p ~/hawkeye/micro "$MICRO"
gcc -O2 -static -o "$BIN" ~/hawkeye/tools/microbench/llc_patterns.c || exit 1

declare -A ARGS=(
    [fit]="fit 1024 $PASSES"
    [thrash]="thrash 3072 $PASSES"
    [mix]="mix 1024 $((4096 * PASSES)) $PASSES"
)

for pat in fit thrash mix; do
    for rp in $POLICIES; do
        out=$MICRO/$pat/$rp
        mkdir -p "$out"
        $GEM5 -q --outdir="$out" "${DBG[@]}" "$CONFIG" --cmd="$BIN" \
            --options="${ARGS[$pat]}" --rp="$rp" > "$out/log.txt" 2>&1 &
    done
    wait
done
