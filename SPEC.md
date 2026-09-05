# Gold Dealer Positioning Engine — Build Spec

**For:** Marquis
**Goal:** A daily system that reads options-market dealer hedging pressure on gold (gamma exposure + delta exposure) and turns it into (1) tradable levels on a XAUUSD TradingView chart and (2) a phone dashboard showing the day's dealer-hedging environment.

**Chart target:** XAUUSD (spot). **Primary data:** dxFeed (real /GC COMEX futures options greeks + open interest). **Free fallback:** GLD ETF options via yfinance.

---

## 0. Kickoff prompt (paste this into Claude Code first)

> I'm building the **Gold Dealer Positioning Engine**. Read `SPEC.md` in this folder end to end, then implement **Phase 1 (v1)** exactly as specified. Before writing code, restate the architecture back to me in 5 bullets and list the exact dxFeed symbols/event types you'll subscribe to for /GC options, and confirm my dxFeed entitlements cover CME futures options greeks + open interest. Then scaffold the repo, set up config for my dxFeed credentials via a `.env` file (never hardcode secrets), and build the pipeline step by step, running each stage and showing me the output before moving on. Start with the data layer: connect to dxFeed, pull the front two /GC option expirations, and print a table of strike / call OI / put OI / call gamma / put gamma so we can eyeball it before computing anything.

Then work through the spec section by section. Keep a running `README.md` and commit after each working stage.

---

## 1. The edge (why this works — so you understand intent)

Options dealers (market makers) are on the other side of most retail and institutional option trades. When they hold those positions they must hedge the delta by trading the underlying — for gold, that's GLD/IAU shares **and, where the big institutional gamma sits, /GC COMEX futures**. Basis arbitrage links the two, so gold's *effective* hedging pressure is the combined book, and it lands directly on the futures/spot price you trade.

The sign of net dealer gamma sets the regime:

- **Positive gamma (dealers long gamma):** dealers *buy dips and sell rallies* → volatility is **suppressed**, price mean-reverts, ranges hold. Fade extremes back toward the biggest gamma strike.
- **Negative gamma (dealers short gamma):** dealers *sell into declines and buy into rallies* → volatility is **amplified**, moves trend and extend. Respect breakouts, expect momentum.

The levels that matter:

- **Gamma Flip / Zero Gamma** — the price where net dealer gamma crosses from + to −. The single most important line: it's the switch between the two regimes above.
- **Call Wall** — strike with the largest concentrated call gamma. Acts as **resistance** (dealers short those calls sell into it).
- **Put Wall** — strike with the largest concentrated put gamma. Acts as **support** (dealers buy to defend).
- **HVL (High-gamma / "magnet" strike)** — strike with the largest absolute total gamma; price tends to gravitate here into expirations ("pinning").
- **DEX (Delta Exposure)** — net dealer delta; tells you the *direction* of standing hedging pressure and how it shifts as price moves.

---

## 2. Architecture (v1)

```
                    ┌─────────────────────────────┐
   dxFeed (primary) │  DATA LAYER                 │
   /GC opt greeks + │  - connect + auth (dxLink)  │
   open interest    │  - pull option series       │
   + underlying     │  - Greeks + Summary events  │
        │           │  - normalize to a chain df  │
   GLD/yfinance ────┤                             │
   (free fallback)  └──────────────┬──────────────┘
                                    │  chain.parquet (raw snapshot)
                    ┌──────────────▼──────────────┐
                    │  COMPUTE ENGINE             │
                    │  - per-strike GEX / DEX     │
                    │  - net GEX, net DEX         │
                    │  - zero-gamma (flip) solve  │
                    │  - call/put walls, HVL      │
                    │  - regime classification    │
                    │  - map strikes → XAUUSD     │
                    └──────────────┬──────────────┘
                                   │  levels.json  +  brief.md  +  pine_seed.txt
              ┌────────────────────┼─────────────────────┐
   ┌──────────▼─────────┐ ┌────────▼────────┐  ┌─────────▼──────────┐
   │ PUBLISH            │ │ TRADINGVIEW      │  │ PHONE DASHBOARD    │
   │ push levels.json   │ │ paste pine_seed  │  │ PWA fetches        │
   │ to static host     │ │ into indicator   │  │ levels.json        │
   └────────────────────┘ └──────────────────┘  └────────────────────┘
```

Run once each morning after prior-session open-interest settles (see §8), plus optional intraday refreshes for greeks/price.

---

## 3. Data layer

### 3.1 Primary — dxFeed (use this)

dxFeed computes greeks server-side and carries open interest, across equities **and CME futures options**, so we pull the real /GC gamma book directly (no Black-Scholes needed on this path).

- **Access:** dxLink WebSocket (token-based) or the dxFeed REST webservice. Use my existing dxFeed credentials. Prefer the maintained Python path (dxLink client / `dxfeed-graal`-based SDK); if the SDK is awkward, fall back to a thin dxLink WebSocket client.
- **Event types to subscribe:**
  - `Greeks` → `gamma`, `delta`, `volatility`, `price` (per option symbol).
  - `Summary` → `openInterest` (per option symbol).
  - `Quote` / `Trade` on the underlying (/GC front future) → spot reference.
  - `Series` / instrument profile (IPF) → enumerate available /GC expirations and strikes.
- **Symbology:** CME futures-option symbols must match my entitlement. **Do not guess tickers** — first query the instrument profile / symbol lookup to list the live /GC option symbols, confirm the format, then subscribe. Verify my subscription actually returns CME futures-options greeks + OI; if it doesn't, fall back to §3.2 and tell me.
- **Scope for v1:** the front **two** monthly /GC option expirations (nearest liquidity). Make the number of expirations a config value.

### 3.2 Free fallback — GLD via yfinance (for testing / if dxFeed CME entitlement is missing)

- `yfinance` pulls the GLD option chain (strikes, OI, IV, expiries) with no key. Greeks aren't provided → compute **gamma and delta with Black-Scholes** from IV (`py_vollib` or a small local BSM).
- Underlying gold price: `GC=F` (front future) from yfinance.
- This path is also the **offline test fixture** — snapshot one chain to a file so the compute engine can be developed/tested without burning live calls.

### 3.3 Config

`.env` (git-ignored): dxFeed token/endpoint. `config.yaml`: expirations to include, contract multipliers (100 for GLD, 100 troy oz for /GC), basis offset (XAUUSD − /GC), refresh schedule, output host path. **No secrets in code or in levels.json.**

---

## 4. Compute engine (exact definitions)

Contract multiplier `M` = 100 (both GLD contracts and /GC, which is 100 troy oz). Spot `S` = underlying gold price.

**Per-strike gamma notional (naive dealer convention — dealers long calls, short puts):**

```
call_gex(K) = + call_gamma(K) * call_OI(K) * M * S^2 * 0.01
put_gex(K)  = - put_gamma(K)  * put_OI(K)  * M * S^2 * 0.01
gex(K)      = call_gex(K) + put_gex(K)
```

- The `* 0.01` expresses GEX as "$ of dealer hedging per 1% move." Keep it, and store raw gamma too.
- **The sign convention is an assumption.** Expose a `dealer_long_calls_short_puts` flag in config so we can flip/refine it later. Document the choice in the output.

**Net GEX** = Σ gex(K) over all strikes/expirations. Sign → regime.

**Zero Gamma / Gamma Flip (proper method, not just nearest strike):**
Recompute total GEX across a grid of hypothetical spot prices around current S (recompute each option's gamma at each candidate spot via BSM using its IV; on the dxFeed path, approximate by reusing per-strike gamma profiles or recompute from IV). Find the spot where total GEX crosses zero. That crossing = the flip level. Report it, plus the current spot's position relative to it.

**Call Wall** = strike with max positive `call_gex(K)`.
**Put Wall** = strike with max `|put_gex(K)|` (most negative).
**HVL / magnet** = strike with max `|gex(K)|` (absolute total gamma).
**Secondary strikes** = next 2–3 largest `|gex(K)|` for context on the ladder.

**DEX (Delta Exposure):**
```
dex(K) = (call_delta(K)*call_OI(K) + put_delta(K)*put_OI(K)) * M * S * sign_convention
net_DEX = Σ dex(K)
```
Report net DEX and its sign (net long/short dealer delta = direction of standing hedging pressure).

**Regime classification:**
- `spot > flip` AND `net_GEX > 0` → **SUPPRESSION** (mean-revert; fade toward HVL; call wall = resistance, put wall = support).
- `spot < flip` OR `net_GEX < 0` → **AMPLIFICATION** (trend/momentum; breakouts extend; walls can break).
- Include a numeric "distance to flip" and "distance to each wall" in ATR terms if an ATR feed is easy; otherwise in dollars and %.

**Price mapping to XAUUSD (chart target):**
- **dxFeed /GC path:** strikes are already in gold-price terms → map to XAUUSD with a small configurable **basis offset** (`xau = gc_strike + basis`), where `basis = live_XAUUSD − live_GC` (compute daily, usually a few dollars).
- **GLD fallback path:** convert each GLD strike to gold price with a **dynamic ratio** computed live each run: `gold_level = gld_strike * (gold_price / gld_price)` (≈10.7×, and this auto-handles GLD's expense-ratio drift). Then apply basis to XAUUSD.
- Always output levels in **all three scales** (XAUUSD, /GC, GLD) in levels.json so the numbers are reusable on any gold chart.

---

## 5. Outputs

### 5.1 `levels.json` (machine-readable — consumed by app + Pine seed generator)

```json
{
  "asof_utc": "2026-09-05T12:30:00Z",
  "data_source": "dxfeed:/GC",
  "oi_date": "2026-09-04",
  "sign_convention": "dealer_long_calls_short_puts",
  "underlying": { "gc": 2534.1, "xauusd": 2536.4, "gld": 236.9, "basis_xau_gc": 2.3 },
  "regime": { "state": "SUPPRESSION", "net_gex": 1.83e9, "net_dex": -4.2e8, "flip": { "gc": 2521.0, "xauusd": 2523.3 } },
  "levels_xauusd": {
    "call_wall": 2560.0, "put_wall": 2500.0, "hvl": 2540.0, "gamma_flip": 2523.3,
    "secondary": [2550.0, 2515.0, 2575.0]
  },
  "ladder": [ { "strike_xau": 2560, "gex": 9.1e8, "type": "call" }, "... top 12 strikes by |gex| ..." ],
  "notes": "OI is prior-session settlement (T+1). Intraday flow not reflected."
}
```

### 5.2 `brief.md` — human daily game plan
Auto-written plain-English summary: regime, where spot sits vs flip, the three walls with distance, and an if/then plan ("Above flip 2523 with positive gamma → fade rallies into call wall 2560, buy dips toward HVL 2540; losing 2523 flips to momentum, put wall 2500 next").

### 5.3 `pine_seed.txt` — one line to paste into the TradingView indicator
`callWall=2560,putWall=2500,hvl=2540,flip=2523.3,s1=2550,s2=2515,s3=2575,regime=SUPPRESSION`
The Pine indicator (see `gold_gamma_levels.pine`) parses this from a single text input so daily updates are one copy-paste.

---

## 6. TradingView indicator

A ready-to-use Pine v5 indicator ships alongside this spec: **`gold_gamma_levels.pine`**. It plots Call Wall, Put Wall, Gamma Flip, HVL and up to three secondary strikes as extended lines with labels, and tints the background by regime. v1 is manual: paste the daily `pine_seed` values into the indicator's inputs. **Phase 2** automates delivery (see §9). Keep the engine's XAUUSD outputs consistent with this indicator's inputs.

---

## 7. Phone dashboard (PWA)

A mobile-first dashboard shell already exists (single self-contained HTML). Wire it to live data:

- On load, `fetch()` the published `levels.json` and render: **regime banner** (green suppression / red amplification), **spot-vs-flip gauge**, **Call Wall / Put Wall / HVL cards** (with $ and % distance from spot), **net GEX & net DEX** tiles, a **key-strike gamma ladder** (horizontal bars, calls vs puts), and the **daily game plan** text. Show `asof`, `oi_date`, and data source.
- Make it an installable PWA (manifest + service worker) so it adds to the iOS/Android home screen and caches the last payload for offline glance.
- Pull-to-refresh re-fetches levels.json.

---

## 8. Scheduling & data-latency honesty

- **Open interest is end-of-session and published T+1** (CME settlement OI posts the next morning). So the morning run uses *prior-session* OI + *live* greeks/price. State this in every output; don't imply intraday OI.
- **Morning run** (~7:30–8:00 ET) writes the day's levels.json/brief/pine_seed and publishes.
- **Optional intraday refresh** (e.g., every 30–60 min during RTH) updates greeks, spot, DEX and distances using the same OI — cheap and useful for regime/flip proximity.
- Use a scheduler that survives reboots (cron / Task Scheduler / a small always-on worker / GitHub Actions if data access allows).

---

## 9. Phase roadmap

**Phase 1 (v1 — build now):** dxFeed /GC data → GEX/DEX/flip/walls/HVL → levels.json + brief + pine_seed → manual Pine paste + live phone dashboard. Free GLD fallback wired for testing.

**Phase 2:**
- **Combined book:** add GLD + IAU to the /GC book for gold's *effective* gamma.
- **Auto-delivery to TradingView:** publish levels.json to a static host and (a) auto-generate the pine_seed, (b) optionally use TradingView webhooks/alerts to surface level crosses.
- **Vanna & Charm exposure:** vanna (gamma's sensitivity to IV — drives grind-up into stable-vol windows) and charm (delta decay into expiry — drives pinning). Add VEX/charm tiles.
- **OpEx mapping:** monthly COMEX + GLD expirations, roll windows, "gamma unclench" after expiration.
- **Macro overlay:** 10Y real yields (TIPS), DXY, SPX correlation regime — gold gamma interacts with the macro tape (fits your macro-informed approach).
- **COT positioning:** weekly CFTC Commitments of Traders (managed money / swap-dealer net) as a slower-moving positioning confirm.
- **Alerts:** push/email when spot nears a wall, crosses the flip, or the regime flips.
- **Backtest module:** measure how often gold actually respects these levels (touch/reject/break stats, expectancy by regime) to build conviction and size accordingly.

---

## 10. Tech stack & repo structure

Python 3.11+. Suggested layout:

```
gold-gamma/
  .env                 # dxFeed creds (git-ignored)
  config.yaml
  src/
    data/dxfeed_client.py      # dxLink connect, subscribe Greeks+Summary+Quote
    data/yf_fallback.py        # GLD chain + BSM greeks
    compute/gex.py             # per-strike + net GEX/DEX
    compute/flip.py            # zero-gamma solver
    compute/levels.py          # walls, HVL, regime, XAUUSD mapping
    output/writer.py           # levels.json, brief.md, pine_seed.txt
    publish/push.py            # to static host
    schedule/run_daily.py      # orchestrator
  web/                         # PWA dashboard (index.html, manifest, sw.js)
  tradingview/gold_gamma_levels.pine
  tests/                       # uses the snapshot fixture
  README.md
```

Test with the offline GLD snapshot before going live. Log every run.

---

## 11. Guardrails

- **Secrets:** dxFeed creds in `.env` only; never in code, logs, or levels.json.
- **Sign convention is an assumption** — expose it, document it in output, make it flippable.
- **OI latency (T+1)** — always disclosed in output.
- **Entitlements** — verify dxFeed returns CME futures-options greeks + OI *before* building around it; fall back to GLD and tell me if not.
- **Not financial advice** — this is a positioning-context tool; it informs decisions, it doesn't make them.

---

## 12. Definition of done (v1)

1. `python src/schedule/run_daily.py` connects to dxFeed, pulls front-two /GC expirations, and writes valid `levels.json`, `brief.md`, `pine_seed.txt`.
2. `levels.json` contains regime, flip, call/put walls, HVL, secondary strikes — in XAUUSD, /GC, and GLD scales — plus net GEX and net DEX.
3. The Pine indicator, seeded from `pine_seed.txt`, plots correct levels on a XAUUSD chart.
4. The phone dashboard fetches `levels.json` and renders the full environment on a phone, installable to the home screen.
5. Runs unattended on the morning schedule; GLD fallback works when dxFeed is unavailable.
