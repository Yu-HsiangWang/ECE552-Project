#!/bin/bash
# Run one SPEC CPU2017 benchmark (speed _s or rate _r) on the Hawkeye config
# with one LLC policy.
#
# Usage: run_spec.sh <benchmark> <policy> [fast_forward] [warmup] [measure]
#   e.g. run_spec.sh 605.mcf_s DRRIP 1000000000 10000000 50000000
# Output: ~/hawkeye/out/<benchmark>/<policy>[_$TAG]/{stats.txt,config.ini,log.txt}
# MEM_MAX env var (e.g. 9G) caps the run's memory, so a run that grows too
# large is killed instead of hanging the whole instance.

set -e
BENCH=$1
RP=$2
FF=${3:-0}
WARMUP=${4:-10000000}
MEASURE=${5:-50000000}

GEM5=~/gem5/build/X86/gem5.opt
CONFIG=~/hawkeye/configs/hk_se.py
SPEC_DIR=~/spec2017/benchspec/CPU/$BENCH
SIZE=refspeed
[[ $BENCH == *_r ]] && SIZE=refrate
RUN_DIR=$SPEC_DIR/run/run_base_${SIZE}_mytest-m64.0000
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
    531.deepsjeng_r) OPTS="ref.txt" ;;
    557.xz_r)        OPTS="cld.tar.xz 160 19cf30ae51eddcbefda78dd06014b4b96281456e078ca7c13e1c0c9e6aaea8dff3efb4ad6b0456697718cede6bd5454852652806a657bb56e07d61128434b474 59796407 61004416 6" ;;
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
LIMIT=
[ -n "$MEM_MAX" ] && LIMIT="systemd-run --user --scope -q -p MemoryMax=$MEM_MAX -p MemorySwapMax=0"
$LIMIT $GEM5 -q --outdir="$OUT" "$CONFIG" --cmd="$BINARY" --options="$OPTS" \
    --rp="$RP" --fast-forward="$FF" --warmup="$WARMUP" --measure="$MEASURE" > "$OUT/log.txt" 2>&1
