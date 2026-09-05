"""Macro/fundamentals context: USD (DXY), nominal 10Y yield, S&P 500, and the
GC-vs-GLD correlation (a trust check for the yfinance/GLD proxy path — shown
alongside any GLD-derived options analysis since GLD is only a proxy for the
real /GC book). Free, yfinance-only; real yields/breakeven come from
data_fred.py when a FRED_API_KEY is configured.
"""
from __future__ import annotations
import yfinance as yf
import pandas as pd

# Yahoo has moved/renamed the ICE Dollar Index ticker before; try in order.
DXY_CANDIDATES = ["DX-Y.NYB", "DX=F", "UUP"]


def _history(sym: str, period="3mo") -> pd.Series | None:
    hist = yf.Ticker(sym).history(period=period)["Close"]
    return hist if not hist.empty else None


def _first_history(candidates: list[str], period="3mo") -> tuple[str, pd.Series] | tuple[None, None]:
    for sym in candidates:
        hist = _history(sym, period)
        if hist is not None and len(hist) > 5:
            return sym, hist
    return None, None


def _pct_change_over(hist: pd.Series, bars_back: int) -> float | None:
    if hist is None or len(hist) <= bars_back:
        return None
    return float(hist.iloc[-1] / hist.iloc[-1 - bars_back] - 1)


def _corr(a: pd.Series, b: pd.Series, window: int) -> float | None:
    joined = pd.concat([a, b], axis=1, join="inner").tail(window)
    if len(joined) < max(5, window // 2):
        return None
    return float(joined.iloc[:, 0].corr(joined.iloc[:, 1]))


def fetch(cfg: dict) -> dict:
    window = int(cfg.get("macro_corr_window", 30))
    gc_sym = cfg.get("gc_symbol", "GC=F")
    gld_sym = cfg.get("gld_symbol", "GLD")
    spx_sym = cfg.get("spx_symbol", "^GSPC")
    tnx_sym = cfg.get("tnx_symbol", "^TNX")

    gc_hist = _history(gc_sym)
    gld_hist = _history(gld_sym)
    spx_hist = _history(spx_sym)
    tnx_hist = _history(tnx_sym)
    dxy_used_sym, dxy_hist = _first_history(DXY_CANDIDATES)

    gc_ret = gc_hist.pct_change().dropna() if gc_hist is not None else None
    gld_ret = gld_hist.pct_change().dropna() if gld_hist is not None else None
    spx_ret = spx_hist.pct_change().dropna() if spx_hist is not None else None
    dxy_ret = dxy_hist.pct_change().dropna() if dxy_hist is not None else None

    dxy_level = float(dxy_hist.iloc[-1]) if dxy_hist is not None else None
    dxy_chg_1d = _pct_change_over(dxy_hist, 1)
    dxy_chg_5d = _pct_change_over(dxy_hist, 5)

    # ^TNX is quoted directly in yield percent (e.g. 4.78 -> 4.78%).
    tnx_pct = float(tnx_hist.iloc[-1]) if tnx_hist is not None else None
    tnx_chg_5d_bp = None
    if tnx_hist is not None and len(tnx_hist) > 5:
        tnx_chg_5d_bp = float((tnx_hist.iloc[-1] - tnx_hist.iloc[-6]) * 100)

    gold_vs_dxy = _corr(gc_ret, dxy_ret, window) if gc_ret is not None and dxy_ret is not None else None
    gold_vs_spx = _corr(gc_ret, spx_ret, window) if gc_ret is not None and spx_ret is not None else None
    gc_vs_gld = _corr(gc_ret, gld_ret, window) if gc_ret is not None and gld_ret is not None else None

    return {
        "window_days": window,
        "dxy": {
            "symbol": dxy_used_sym,
            "level": round(dxy_level, 2) if dxy_level is not None else None,
            "chg_1d_pct": round(dxy_chg_1d * 100, 2) if dxy_chg_1d is not None else None,
            "chg_5d_pct": round(dxy_chg_5d * 100, 2) if dxy_chg_5d is not None else None,
        },
        "yield_10y_nominal": {
            "symbol": tnx_sym,
            "pct": round(tnx_pct, 3) if tnx_pct is not None else None,
            "chg_5d_bp": round(tnx_chg_5d_bp, 1) if tnx_chg_5d_bp is not None else None,
        },
        "correlations": {
            "gold_vs_dxy": round(gold_vs_dxy, 2) if gold_vs_dxy is not None else None,
            "gold_vs_spx": round(gold_vs_spx, 2) if gold_vs_spx is not None else None,
            "gc_vs_gld": round(gc_vs_gld, 2) if gc_vs_gld is not None else None,
        },
    }


def classify_regime(dxy_chg_5d_pct: float | None, yield_chg_5d_bp: float | None) -> tuple[str, str]:
    """Heuristic macro read: dollar direction + rate direction, both matter for gold.
    Uses the real 10Y yield change when FRED is configured (passed in by the
    caller), otherwise falls back to the nominal ^TNX 5d change."""
    if dxy_chg_5d_pct is None or yield_chg_5d_bp is None:
        return "MIXED", "Insufficient data for a directional macro read."
    dollar_bearish = dxy_chg_5d_pct < -0.1
    dollar_bullish = dxy_chg_5d_pct > 0.1
    yields_falling = yield_chg_5d_bp < -3
    yields_rising = yield_chg_5d_bp > 3
    if dollar_bearish and yields_falling:
        return "TAILWIND", "Dollar weakening and yields falling over 5 days — both support gold."
    if dollar_bullish and yields_rising:
        return "HEADWIND", "Dollar strengthening and yields rising over 5 days — both pressure gold."
    return "MIXED", "Dollar and yield signals aren't aligned over the last 5 days."
