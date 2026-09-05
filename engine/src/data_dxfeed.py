"""PRIMARY data source: dxFeed (real /GC COMEX gold futures options book).

dxFeed computes greeks server-side and carries open interest across CME futures
options, so this path gives you the actual institutional gamma book — the
"100% accuracy" source. It hands us gamma/delta directly (no BSM needed for the
point-in-time snapshot); implied vol is still used by the flip solver.

=================  WHAT CLAUDE CODE MUST VERIFY (live, with the account)  ========
1. ACCESS METHOD. Confirm the current dxFeed Python path for this account:
     (a) the `dxfeed` PyPI package, OR
     (b) dxLink over WebSocket (implemented below as a skeleton), OR
     (c) the dxFeed REST webservice.
   Use whichever the entitlement/docs support; keep the load_chain() contract.
2. ENTITLEMENT. Confirm the subscription returns CME futures-options
   Greeks + Summary(openInterest). If not, this raises and `source: auto`
   falls back to GLD (src/data_yf.py) — tell the user.
3. SYMBOLOGY. Resolve the live /GC option symbols (front `expirations`) via the
   instrument profile / symbol lookup. DO NOT hardcode guessed tickers.
4. EVENTS to subscribe per option symbol:
     Greeks  -> gamma, delta, volatility     (point-in-time greeks + IV)
     Summary -> openInterest                  (dealer positioning size)
   Plus Quote/Trade on the /GC front future for the underlying gold price.
5. NORMALIZE to the exact frame engine.compute() expects (see engine.py):
     columns: type('C'/'P'), oi, iv, T(years), expiry, strike_native, strike
     For /GC, strike is ALREADY gold price -> strike == strike_native.
     meta: source, S_gold(=/GC price), gc_price, gld_price(optional), ratio(=1.0 for /GC)
=================================================================================
"""
from __future__ import annotations
import os
import json
import datetime as dt
import pandas as pd


def load_chain(cfg: dict, env: dict | None = None):
    token = (env or os.environ).get("DXFEED_TOKEN", "").strip()
    ws_url = (env or os.environ).get("DXFEED_WS_URL", "").strip()
    if not token or not ws_url:
        raise NotImplementedError(
            "dxFeed not configured: set DXFEED_TOKEN and DXFEED_WS_URL in .env. "
            "Until then, use source: yfinance (free GLD fallback)."
        )

    # ---- IMPLEMENT with your verified access method (see header, item 1) ----
    # Skeleton for the dxLink WebSocket path is in _DxLinkSnapshot below.
    # Steps:
    #   1) symbols = resolve_gc_option_symbols(cfg["expirations"])   # item 3
    #   2) snap = _DxLinkSnapshot(ws_url, token).collect(
    #          symbols, events=["Greeks", "Summary"], underlying="/GC:<front>")
    #   3) df, meta = _normalize(snap, cfg)
    #   4) return df, meta
    raise NotImplementedError(
        "dxFeed client not implemented yet. Claude Code: implement per the header "
        "checklist against the live account, then remove this raise."
    )


# ---------------------------------------------------------------------------
# dxLink WebSocket snapshot skeleton (verify frame shapes against dxFeed docs).
# dxLink is a JSON-over-WebSocket protocol: SETUP -> AUTH -> CHANNEL_REQUEST(FEED)
# -> FEED_SETUP -> FEED_SUBSCRIPTION -> receive FEED_DATA events -> close.
# ---------------------------------------------------------------------------
class _DxLinkSnapshot:
    def __init__(self, ws_url: str, token: str):
        self.ws_url = ws_url
        self.token = token

    def collect(self, symbols, events, underlying, timeout=20):
        """Return {symbol: {event: {...fields...}}}. IMPLEMENT with `websockets`.

        Pseudocode:
            async with websockets.connect(self.ws_url) as ws:
                await send(SETUP)                       # keepaliveTimeout etc.
                await send(AUTH, token=self.token)      # wait AUTH_STATE=AUTHORIZED
                await send(CHANNEL_REQUEST, channel=1, service="FEED")
                await send(FEED_SETUP, acceptEventFields={
                    "Greeks":  ["eventSymbol","gamma","delta","volatility"],
                    "Summary": ["eventSymbol","openInterest"],
                    "Quote":   ["eventSymbol","bidPrice","askPrice"],
                })
                await send(FEED_SUBSCRIPTION, add=[{"type": e, "symbol": s}
                                                   for s in symbols for e in events]
                                                  + [{"type":"Quote","symbol":underlying}])
                # accumulate FEED_DATA until each symbol has Greeks+Summary or timeout
        """
        raise NotImplementedError


def _normalize(snap: dict, cfg: dict):
    """Turn the collected snapshot into engine.compute()'s frame + meta."""
    rows = []
    # for sym, ev in snap.items():
    #     g, s = ev.get("Greeks", {}), ev.get("Summary", {})
    #     typ, strike, expiry, T = _parse_gc_option_symbol(sym)   # item 3/5
    #     rows.append({"type": typ, "oi": s["openInterest"], "iv": g["volatility"],
    #                  "T": T, "expiry": expiry, "strike_native": strike,
    #                  "strike": strike, "gamma": g["gamma"], "delta": g["delta"]})
    df = pd.DataFrame(rows)
    gc_price = None  # from Quote on the underlying
    meta = {"source": "dxfeed:/GC", "S_gold": gc_price, "gc_price": gc_price,
            "gld_price": None, "ratio": 1.0}
    return df, meta
