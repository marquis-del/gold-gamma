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


def _star(rc: dict, key: str) -> str:
    hit = (rc or {}).get(key) or {}
    return " ⭐" if hit.get("is_confluence") else ""


def build_brief(result: dict) -> str:
    L = result["levels_xauusd"]
    R = result["regime"]
    u = result["underlying"]
    RC = result.get("round_confluence")
    spot = u["xauusd"]
    flip = L.get("gamma_flip")
    sup = R["state"] == "SUPPRESSION"
    lines = [
        f"# Gold Gamma Brief — {dt.date.today():%A %b %d, %Y}",
        "",
        f"**Spot (XAUUSD):** {_fmt(spot)}  |  **Source:** {result['data_source']}",
        f"**Regime:** {R['state']}  |  **Net GEX:** {_money(R['net_gex'])}  |  **Net DEX:** {_money(R['net_dex'])}"
        f"  |  **Net VEX:** {_money(R.get('net_vex'))}  |  **Net CEX/day:** {_money(R.get('net_cex'))}",
        f"**Gamma flip:** {_fmt(flip)}{_star(RC,'gamma_flip')}  |  **Call wall:** {_fmt(L['call_wall'])}{_star(RC,'call_wall')}"
        f"  |  **Put wall:** {_fmt(L['put_wall'])}{_star(RC,'put_wall')}  |  **HVL:** {_fmt(L['hvl'])}{_star(RC,'hvl')}",
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
    M = result.get("macro")
    if M:
        rate_label = "real 10Y" if M["regime"]["rate_basis"] == "real_10y" else "nominal 10Y"
        rate_val = (M.get("real_yield_10y") or {}).get("pct") if M["regime"]["rate_basis"] == "real_10y" else M["yield_10y_nominal"]["pct"]
        lines += [
            "",
            "## Macro backdrop",
            f"**Regime:** {M['regime']['state']} — {M['regime']['description']}",
            f"DXY {_fmt(M['dxy']['level'])} ({M['dxy']['chg_5d_pct']:+.2f}% 5d)  |  {rate_label} {rate_val:.2f}%  |  "
            f"gold/DXY corr {M['correlations']['gold_vs_dxy']}  |  gold/SPX corr {M['correlations']['gold_vs_spx']}",
            f"_GLD-proxy trust check — GC/GLD {M['window_days']}d return correlation: {M['correlations']['gc_vs_gld']}._",
        ]
    if RC and any((RC.get(k) or {}).get("is_confluence") for k in ("call_wall", "put_wall", "hvl", "gamma_flip")):
        lines += ["", f"_⭐ = within ${RC['tolerance']:g} of a round ${RC['step']:g} level — {RC['note']}_"]
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
