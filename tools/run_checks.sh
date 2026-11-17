#!/bin/bash
# Runs every reference-model check on the traces fetched from EC2.
# Usage: run_checks.sh <dir>   (<dir> holds micro_dbg/ and out/ fetched from
#        the EC2 after run_final.sh, with their trace.txt.gz files)
D=$1
R=$(dirname "$0")
for pat in fit thrash mix; do
    t=$D/micro_dbg/$pat/Hawkeye/trace.txt.gz
    [ -f $t ] && { echo "== Hawkeye replay micro $pat"; python3 $R/hawkeye_ref.py replay $t; }
    t=$D/micro_dbg/$pat/HawkeyeI/trace.txt.gz
    [ -f $t ] && { echo "== HawkeyeI replay micro $pat"; python3 $R/hawkeye_ref.py replay --inst-friendly $t; }
    t=$D/micro_dbg/$pat/Mockingjay/trace.txt.gz
    [ -f $t ] && { echo "== Mockingjay check micro $pat"; python3 $R/mockingjay_ref.py check $t; }
done
for b in 502.gcc_r 620.omnetpp_s; do
    t=$D/out/$b/Hawkeye_check/trace.txt.gz
    [ -f $t ] && { echo "== Hawkeye replay $b (30M from start)"; python3 $R/hawkeye_ref.py replay $t; }
    t=$D/out/$b/HawkeyeI_check/trace.txt.gz
    [ -f $t ] && { echo "== HawkeyeI replay $b (30M from start)"; python3 $R/hawkeye_ref.py replay --inst-friendly $t; }
    t=$D/out/$b/Mockingjay_check/trace.txt.gz
    [ -f $t ] && { echo "== Mockingjay check $b (30M from start)"; python3 $R/mockingjay_ref.py check $t; }
done
