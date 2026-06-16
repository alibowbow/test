#!/usr/bin/env python3
"""
XPL (Plasma) chart-data collector + technical analysis.

Collects OHLCV candles for XPL/USDT, computes technical indicators
(SMA/EMA, RSI, MACD, Bollinger Bands), renders a candlestick chart PNG,
saves the raw data to CSV, and prints a text summary.

Data sources (tried in order):
  1. MEXC public REST API  -> https://api.mexc.com  (no API key required)
  2. CryptoCompare         -> https://min-api.cryptocompare.com  (datacenter-friendly fallback)

The fallback exists because exchange APIs (MEXC behind Cloudflare) often
return HTTP 403 to cloud/datacenter egress IPs even when the host is
allow-listed. CryptoCompare generally answers datacenter IPs.

Usage:
    python xpl_chart.py                      # XPLUSDT, daily, 180 candles
    python xpl_chart.py --interval 4h --limit 200
    python xpl_chart.py --source mexc        # force a single source
    python xpl_chart.py --mock               # offline self-test (synthetic data)
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone, timedelta

import numpy as np
import pandas as pd
import requests

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
HEADERS = {"User-Agent": UA, "Accept": "application/json"}

# Known reference levels (from public market data, June 2026) for context.
ATH_PRICE, ATH_DATE = 1.68, "2025-09-28"
ATL_PRICE, ATL_DATE = 0.06014, "2026-06-10"


# --------------------------------------------------------------------------- #
# Data sources                                                                #
# --------------------------------------------------------------------------- #
def _normalize(rows: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(rows)
    df = df.set_index("time").sort_index()
    for col in ("open", "high", "low", "close", "volume"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def fetch_mexc(symbol="XPLUSDT", interval="1d", limit=180) -> pd.DataFrame:
    """MEXC v3 klines. Intervals: 1m,5m,15m,30m,60m,4h,1d,1W,1M."""
    iv = {"1h": "60m", "1w": "1W", "1M": "1M"}.get(interval, interval)
    r = requests.get(
        "https://api.mexc.com/api/v3/klines",
        params={"symbol": symbol, "interval": iv, "limit": limit},
        headers=HEADERS, timeout=15,
    )
    r.raise_for_status()
    data = r.json()
    if not isinstance(data, list) or not data:
        raise ValueError(f"MEXC: unexpected payload: {str(data)[:200]}")
    rows = [{
        "time": datetime.fromtimestamp(k[0] / 1000, tz=timezone.utc),
        "open": k[1], "high": k[2], "low": k[3], "close": k[4], "volume": k[5],
    } for k in data]
    return _normalize(rows)


def fetch_cryptocompare(symbol="XPLUSDT", interval="1d", limit=180) -> pd.DataFrame:
    """CryptoCompare histo OHLCV. Falls back across quote currencies."""
    fsym = symbol.replace("USDT", "").replace("USD", "") or "XPL"
    endpoint, aggregate = {
        "1d": ("histoday", 1), "4h": ("histohour", 4),
        "1h": ("histohour", 1), "1w": ("histoday", 7),
    }.get(interval, ("histoday", 1))

    last_err = None
    for tsym in ("USDT", "USD"):
        try:
            r = requests.get(
                f"https://min-api.cryptocompare.com/data/v2/{endpoint}",
                params={"fsym": fsym, "tsym": tsym, "limit": limit,
                        "aggregate": aggregate},
                headers=HEADERS, timeout=15,
            )
            r.raise_for_status()
            j = r.json()
            if j.get("Response") == "Error":
                raise ValueError(f"CryptoCompare({tsym}): {j.get('Message')}")
            data = j["Data"]["Data"]
            if not data or all(d["close"] == 0 for d in data):
                raise ValueError(f"CryptoCompare({tsym}): empty/zero series")
            rows = [{
                "time": datetime.fromtimestamp(d["time"], tz=timezone.utc),
                "open": d["open"], "high": d["high"], "low": d["low"],
                "close": d["close"], "volume": d.get("volumefrom", 0),
            } for d in data if d["close"] > 0]
            return _normalize(rows)
        except Exception as e:  # try next quote currency
            last_err = e
    raise ValueError(f"CryptoCompare failed: {last_err}")


def make_mock(interval="1d", limit=180) -> pd.DataFrame:
    """Synthetic OHLC for offline pipeline testing (no network)."""
    rng = np.random.default_rng(42)
    step = {"1d": timedelta(days=1), "4h": timedelta(hours=4),
            "1h": timedelta(hours=1)}.get(interval, timedelta(days=1))
    t0 = datetime.now(timezone.utc) - step * (limit - 1)
    price = 1.5
    rows = []
    for i in range(limit):
        drift = -0.01 if i < limit * 0.7 else 0.015   # crash then bounce
        ret = drift + rng.normal(0, 0.06)
        o = price
        c = max(0.02, o * (1 + ret))
        h = max(o, c) * (1 + abs(rng.normal(0, 0.02)))
        l = min(o, c) * (1 - abs(rng.normal(0, 0.02)))
        rows.append({"time": t0 + step * i, "open": o, "high": h,
                     "low": l, "close": c, "volume": rng.uniform(1e6, 9e6)})
        price = c
    return _normalize(rows)


SOURCES = {"mexc": fetch_mexc, "cryptocompare": fetch_cryptocompare}


def collect(symbol, interval, limit, source="auto") -> tuple[pd.DataFrame, str]:
    order = list(SOURCES) if source == "auto" else [source]
    errors = []
    for name in order:
        try:
            print(f"[fetch] trying {name} ...", file=sys.stderr)
            df = SOURCES[name](symbol, interval, limit)
            print(f"[fetch] OK via {name}: {len(df)} candles "
                  f"({df.index[0].date()} -> {df.index[-1].date()})",
                  file=sys.stderr)
            return df, name
        except Exception as e:
            print(f"[fetch] {name} failed: {e}", file=sys.stderr)
            errors.append(f"{name}: {e}")
    raise SystemExit("All data sources failed:\n  " + "\n  ".join(errors))


# --------------------------------------------------------------------------- #
# Indicators                                                                  #
# --------------------------------------------------------------------------- #
def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    c = df["close"]
    df["SMA20"] = c.rolling(20).mean()
    df["SMA50"] = c.rolling(50).mean()
    df["EMA20"] = c.ewm(span=20, adjust=False).mean()

    delta = c.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / 14, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / 14, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    df["RSI14"] = 100 - 100 / (1 + rs)

    ema12 = c.ewm(span=12, adjust=False).mean()
    ema26 = c.ewm(span=26, adjust=False).mean()
    df["MACD"] = ema12 - ema26
    df["MACD_signal"] = df["MACD"].ewm(span=9, adjust=False).mean()
    df["MACD_hist"] = df["MACD"] - df["MACD_signal"]

    std20 = c.rolling(20).std()
    df["BB_mid"] = df["SMA20"]
    df["BB_up"] = df["SMA20"] + 2 * std20
    df["BB_low"] = df["SMA20"] - 2 * std20
    return df


# --------------------------------------------------------------------------- #
# Chart                                                                       #
# --------------------------------------------------------------------------- #
def render_chart(df: pd.DataFrame, out: str, symbol: str, interval: str, source: str):
    try:
        import mplfinance as mpf
    except Exception as e:
        return _render_fallback(df, out, symbol, e)

    p = df.rename(columns={"open": "Open", "high": "High", "low": "Low",
                           "close": "Close", "volume": "Volume"})
    line = lambda s, **k: mpf.make_addplot(s, **k)
    aps = [
        line(df["BB_up"], color="#9aa0a6", width=0.7),
        line(df["BB_low"], color="#9aa0a6", width=0.7),
        line(df["SMA20"], color="#1a73e8", width=0.9),
        line(df["SMA50"], color="#f9ab00", width=0.9),
        line(df["RSI14"], panel=2, color="#9334e6", width=0.9, ylabel="RSI"),
        line(pd.Series(70, index=df.index), panel=2, color="#d93025", width=0.6),
        line(pd.Series(30, index=df.index), panel=2, color="#188038", width=0.6),
        line(df["MACD"], panel=3, color="#1a73e8", width=0.9, ylabel="MACD"),
        line(df["MACD_signal"], panel=3, color="#f9ab00", width=0.9),
        line(df["MACD_hist"], panel=3, type="bar", color="#9aa0a6", alpha=0.5),
    ]
    title = f"\n{symbol}  {interval}  (source: {source})  candles={len(df)}"
    mpf.plot(
        p, type="candle", style="yahoo", volume=True, addplot=aps,
        panel_ratios=(6, 1.6, 2, 2), figratio=(16, 11), figscale=1.3,
        tight_layout=True, title=title, savefig=dict(fname=out, dpi=130),
    )
    print(f"[chart] saved -> {out}", file=sys.stderr)


def _render_fallback(df, out, symbol, why):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    print(f"[chart] mplfinance unavailable ({why}); using line fallback",
          file=sys.stderr)
    fig, ax = plt.subplots(figsize=(14, 7))
    ax.plot(df.index, df["close"], label="close", color="black")
    for col, color in (("SMA20", "#1a73e8"), ("SMA50", "#f9ab00")):
        ax.plot(df.index, df[col], label=col, color=color, lw=0.9)
    ax.fill_between(df.index, df["BB_low"], df["BB_up"], color="gray", alpha=0.12)
    ax.set_title(f"{symbol} close + MA/Bollinger")
    ax.legend()
    fig.tight_layout()
    fig.savefig(out, dpi=130)
    print(f"[chart] saved -> {out}", file=sys.stderr)


# --------------------------------------------------------------------------- #
# Summary                                                                     #
# --------------------------------------------------------------------------- #
def summarize(df: pd.DataFrame, symbol: str, interval: str, source: str) -> str:
    last, prev = df.iloc[-1], df.iloc[-2]
    chg = (last.close / prev.close - 1) * 100
    hi, lo = df["high"].max(), df["low"].min()
    rsi = last.RSI14
    rsi_zone = "overbought" if rsi >= 70 else "oversold" if rsi <= 30 else "neutral"
    macd_state = "bullish" if last.MACD_hist > 0 else "bearish"

    def rel(level):
        return "above" if last.close >= level else "below"

    bb_pos = ("near upper" if last.close >= last.BB_up * 0.98 else
              "near lower" if last.close <= last.BB_low * 1.02 else "mid-band")

    L = [
        f"================ XPL / Plasma  ({symbol}, {interval}) ================",
        f"source          : {source}",
        f"candles         : {len(df)}  ({df.index[0].date()} -> {df.index[-1].date()})",
        f"last close      : ${last.close:,.6f}",
        f"per-candle chg  : {chg:+.2f}%",
        f"window high/low : ${hi:,.6f} / ${lo:,.6f}",
        f"RSI(14)         : {rsi:,.1f}  ({rsi_zone})",
        f"MACD hist       : {last.MACD_hist:+.5f}  ({macd_state})",
        f"vs SMA20/50     : {rel(last.SMA20)} SMA20 (${last.SMA20:,.5f}) / "
        f"{rel(last.SMA50)} SMA50 (${last.SMA50:,.5f})",
        f"Bollinger       : {bb_pos}  [{last.BB_low:,.5f} .. {last.BB_up:,.5f}]",
        f"vs ATH {ATH_PRICE} ({ATH_DATE}) : {(last.close/ATH_PRICE-1)*100:+.1f}%",
        f"vs ATL {ATL_PRICE} ({ATL_DATE}) : {(last.close/ATL_PRICE-1)*100:+.1f}%",
        "=====================================================================",
    ]
    return "\n".join(L)


# --------------------------------------------------------------------------- #
def main():
    ap = argparse.ArgumentParser(description="XPL/Plasma chart + indicators")
    ap.add_argument("--symbol", default="XPLUSDT")
    ap.add_argument("--interval", default="1d",
                    help="1d, 4h, 1h, 1w (default 1d)")
    ap.add_argument("--limit", type=int, default=180)
    ap.add_argument("--source", default="auto",
                    choices=["auto", "mexc", "cryptocompare"])
    ap.add_argument("--out", default="xpl_chart.png")
    ap.add_argument("--csv", default=None, help="default: xpl_ohlcv_<interval>.csv")
    ap.add_argument("--mock", action="store_true",
                    help="offline self-test with synthetic data")
    args = ap.parse_args()

    if args.mock:
        df, source = make_mock(args.interval, args.limit), "mock"
        print("[fetch] using synthetic MOCK data (offline test)", file=sys.stderr)
    else:
        df, source = collect(args.symbol, args.interval, args.limit, args.source)

    df = add_indicators(df)

    csv = args.csv or f"xpl_ohlcv_{args.interval}.csv"
    df[["open", "high", "low", "close", "volume"]].to_csv(csv)
    print(f"[data] raw OHLCV saved -> {csv}", file=sys.stderr)

    render_chart(df, args.out, args.symbol, args.interval, source)
    print(summarize(df, args.symbol, args.interval, source))


if __name__ == "__main__":
    main()
