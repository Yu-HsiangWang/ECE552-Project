#!/usr/bin/env python3
"""Figures for the final report. Run from the repository root:
python3 FinalReport/fig/make_figs.py"""
import csv
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Patch

# Categorical slots 1-5 and 7 of the dataviz reference palette, validated as
# a set (light mode). Each I variant shares its policy's hue and adds a hatch.
SERIES = [("SRRIP", "#2a78d6", ""), ("BRRIP", "#eb6834", ""),
          ("DRRIP", "#1baf7a", ""), ("SHiP", "#eda100", ""),
          ("Hawkeye", "#e87ba4", ""), ("HawkeyeI", "#e87ba4", "////"),
          ("Mockingjay", "#6250d6", ""), ("MockingjayI", "#6250d6", "////")]
BENCH = ["605.mcf_s", "620.omnetpp_s", "502.gcc_r", "623.xalancbmk_s",
         "557.xz_r", "531.deepsjeng_r"]
INK, GRID = "#52514e", "#e4e3df"

rows = {}
for r in csv.DictReader(open("results/06_all_policies.csv")):
    if r["llc"] == "2MB":
        rows[(r["bench"], r["policy"])] = r

plt.rcParams.update({"font.family": "serif", "font.serif": ["STIXGeneral", "DejaVu Serif"],
                     "mathtext.fontset": "stix", "font.size": 8.5,
                     "axes.edgecolor": INK, "axes.linewidth": 0.6,
                     "xtick.color": INK, "ytick.color": INK,
                     "hatch.color": "white", "hatch.linewidth": 0.8})
fig, axes = plt.subplots(2, 1, figsize=(7.0, 3.6), sharex=True)
n = len(SERIES)
w = 0.84 / n
panels = [("miss_red_%", "LLC misses removed\nrelative to LRU (%)", (-42, 42), range(-40, 41, 20)),
          ("speedup", "IPC speedup\nrelative to LRU (%)", (-7.5, 4.5), range(-6, 5, 2))]
for ax, (key, label, ylim, yticks) in zip(axes, panels):
    for i, (p, c, h) in enumerate(SERIES):
        xs = [b + (i - (n - 1) / 2) * w for b in range(len(BENCH))]
        ys = [float(rows[(b, p)][key]) for b in BENCH]
        if key == "speedup":
            ys = [100 * (y - 1) for y in ys]
        ax.bar(xs, ys, width=w * 0.86, color=c, hatch=h, linewidth=0, zorder=3)
    ax.axhline(0, color=INK, linewidth=0.6, zorder=4)
    ax.set_ylabel(label)
    ax.set_ylim(*ylim)
    ax.set_yticks(list(yticks))
    ax.grid(axis="y", color=GRID, linewidth=0.5, zorder=0)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    ax.tick_params(axis="x", length=0)
axes[1].set_xticks(range(len(BENCH)))
axes[1].set_xticklabels([f"{b.split('.')[1].split('_')[0]}\n(LRU MPKI {float(rows[(b, 'LRU')]['mpki']):.2f})"
                         for b in BENCH])
handles = [Patch(facecolor=c, hatch=h, label=p, linewidth=0) for p, c, h in SERIES]
axes[0].legend(handles=handles, ncol=8, frameon=False, loc="lower center",
               bbox_to_anchor=(0.5, 1.0), handlelength=1.2, columnspacing=1.1,
               fontsize=7.8)
fig.tight_layout(pad=0.2, h_pad=0.6)
fig.savefig("FinalReport/fig/spec_2mb.pdf")
