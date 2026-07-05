# Binance Futures Crypto Screener

Scans all Binance USDT-M perpetual futures every hour, keeps a persistent
watchlist of coins that are trending **and** sitting on a valid trendline,
and removes them when a confirmed 3-candle breakout invalidates the setup.

## Logic pipeline

1. **BTC-correlation filter** — Pearson correlation with BTCUSDT over the
   last 30 **and** 90 daily candles must both be `<= 0.5`.
   By default the correlation is computed on daily *returns* (the
   statistically sound approach — raw-price correlation between two trending
   assets is almost always spuriously high). Set `CORR_ON_RETURNS = False`
   in `config.py` to use raw close prices instead.
2. **Trend structure** (per timeframe: m15, h1, h4, d1) — at least
   3 Higher Highs + 3 Higher Lows (uptrend) or 3 Lower Highs + 3 Lower Lows
   (downtrend). A Higher High is a *relation* between two consecutive swing
   highs, so 3 HHs require **4 strictly rising swing highs** (and likewise
   per side) — this is what the code enforces. Swings come from a
   non-repainting ±5-bar extremum algorithm that discards unconfirmed
   pivots near both data edges.
3. **Trendline** — least-squares line through the trend's Higher Lows
   (uptrend support) or Lower Highs (downtrend resistance); only the
   trailing monotonic swing run is fitted, and it requires ≥ 3 confirmed
   touches within 0.5% of the line plus the correct slope sign.
4. **Distance check** — latest closed candle must be within **0.5%** of the
   projected trendline.
5. **Invalidation** — a coin is removed when this 3-candle sequence closes
   through the line (below support / above resistance):
   - **C1** closes through the line on volume `>= 2× Volume-MA(20)`
   - **C2** closes through the line and is **not** a hammer
     (shooting star for downtrends)
   - **C3** closes through the line

The watchlist is persisted to `watchlist.json` between cycles and restarts.
Trendlines are stored as `slope/intercept` anchored to a candle timestamp,
so they are projected forward onto new candles in later cycles.

## Install

```bash
pip install -r requirements.txt
```

> `pandas_ta` is intentionally **not** used — it is unmaintained and breaks
> on modern numpy/Python. The only indicators needed (volume SMA, candle
> patterns) are implemented directly in pandas/numpy.

## Run

```bash
python screener.py                 # loop forever, scan every hour
python screener.py --once          # single scan cycle, then exit
python screener.py --once --max-symbols 30   # quick smoke test
python screener.py --interval 1800 # custom cycle length (seconds)
```

No API keys are required — only public market-data endpoints are used.

### Network access

Binance API endpoints are unreachable from some countries — either Binance
geo-blocks the region (HTTP 451, e.g. the US) or the local ISP blocks the
exchange domains (connection/SSL errors during the handshake, common in
Indonesia). The screener survives this gracefully (it retries and waits for
the next cycle), but it can't screen anything without data. Options:

- run it on a VPS in a supported region, or
- route it through a VPN/proxy. `ccxt` honors the standard proxy
  environment variable, so no code change is needed:

  ```powershell
  $env:HTTPS_PROXY = "http://127.0.0.1:7890"   # your proxy address
  python screener.py
  ```

A full scan of ~300 symbols takes several minutes because Binance rate
limits are respected (`enableRateLimit` in ccxt).

## Files

| File | Purpose |
|---|---|
| `config.py` | every tunable parameter of the strategy |
| `exchange.py` | ccxt data access with retry/rate-limit handling |
| `analysis.py` | swings, trend, trendline, patterns, breakout logic |
| `watchlist.py` | JSON-persisted watchlist state |
| `screener.py` | scan cycle orchestration, rich output, main loop |
| `watchlist.json` | generated at runtime — current watchlist state |

## Tuning

All thresholds live in `config.py`: swing sensitivity (`SWING_ORDER`),
number of required swings/touches, the 0.5% distance and touch tolerances,
volume-spike multiple, hammer geometry, and the scan interval.
