#!/bin/bash
# Run one SPEC CPU2017 speed benchmark on the Hawkeye config with one LLC policy.
#
# Usage: run_spec.sh <benchmark> <policy> [warmup_insts] [measure_insts]
#   e.g. run_spec.sh 605.mcf_s DRRIP 10000000 50000000
# Output: ~/hawkeye/out/<benchmark>/<policy>/{stats.txt,config.ini,log.txt}

set -e
BENCH=$1
RP=$2
WARMUP=${3:-10000000}
MEASURE=${4:-50000000}

GEM5=~/gem5/build/X86/gem5.opt
CONFIG=~/hawkeye/configs/hk_se.py
SPEC_DIR=~/spec2017/benchspec/CPU/$BENCH
RUN_DIR=$SPEC_DIR/run/run_base_refspeed_mytest-m64.0000
EXE_NAME=${BENCH#*.}

# Arguments of the reference runs, as in the course spec_scripts.
case $BENCH in
    600.perlbench_s) OPTS="-I./lib checkspam.pl 2500 5 25 11 150 1 1 1 1" ;;
    602.gcc_s)       OPTS="gcc-pp.c -O5 -fipa-pta -o gcc-pp.opts-O5_-fipa-pta.s" ;;
    605.mcf_s)       OPTS="inp.in" ;;
    *) echo "no options recorded for $BENCH" >&2; exit 1 ;;
esac

BINARY=$SPEC_DIR/build/build_base_mytest-m64.0000/$EXE_NAME
OUT=~/hawkeye/out/$BENCH/$RP
mkdir -p "$OUT"
cd "$RUN_DIR"
$GEM5 -q --outdir="$OUT" "$CONFIG" --cmd="$BINARY" --options="$OPTS" \
    --rp="$RP" --warmup="$WARMUP" --measure="$MEASURE" > "$OUT/log.txt" 2>&1
