#!/usr/bin/env python3
"""
XPL (Plasma) real-data LEVELS map (June 16, 2026).

The candle-fetching pipeline (xpl_chart.py) is blocked in this environment:
the egress proxy returns `host_not_allowed` for every crypto data host
(MEXC, CryptoCompare, Binance, CoinGecko, Kraken, ...), so no OHLC series
could be downloaded. This script instead draws an honest technical MAP from
the real spot levels gathered via web research -- NOT synthetic candles.

All numbers below are real, sourced June 16, 2026.
"""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch

# ---- Real reference data (June 16, 2026) ----------------------------------
PRICE      = 0.089847          # current spot
D24_LOW    = 0.087667          # 24h low
D24_HIGH   = 0.096832          # 24h high
ATH, ATH_D = 1.68,  "2025-09-28"
ATL, ATL_D = 0.06014, "2026-06-10"

# Support / resistance from market analyses (real, cited)
SUPPORTS    = [(0.087, "S1  0.087  (24h low / near-term)"),
               (0.070, "S2  0.070  (critical pivot)"),
               (0.06014, f"S3  0.060  (ATL {ATL_D})")]
RESISTANCES = [(0.095,  "R1  0.095  (24h high zone)"),
               (0.105,  "R2  0.105  (reclaim = bias flips)"),
               (0.110,  "R3  0.110  (~EMA20)"),
               (0.120,  "R4  0.120  (~Supertrend)")]

# Real anchor points of the price path (sparse, labelled -- not OHLC)
PATH = [("2025-09", 1.68,  "ATH 1.68"),
        ("2026-04", 0.30,  "~0.30"),
        ("2026-06-10", 0.060, "ATL 0.060"),
        ("2026-06-12", 0.115, "+27% Plasma One\ncard tiers"),
        ("2026-06-16", PRICE, "now 0.090")]

fig, (axL, axR) = plt.subplots(1, 2, figsize=(15, 8),
                               gridspec_kw={"width_ratios": [1.05, 1]})
fig.suptitle("XPL / Plasma  —  REAL-DATA technical levels map  (2026-06-16)\n"
             "built from spot levels via web research — OHLC fetch blocked by "
             "egress (host_not_allowed)", fontsize=12, weight="bold")

# ---------- LEFT: zoomed actionable levels ($0.05–$0.13) -------------------
axL.set_title("Actionable zone  ($0.05 – $0.13)", fontsize=11)
axL.set_xlim(0, 1); axL.set_ylim(0.05, 0.13)
axL.set_ylabel("Price (USD)")
axL.set_xticks([])

# resistance band (red) / support band (green)
for lvl, lbl in RESISTANCES:
    if 0.05 <= lvl <= 0.13:
        axL.axhline(lvl, color="#d93025", lw=1.3, alpha=0.8)
        axL.text(0.015, lvl, lbl, va="center", fontsize=8.5, color="#a50e0e")
for lvl, lbl in SUPPORTS:
    if 0.05 <= lvl <= 0.13:
        axL.axhline(lvl, color="#188038", lw=1.3, alpha=0.85)
        axL.text(0.015, lvl, lbl, va="center", fontsize=8.5, color="#0b5394")

# 24h range shaded
axL.axhspan(D24_LOW, D24_HIGH, color="#fbbc04", alpha=0.18)
axL.text(0.985, (D24_LOW+D24_HIGH)/2, "24h\nrange", ha="right", va="center",
         fontsize=8, color="#9a6700")

# current price
axL.axhline(PRICE, color="black", lw=2.2)
axL.text(0.985, PRICE, f"  ● {PRICE:.4f}", ha="right", va="bottom",
         fontsize=10, weight="bold")

# July 28 unlock annotation
axL.annotate("Jul 28 unlock →\n1B public-sale tradeable\n+2.5B team/investor vest start",
             xy=(0.5, 0.072), fontsize=8.5, ha="center", color="#a50e0e",
             bbox=dict(boxstyle="round", fc="#fce8e6", ec="#d93025", alpha=0.9))
axL.grid(axis="y", alpha=0.25)

# ---------- RIGHT: full-range drawdown context (log) -----------------------
axR.set_title("Drawdown context (log)  —  ATH → ATL → now", fontsize=11)
xs = list(range(len(PATH)))
ys = [p[1] for p in PATH]
axR.set_yscale("log")
axR.plot(xs, ys, "o-", color="#1a73e8", lw=1.6, ms=7)
for x, (_, y, lbl) in zip(xs, PATH):
    axR.annotate(lbl, (x, y), textcoords="offset points", xytext=(0, 10),
                 ha="center", fontsize=8.3)
axR.axhline(ATH, color="#9aa0a6", ls="--", lw=0.8)
axR.axhline(ATL, color="#9aa0a6", ls="--", lw=0.8)
axR.axhline(PRICE, color="black", lw=1.4, alpha=0.7)
axR.set_xticks(xs)
axR.set_xticklabels([p[0] for p in PATH], rotation=30, ha="right", fontsize=8)
axR.set_ylabel("Price (USD, log)")
axR.set_ylim(0.05, 2.0)
axR.grid(alpha=0.25, which="both")
dd = (PRICE/ATH - 1) * 100
axR.text(0.04, 0.04, f"from ATH: {dd:+.0f}%\nfrom ATL: {(PRICE/ATL-1)*100:+.0f}%",
         transform=axR.transAxes, fontsize=9,
         bbox=dict(boxstyle="round", fc="#e8f0fe", ec="#1a73e8"))

fig.tight_layout(rect=[0, 0, 1, 0.94])
fig.savefig("xpl_chart.png", dpi=140)
print("saved xpl_chart.png")
