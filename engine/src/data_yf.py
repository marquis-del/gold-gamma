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
        # period="1d" intermittently comes back empty for futures around
        # session/weekend gaps; "5d" reliably has at least one row.
        hist = t.history(period="5d")
        if hist.empty:
            raise ValueError(f"{sym}: no price data from yfinance (tried fast_info and 5d history)")
        px = float(hist["Close"].iloc[-1])
    return float(px)


def load_chain(cfg: dict, env: dict | None = None):
    gld_sym = cfg.get("gld_symbol", "GLD")
    etf_syms = cfg.get("etf_symbols") or [gld_sym]
    gc_sym = cfg.get("gc_symbol", "GC=F")
    n_exp = int(cfg.get("expirations", 2))

    gc_px = _last_price(gc_sym)
    today = dt.date.today()

    rows = []
    used_syms = []
    gld_px = ratio = None  # primary ETF (first one that resolves) — kept for underlying.gld display
    for sym in etf_syms:
        try:
            etf_px = _last_price(sym)
            tk = yf.Ticker(sym)
            exps = list(tk.options)[:n_exp]
        except Exception:
            continue
        sym_ratio = gc_px / etf_px       # gold price per 1.0 of this ETF share
        if gld_px is None:
            gld_px, ratio = etf_px, sym_ratio
        got_any = False
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
                        "strike": float(k) * sym_ratio,     # -> gold price space
                        "venue": sym,
                    })
                    got_any = True
        if got_any:
            used_syms.append(sym)

    if gld_px is None:
        raise ValueError(f"none of {etf_syms} resolved a price/chain via yfinance")

    df = pd.DataFrame(rows)
    meta = {
        "source": f"yfinance:{'+'.join(used_syms)}",
        "S_gold": gc_px,
        "gc_price": gc_px,
        "gld_price": gld_px,
        "ratio": ratio,
        "etf_venues": used_syms,
    }
    return df, meta
