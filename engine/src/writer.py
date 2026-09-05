"""Write the engine outputs: levels.json (for the dashboard + Pine seed),
brief.md (human game plan), pine_seed.txt (one line to paste into TradingView)."""
from __future__ import annotations
import json
import os
import datetime as dt


def _fmt(x):
    return "n/a" if x is None else f"{x:,.1f}"


def _money(x):
    if x is None:
        return "n/a"
    s = "-" if x < 0 else "+"
    return f"{s}${abs(x)/1e9:.2f}B"


def build_brief(result: dict) -> str:
    L = result["levels_xauusd"]
    R = result["regime"]
    u = result["underlying"]
    spot = u["xauusd"]
    flip = L.get("gamma_flip")
    sup = R["state"] == "SUPPRESSION"
    lines = [
        f"# Gold Gamma Brief — {dt.date.today():%A %b %d, %Y}",
        "",
        f"**Spot (XAUUSD):** {_fmt(spot)}  |  **Source:** {result['data_source']}",
        f"**Regime:** {R['state']}  |  **Net GEX:** {_money(R['net_gex'])}  |  **Net DEX:** {_money(R['net_dex'])}",
        f"**Gamma flip:** {_fmt(flip)}  |  **Call wall:** {_fmt(L['call_wall'])}  |  **Put wall:** {_fmt(L['put_wall'])}  |  **HVL:** {_fmt(L['hvl'])}",
        "",
        "## Game plan",
    ]
    if sup:
        lines += [
            f"- Positive gamma / above flip {_fmt(flip)}: contained, mean-reverting tape.",
            f"- Fade rallies into the call wall {_fmt(L['call_wall'])}; buy dips toward the HVL magnet {_fmt(L['hvl'])}.",
            f"- Losing {_fmt(flip)} flips to AMPLIFICATION — momentum turns on, next support the put wall {_fmt(L['put_wall'])}.",
        ]
    else:
        lines += [
            f"- Negative gamma / below flip {_fmt(flip)}: trending, volatile tape — respect momentum.",
            f"- Breakdowns extend toward the put wall {_fmt(L['put_wall'])}; reclaiming {_fmt(flip)} restores suppression.",
            f"- Rallies can run to the call wall {_fmt(L['call_wall'])} before dealers cap them.",
        ]
    lines += ["", f"_OI is prior-session settlement (T+1). Sign convention: {result['sign_convention']}. Positioning context, not financial advice._"]
    return "\n".join(lines)


def build_pine_seed(result: dict) -> str:
    L = result["levels_xauusd"]
    sec = L.get("secondary", []) + [None, None, None]
    parts = [
        f"callWall={_num(L['call_wall'])}", f"putWall={_num(L['put_wall'])}",
        f"hvl={_num(L['hvl'])}", f"flip={_num(L['gamma_flip'])}",
        f"s1={_num(sec[0])}", f"s2={_num(sec[1])}", f"s3={_num(sec[2])}",
        f"regime={result['regime']['state']}",
    ]
    return ",".join(parts)


def _num(x):
    return "" if x is None else f"{x:g}"


def write_outputs(result: dict, cfg: dict, oi_date: str | None = None):
    out = cfg.get("output_dir", "./public")
    os.makedirs(out, exist_ok=True)
    payload = dict(result)
    payload["asof_utc"] = dt.datetime.now(dt.timezone.utc).isoformat()
    payload["oi_date"] = oi_date or (dt.date.today() - dt.timedelta(days=1)).isoformat()
    payload["notes"] = "OI is prior-session settlement (T+1). Intraday flow not reflected."

    with open(os.path.join(out, "levels.json"), "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    with open(os.path.join(out, "brief.md"), "w", encoding="utf-8") as f:
        f.write(build_brief(result))
    with open(os.path.join(out, "pine_seed.txt"), "w", encoding="utf-8") as f:
        f.write(build_pine_seed(result))
    return out
