"""Sanity tests on a synthetic chain (no network). Run: pytest -q  OR  python tests/test_engine.py"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd
from src import engine

CFG = {
    "risk_free_rate": 0.045, "dividend_yield": 0.0, "basis_xau_gc": 0.0,
    "sign_convention": "dealer_long_calls_short_puts",
    "flip_scan": {"range_pct": 0.06, "steps": 121}, "ladder_top": 12,
}


def synthetic():
    S = 2500.0
    strikes = np.arange(2400, 2601, 10.0)
    rows = []
    for k in strikes:
        # OI shaped: big call wall at 2560, big put wall at 2440, magnet mass near 2500
        call_oi = 300 + 4000 * np.exp(-((k - 2560) ** 2) / (2 * 8 ** 2)) + 2600 * np.exp(-((k - 2500) ** 2) / (2 * 20 ** 2))
        put_oi = 300 + 4000 * np.exp(-((k - 2440) ** 2) / (2 * 8 ** 2)) + 2600 * np.exp(-((k - 2500) ** 2) / (2 * 20 ** 2))
        for typ, oi in (("C", call_oi), ("P", put_oi)):
            rows.append({"type": typ, "oi": float(oi), "iv": 0.15, "T": 0.05,
                         "expiry": "2026-09-19", "strike_native": k, "strike": k})
    df = pd.DataFrame(rows)
    meta = {"source": "synthetic", "S_gold": S, "gc_price": S, "gld_price": S / 10.7, "ratio": 10.7}
    return df, meta


def test_levels():
    df, meta = synthetic()
    r = engine.compute(df, meta, CFG)
    L = r["levels_gc"]
    assert L["call_wall"] == 2560, L["call_wall"]
    assert L["put_wall"] == 2440, L["put_wall"]
    assert 2480 <= L["hvl"] <= 2520, L["hvl"]
    assert r["regime"]["state"] in ("SUPPRESSION", "AMPLIFICATION")
    assert len(r["ladder"]) > 0
    assert r["levels_gld"]["hvl"] < r["levels_gc"]["hvl"]  # gld scale is smaller
    return r


if __name__ == "__main__":
    r = test_levels()
    import json
    print(json.dumps({k: r[k] for k in ("data_source", "underlying", "regime", "levels_xauusd", "levels_gld")}, indent=2))
    print("OK: all assertions passed")
