#!/bin/bash
# Build SPEC CPU2017 speed benchmarks for gem5 SE mode, as the course
# spec_scripts do (runcpu --fake sets up build/ and run/, specmake compiles).
#
# Usage: build_spec.sh <benchmark>...   e.g. build_spec.sh 620.omnetpp_s

SPEC=~/spec2017
for BENCH in "$@"; do
    EXE=${BENCH#*.}
    [ "$BENCH" = "602.gcc_s" ] && EXE=sgcc
    BUILD_DIR=$SPEC/benchspec/CPU/$BENCH/build/build_base_mytest-m64.0000
    if [ -x "$BUILD_DIR/$EXE" ]; then
        echo "$BENCH: already built"
        continue
    fi
    (cd $SPEC && source shrc && \
        runcpu --fake --config sample-gcc-linux-x86 $BENCH > /dev/null) || exit 1
    (cd "$BUILD_DIR" && source $SPEC/shrc && specmake > make.log 2>&1)
    if [ -x "$BUILD_DIR/$EXE" ]; then
        echo "$BENCH: built"
    else
        echo "$BENCH: build FAILED, see $BUILD_DIR/make.log"
    fi
done
