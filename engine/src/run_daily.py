"""Orchestrator: pick source -> load chain -> compute levels -> write outputs.

Usage:
    python -m src.run_daily              # uses config.yaml + .env
    python -m src.run_daily --source yfinance
"""
from __future__ import annotations
import argparse
import os
import sys
import yaml
from dotenv import load_dotenv

from . import engine
from . import writer


def load_cfg(path="config.yaml"):
    with open(path) as f:
        return yaml.safe_load(f)


def pick_loader(source: str):
    if source == "yfinance":
        from . import data_yf
        return data_yf.load_chain
    if source == "dxfeed":
        from . import data_dxfeed
        return data_dxfeed.load_chain
    # auto: dxfeed if token present, else yfinance
    if os.environ.get("DXFEED_TOKEN", "").strip():
        from . import data_dxfeed
        return data_dxfeed.load_chain
    from . import data_yf
    return data_yf.load_chain


def main():
    load_dotenv()
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", default=None, help="auto|dxfeed|yfinance")
    ap.add_argument("--config", default="config.yaml")
    args = ap.parse_args()

    cfg = load_cfg(args.config)
    source = args.source or cfg.get("source", "auto")

    loader = pick_loader(source)
    try:
        df, meta = loader(cfg)
    except NotImplementedError as e:
        # dxfeed not ready -> fall back to yfinance in auto mode
        if source in ("auto", "dxfeed") and cfg.get("source", "auto") != "dxfeed":
            print(f"[warn] {e}\n[warn] falling back to yfinance", file=sys.stderr)
            from . import data_yf
            df, meta = data_yf.load_chain(cfg)
        else:
            raise

    if df.empty:
        print("[error] empty options chain — check data source/entitlement", file=sys.stderr)
        sys.exit(1)

    result = engine.compute(df, meta, cfg)
    out = writer.write_outputs(result, cfg)

    R, L = result["regime"], result["levels_xauusd"]
    print(f"source   : {result['data_source']}")
    print(f"spot XAU : {result['underlying']['xauusd']:,.1f}")
    print(f"regime   : {R['state']}  net_gex={R['net_gex']/1e9:+.2f}B  net_dex={R['net_dex']/1e9:+.2f}B")
    print(f"flip     : {L['gamma_flip']}")
    print(f"call wall: {L['call_wall']}   put wall: {L['put_wall']}   hvl: {L['hvl']}")
    print(f"written  : {out}/levels.json, brief.md, pine_seed.txt")


if __name__ == "__main__":
    main()
