"""Optional fundamentals from FRED: real 10Y yield (DFII10) and 10Y breakeven
inflation (T10YIE). Needs a free FRED_API_KEY in .env
(https://fred.stlouisfed.org/docs/api/api_key.html) — returns None entirely
when unset so the engine degrades to the yfinance-only nominal-yield read in
data_macro.py.
"""
from __future__ import annotations
import os
import requests

BASE = "https://api.stlouisfed.org/fred/series/observations"


def _recent(series_id: str, api_key: str, limit: int = 10) -> list[tuple[str, float]]:
    r = requests.get(BASE, params={
        "series_id": series_id, "api_key": api_key, "file_type": "json",
        "sort_order": "desc", "limit": limit,
    }, timeout=10)
    r.raise_for_status()
    out = []
    for obs in r.json().get("observations", []):
        if obs.get("value") not in (".", None, ""):
            out.append((obs["date"], float(obs["value"])))
    return out


def _latest_and_5d_chg(series_id: str, api_key: str) -> dict:
    obs = _recent(series_id, api_key)
    if not obs:
        return {"pct": None, "as_of": None, "chg_5d_bp": None}
    latest_date, latest_val = obs[0]
    chg_5d_bp = None
    if len(obs) > 5:
        chg_5d_bp = round((latest_val - obs[5][1]) * 100, 1)
    return {"pct": latest_val, "as_of": latest_date, "chg_5d_bp": chg_5d_bp}


def fetch(env: dict | None = None) -> dict | None:
    api_key = (env or os.environ).get("FRED_API_KEY", "").strip()
    if not api_key:
        return None
    return {
        "real_yield_10y": _latest_and_5d_chg("DFII10", api_key),
        "breakeven_inflation_10y": _latest_and_5d_chg("T10YIE", api_key),
    }
