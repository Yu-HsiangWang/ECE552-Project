#!/usr/bin/env python3
"""Figures for the status report. Run from the repository root:
python3 StatusReport/fig/make_figs.py"""
import csv
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

SERIES = ["SRRIP", "BRRIP", "DRRIP", "SHiP", "Hawkeye", "HawkeyeI"]
# Categorical slots 1-6 of the dataviz reference palette, in fixed order.
COLORS = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300"]
BENCH = ["605.mcf_s", "620.omnetpp_s", "502.gcc_r", "623.xalancbmk_s",
         "557.xz_r", "531.deepsjeng_r"]

rows = {}
for f in ("results/02_spec_main.csv", "StatusReport/fig/hawkeyei_2mb.csv"):
    for r in csv.DictReader(open(f)):
        rows[(r["bench"], r["policy"])] = r

plt.rcParams.update({"font.family": "serif", "font.serif": ["STIXGeneral", "DejaVu Serif"],
                     "mathtext.fontset": "stix", "font.size": 8,
                     "axes.edgecolor": "#52514e", "axes.linewidth": 0.6,
                     "xtick.color": "#52514e", "ytick.color": "#52514e"})
fig, ax = plt.subplots(figsize=(7.0, 1.9))
n = len(SERIES)
w = 0.8 / n
for i, (p, c) in enumerate(zip(SERIES, COLORS)):
    xs = [b + (i - (n - 1) / 2) * w for b in range(len(BENCH))]
    ys = [float(rows[(b, p)]["miss_red_%"]) for b in BENCH]
    ax.bar(xs, ys, width=w * 0.86, color=c, label=p, zorder=3)
ax.axhline(0, color="#52514e", linewidth=0.6, zorder=4)
ax.set_xticks(range(len(BENCH)))
ax.set_xticklabels([f"{b.split('.')[1].split('_')[0]}\n(LRU MPKI {float(rows[(b, 'LRU')]['mpki']):.2f})"
                    for b in BENCH])
ax.set_ylabel("LLC misses removed\nvs. LRU (%)")
ax.set_ylim(-42, 42)
ax.set_yticks(range(-40, 41, 20))
ax.grid(axis="y", color="#e4e3df", linewidth=0.5, zorder=0)
for s in ("top", "right"):
    ax.spines[s].set_visible(False)
ax.tick_params(axis="x", length=0)
ax.legend(ncol=6, frameon=False, loc="lower center", bbox_to_anchor=(0.5, 1.0),
          handlelength=1.0, columnspacing=1.4, fontsize=7.5)
fig.tight_layout(pad=0.2)
fig.savefig("StatusReport/fig/spec_2mb.pdf")
fig.savefig("StatusReport/fig/spec_2mb.png", dpi=200)
