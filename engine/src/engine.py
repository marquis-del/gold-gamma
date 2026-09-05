"""Compute engine: normalized options chain (in GOLD price space) -> dealer
positioning levels. Source-agnostic: works identically on dxFeed /GC data and
the GLD fallback, because both loaders hand it the same normalized frame.

Normalized chain DataFrame columns (all required unless noted):
    strike        float   strike in GOLD price space (~ /GC ~ spot)
    strike_native float   original strike (GLD or /GC) for reference
    type          str     'C' or 'P'
    oi            float   open interest
    iv            float   implied vol (decimal, e.g. 0.16)
    T             float   years to expiry
    gamma         float   OPTIONAL — point-in-time gamma from the feed (dxFeed)
    delta         float   OPTIONAL — point-in-time delta from the feed (dxFeed)

meta dict: source, S_gold, gc_price, gld_price, ratio  (ratio = gold/gld)
"""
from __future__ import annotations
import numpy as np
import pandas as pd
from . import greeks

MULT = 100.0  # contract multiplier: 100 (GLD) / 100 troy oz (/GC)


def _sign(series_type: pd.Series) -> np.ndarray:
    # dealer_long_calls_short_puts: calls +1, puts -1
    return np.where(series_type.values == "C", 1.0, -1.0)


def _point_gamma_delta(df, S, r, q):
    g = df["gamma"].values if "gamma" in df and df["gamma"].notna().all() else \
        greeks.gamma(S, df["strike"].values, df["T"].values, r, q, df["iv"].values)
    d = df["delta"].values if "delta" in df and df["delta"].notna().all() else \
        greeks.delta(S, df["strike"].values, df["T"].values, r, q, df["iv"].values, df["type"].values)
    return g, d


def _total_gex_at(Sp, df, r, q, sign):
    """Net GEX ($/1% move) if spot were Sp — gamma recomputed via BSM at Sp."""
    g = greeks.gamma(Sp, df["strike"].values, df["T"].values, r, q, df["iv"].values)
    return float(np.sum(sign * g * df["oi"].values * MULT * Sp ** 2 * 0.01))


def _solve_flip(df, S, r, q, sign, range_pct, steps):
    lo, hi = S * (1 - range_pct), S * (1 + range_pct)
    grid = np.linspace(lo, hi, steps)
    vals = np.array([_total_gex_at(sp, df, r, q, sign) for sp in grid])
    # find sign changes; pick the crossing nearest current spot
    crossings = []
    for i in range(len(grid) - 1):
        if vals[i] == 0:
            crossings.append(grid[i])
        elif vals[i] * vals[i + 1] < 0:
            # linear interpolation for the zero
            x0, x1, y0, y1 = grid[i], grid[i + 1], vals[i], vals[i + 1]
            crossings.append(x0 - y0 * (x1 - x0) / (y1 - y0))
    if not crossings:
        return None
    return float(min(crossings, key=lambda x: abs(x - S)))


def compute(df: pd.DataFrame, meta: dict, cfg: dict) -> dict:
    S = float(meta["S_gold"])
    r = float(cfg.get("risk_free_rate", 0.045))
    q = float(cfg.get("dividend_yield", 0.0))
    basis = float(cfg.get("basis_xau_gc", 0.0))
    ratio = float(meta.get("ratio", 1.0)) or 1.0

    df = df.copy()
    df = df[(df["oi"] > 0) & df["iv"].notna() & (df["iv"] > 0)].reset_index(drop=True)
    sign = _sign(df["type"])

    g, d = _point_gamma_delta(df, S, r, q)
    df["gex"] = sign * g * df["oi"].values * MULT * S ** 2 * 0.01
    df["dex"] = sign * d * df["oi"].values * MULT * S           # dealer delta $-notional

    net_gex = float(df["gex"].sum())
    net_dex = float(df["dex"].sum())

    # per-strike aggregation (gold space)
    by = df.groupby("strike")
    call_gex = by.apply(lambda x: x.loc[x["type"] == "C", "gex"].sum())
    put_gex = by.apply(lambda x: x.loc[x["type"] == "P", "gex"].sum())
    gross_gex = call_gex.abs() + put_gex.abs()   # gamma magnet = gross concentration

    call_wall = float(call_gex.idxmax()) if (call_gex > 0).any() else None
    put_wall = float(put_gex.idxmin()) if (put_gex < 0).any() else None
    hvl = float(gross_gex.idxmax())

    ranked = gross_gex.sort_values(ascending=False)
    chosen = {call_wall, put_wall, hvl}
    secondary = [float(k) for k in ranked.index if float(k) not in chosen][: 3]

    flip = _solve_flip(df, S, r, q, sign,
                       cfg["flip_scan"]["range_pct"], cfg["flip_scan"]["steps"])

    if flip is not None:
        state = "SUPPRESSION" if (S > flip and net_gex > 0) else "AMPLIFICATION"
    else:
        state = "SUPPRESSION" if net_gex > 0 else "AMPLIFICATION"

    def scales(gold_val):
        if gold_val is None:
            return None
        return {"xauusd": round(gold_val + basis, 2),
                "gc": round(gold_val, 2),
                "gld": round(gold_val / ratio, 2)}

    # ladder (top N strikes by |total gex|), split call/put, in gold space
    top = ranked.index[: int(cfg.get("ladder_top", 12))]
    ladder = []
    for k in sorted(top, reverse=True):
        ladder.append({
            "strike_xau": round(float(k) + basis, 2),
            "strike_gold": round(float(k), 2),
            "call_gex": round(float(call_gex.get(k, 0.0)), 2),
            "put_gex": round(float(put_gex.get(k, 0.0)), 2),
        })

    return {
        "data_source": meta.get("source"),
        "underlying": {
            "gold": round(S, 2),
            "xauusd": round(S + basis, 2),
            "gc": round(meta.get("gc_price", S), 2),
            "gld": round(meta.get("gld_price", S / ratio), 2),
            "basis_xau_gc": round(basis, 2),
            "gld_to_gold_ratio": round(ratio, 4),
        },
        "regime": {
            "state": state,
            "net_gex": net_gex,
            "net_dex": net_dex,
            "flip": scales(flip),
        },
        "levels_xauusd": {
            "call_wall": (scales(call_wall) or {}).get("xauusd") if call_wall else None,
            "put_wall": (scales(put_wall) or {}).get("xauusd") if put_wall else None,
            "hvl": scales(hvl)["xauusd"],
            "gamma_flip": (scales(flip) or {}).get("xauusd") if flip else None,
            "secondary": [scales(s)["xauusd"] for s in secondary],
        },
        "levels_gc": {
            "call_wall": call_wall, "put_wall": put_wall, "hvl": hvl,
            "gamma_flip": flip, "secondary": secondary,
        },
        "levels_gld": {
            "call_wall": (scales(call_wall) or {}).get("gld") if call_wall else None,
            "put_wall": (scales(put_wall) or {}).get("gld") if put_wall else None,
            "hvl": scales(hvl)["gld"],
        },
        "ladder": ladder,
        "sign_convention": cfg.get("sign_convention", "dealer_long_calls_short_puts"),
    }
