#!/bin/bash
# Run one SPEC CPU2017 speed benchmark on the Hawkeye config with one LLC policy.
#
# Usage: run_spec.sh <benchmark> <policy> [fast_forward] [warmup] [measure]
#   e.g. run_spec.sh 605.mcf_s DRRIP 1000000000 10000000 50000000
# Output: ~/hawkeye/out/<benchmark>/<policy>[_$TAG]/{stats.txt,config.ini,log.txt}

set -e
BENCH=$1
RP=$2
FF=${3:-0}
WARMUP=${4:-10000000}
MEASURE=${5:-50000000}

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
    607.cactuBSSN_s) OPTS="spec_ref.par" ;;
    620.omnetpp_s)   OPTS="-c General -r 0" ;;
    623.xalancbmk_s) OPTS="-v t5.xml xalanc.xsl" ;;
    631.deepsjeng_s) OPTS="ref.txt" ;;
    641.leela_s)     OPTS="ref.sgf" ;;
    644.nab_s)       OPTS="3j1n 20140317 220" ;;
    657.xz_s)        OPTS="cpu2006docs.tar.xz 6643 055ce243071129412e9dd0b3b69a21654033a9b723d874b2015c774fac1553d9713be561ca86f74e4f16f22e664fc17a79f30caa5ad2c04fbc447549c2810fae 1036078272 1111795472 4" ;;
    *) echo "no options recorded for $BENCH" >&2; exit 1 ;;
esac

# gcc_s builds its binary as sgcc.
[ "$BENCH" = "602.gcc_s" ] && EXE_NAME=sgcc
BINARY=$SPEC_DIR/build/build_base_mytest-m64.0000/$EXE_NAME
# Optional TAG env var keeps runs with different settings apart.
OUT=~/hawkeye/out/$BENCH/$RP${TAG:+_$TAG}
mkdir -p "$OUT"
cd "$RUN_DIR"
$GEM5 -q --outdir="$OUT" "$CONFIG" --cmd="$BINARY" --options="$OPTS" \
    --rp="$RP" --fast-forward="$FF" --warmup="$WARMUP" --measure="$MEASURE" > "$OUT/log.txt" 2>&1
