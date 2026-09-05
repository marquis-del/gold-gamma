"""FREE FALLBACK data source: GLD options chain via yfinance.

Pulls the GLD chain (strikes, open interest, implied vol) for the nearest N
expirations, computes greeks downstream via Black-Scholes, and converts GLD
strikes into GOLD price space using a live ratio (gold / GLD). Great for
building and testing offline; replace with dxFeed /GC for the real book.
"""
from __future__ import annotations
import datetime as dt
import numpy as np
import pandas as pd
import yfinance as yf


def _last_price(sym: str) -> float:
    t = yf.Ticker(sym)
    px = t.fast_info.get("last_price") if hasattr(t, "fast_info") else None
    if not px:
        hist = t.history(period="1d")
        px = float(hist["Close"].iloc[-1])
    return float(px)


def load_chain(cfg: dict, env: dict | None = None):
    gld_sym = cfg.get("gld_symbol", "GLD")
    gc_sym = cfg.get("gc_symbol", "GC=F")
    n_exp = int(cfg.get("expirations", 2))

    gld_px = _last_price(gld_sym)
    gc_px = _last_price(gc_sym)
    ratio = gc_px / gld_px           # gold price per 1.0 of GLD (~10.x)

    tk = yf.Ticker(gld_sym)
    exps = list(tk.options)[:n_exp]
    today = dt.date.today()

    rows = []
    for exp in exps:
        exp_date = dt.datetime.strptime(exp, "%Y-%m-%d").date()
        T = max((exp_date - today).days, 1) / 365.25
        chain = tk.option_chain(exp)
        for typ, frame in (("C", chain.calls), ("P", chain.puts)):
            for _, o in frame.iterrows():
                oi = o.get("openInterest", np.nan)
                iv = o.get("impliedVolatility", np.nan)
                k = o.get("strike", np.nan)
                if not (oi and oi > 0) or not (iv and iv > 0) or not k:
                    continue
                rows.append({
                    "type": typ,
                    "oi": float(oi),
                    "iv": float(iv),
                    "T": T,
                    "expiry": exp,
                    "strike_native": float(k),
                    "strike": float(k) * ratio,     # -> gold price space
                })

    df = pd.DataFrame(rows)
    meta = {
        "source": f"yfinance:{gld_sym}",
        "S_gold": gc_px,
        "gc_price": gc_px,
        "gld_price": gld_px,
        "ratio": ratio,
    }
    return df, meta
