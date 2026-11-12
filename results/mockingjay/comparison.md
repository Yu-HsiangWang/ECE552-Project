Each cell: LLC miss reduction vs LRU / IPC speedup vs LRU (same benchmark and LLC size). Baselines from repo/results/02_spec_main.csv and 04_llc_sweep.csv; HawkeyeI at 2 MB for gcc/xz/deepsjeng from 02_spec_main.md.

### LLC 2 MB (main)

| bench | LRU MPKI | SRRIP | SHiP | DRRIP | BRRIP | Hawkeye | HawkeyeI | Mockingjay | MockingjayI |
|---|---|---|---|---|---|---|---|---|---|
| 605.mcf_s | 25.98 | +1.0% / 1.000 | +2.4% / 0.982 | −1.3% / 0.975 | −8.3% / 0.933 | +6.3% / 1.014 | +6.3% / 1.014 | +11.6% / 1.040 | +11.6% / 1.040 |
| 623.xalancbmk_s | 0.52 | +21.0% / 1.012 | +17.8% / 1.010 | +33.9% / 1.020 | +37.4% / 1.023 | +11.5% / 1.006 | +16.5% / 1.009 | +28.7% / 1.017 | +29.6% / 1.018 |
| 620.omnetpp_s | 0.69 | −0.5% / 0.999 | −3.0% / 1.000 | −10.2% / 0.997 | −39.2% / 0.991 | −20.4% / 0.986 | −11.6% / 0.991 | −9.2% / 0.992 | −5.7% / 0.994 |
| 502.gcc_r | 0.55 | +0.5% / 1.000 | −1.4% / 0.999 | −3.2% / 0.998 | −13.9% / 0.990 | −6.2% / 0.997 | +3.1% / 1.003 | −1.7% / 0.999 | +2.3% / 1.002 |
| 557.xz_r | 0.35 | +0.3% / 1.000 | +0.8% / 1.001 | −1.7% / 0.999 | −7.4% / 0.996 | +5.5% / 1.003 | +5.5% / 1.003 | +2.4% / 1.001 | +2.5% / 1.001 |
| 531.deepsjeng_r | 0.26 | +0.3% / 1.000 | +0.2% / 1.000 | −0.4% / 1.000 | −2.3% / 0.999 | +0.8% / 1.000 | +0.6% / 1.000 | −0.7% / 0.999 | −0.6% / 1.000 |

### LLC 1 MB

| bench | LRU MPKI | SRRIP | SHiP | DRRIP | BRRIP | Hawkeye | HawkeyeI | Mockingjay | MockingjayI |
|---|---|---|---|---|---|---|---|---|---|
| 605.mcf_s | 32.08 | +1.1% / 1.002 | +7.8% / 1.012 | −1.9% / 0.976 | −5.0% / 0.961 | +6.3% / 1.016 | +6.3% / 1.016 | +8.3% / 1.010 | +8.3% / 1.010 |
| 623.xalancbmk_s | 4.74 | +20.4% / 1.069 | +31.7% / 1.110 | +36.8% / 1.130 | +52.8% / 1.213 | +19.5% / 1.061 | +22.6% / 1.075 | +45.6% / 1.172 | +46.6% / 1.180 |
| 620.omnetpp_s | 0.96 | −5.1% / 0.998 | −15.5% / 1.000 | −109.3% / 0.951 | −213.1% / 0.909 | −12.8% / 0.988 | −4.1% / 0.995 | −17.3% / 0.986 | −8.1% / 0.994 |

### LLC 4 MB

| bench | LRU MPKI | SRRIP | SHiP | DRRIP | BRRIP | Hawkeye | HawkeyeI | Mockingjay | MockingjayI |
|---|---|---|---|---|---|---|---|---|---|
| 605.mcf_s | 22.27 | +2.7% / 1.015 | −0.4% / 0.988 | +2.5% / 1.009 | +0.7% / 0.989 | +10.8% / 1.076 | +10.8% / 1.076 | +19.2% / 1.144 | +19.2% / 1.144 |
| 623.xalancbmk_s | 0.15 | +2.1% / 1.000 | −2.9% / 0.999 | +2.2% / 1.000 | +2.2% / 1.000 | +1.3% / 1.000 | +4.5% / 1.001 | −30.0% / 0.995 | −29.8% / 0.995 |
| 620.omnetpp_s | 0.68 | −0.1% / 0.997 | −0.2% / 0.997 | −0.2% / 0.997 | −0.9% / 0.997 | −9.9% / 0.989 | −5.6% / 0.991 | −1.8% / 0.990 | −1.7% / 0.990 |

## Setup

gem5 v23 X86 SE, O3CPU, L2 256 KB, LLC 16-way (2 MB main, 1 MB / 4 MB sweep), as in 02_spec_main.md.
1B instructions fast-forward, 50M warmup, 200M measured. Mockingjay: `gem5/src/mem/cache/replacement_policies/mockingjay_rp.cc`
(bypass=False, lazy aging, parameters derived from the LLC geometry as in `tools/mockingjay_ref.py`).
MockingjayI: instruction-fetch lines are inserted with ETR 0 and kept out of the sampled cache.
Raw numbers: `mj_main.csv`, `mj_llc1MB.csv`, `mj_llc4MB.csv`; per-run stats in `runs/`.

## Microbenchmarks (LLC miss rate)

| pattern | passes | model (no bypass) | Mockingjay | MockingjayI | LRU |
|---|---|---|---|---|---|
| fit | 6 | 14.3% | 15.0% | 15.0% | 15.0% |
| thrash | 6 | 55.4% | 58.3% | 58.3% | 100% |
| mix | 6 | 96.4% | 96.5% | 96.5% | 100% |
| fit | 20 | 4.8% | 5.0% | 5.0% | 5.0% |
| thrash | 20 | 41.7% | 44.5% | 44.5% | 100% |
| mix | 20 | 91.2% | 91.2% | 91.2% | 100% |

Checksums match LRU in every run. `mockingjay_ref.py check` on the 6-pass `--debug-flags=Mockingjay` traces
(every victim and every demand ETR replayed through the model): 0 mismatches for fit, thrash and mix
(17,343 / 289,499 / 1,347,381 victims). The gap on thrash comes from the access stream (gem5 also has L2 writebacks), not from the policy.

## Mockingjay counters (2 MB, Mockingjay)

| bench | demand misses | would-bypass fills | RDP trains |
|---|---|---|---|
| 605.mcf_s | 4,593,944 | 80% | 82,330 |
| 623.xalancbmk_s | 73,822 | 41% | 48,782 |
| 620.omnetpp_s | 149,978 | 4.5% | 18,135 |
| 502.gcc_r | 112,178 | 80% | 3,074 |
| 557.xz_r | 68,156 | 52% | 380 |
| 531.deepsjeng_r | 52,361 | 98% | 178 |
