"""
Binance USDT-M Futures data access layer (via ccxt).

Public market data only — no API keys required. All calls go through a
retry wrapper that handles rate limits and transient network errors.
"""

import time
import logging

import ccxt
import pandas as pd

import config

log = logging.getLogger("screener.exchange")


def build_exchange() -> ccxt.binanceusdm:
    """Create a ccxt Binance USDT-M futures client with rate limiting on."""
    return ccxt.binanceusdm({
        "enableRateLimit": True,      # ccxt paces requests under Binance limits
        "options": {"defaultType": "swap"},
    })


def _with_retries(fn, *args, **kwargs):
    """
    Run an API call with bounded retries.

    RateLimitExceeded / DDoSProtection back off longer than plain network
    timeouts. After MAX_API_RETRIES the exception propagates to the caller,
    which skips that symbol instead of killing the scan cycle.
    """
    last_exc = None
    for attempt in range(1, config.MAX_API_RETRIES + 1):
        try:
            return fn(*args, **kwargs)
        except (ccxt.RateLimitExceeded, ccxt.DDoSProtection) as exc:
            last_exc = exc
            wait = config.RETRY_BACKOFF_SEC * attempt * 2
            log.warning("Rate limited (attempt %d/%d) — sleeping %ds",
                        attempt, config.MAX_API_RETRIES, wait)
            time.sleep(wait)
        except (ccxt.NetworkError, ccxt.ExchangeNotAvailable,
                ccxt.RequestTimeout) as exc:
            last_exc = exc
            wait = config.RETRY_BACKOFF_SEC * attempt
            log.warning("Network error (attempt %d/%d): %s — sleeping %ds",
                        attempt, config.MAX_API_RETRIES, exc, wait)
            time.sleep(wait)
    raise last_exc


def get_usdt_perp_symbols(exchange: ccxt.binanceusdm) -> list[str]:
    """
    Return every active USDT-margined linear perpetual symbol
    (ccxt unified format, e.g. 'ETH/USDT:USDT').
    """
    markets = _with_retries(exchange.load_markets, True)
    symbols = [
        m["symbol"]
        for m in markets.values()
        if m.get("swap")                                # perpetual futures only
        and m.get("linear")
        and m.get("active")
        and m.get("quote") == config.QUOTE_ASSET
    ]
    return sorted(symbols)


def get_tradfi_symbols(exchange: ccxt.binanceusdm) -> set[str]:
    """
    Symbols whose underlying is a TradFi asset (stocks, commodities, gold…)
    rather than a crypto coin — Binance tags these in exchangeInfo:
    underlyingType EQUITY/COMMODITY, or subtype TradFi/RWA (e.g. XAUT).
    The BTC-correlation filter is meaningless for these.

    Assumes load_markets() was already called (get_usdt_perp_symbols does).
    """
    return {
        m["symbol"]
        for m in exchange.markets.values()
        if m.get("info", {}).get("underlyingType") not in (None, "COIN")
        or {"TradFi", "RWA"} & set(m.get("info", {}).get("underlyingSubType") or [])
    }


def fetch_ohlcv_df(exchange: ccxt.binanceusdm, symbol: str,
                   timeframe: str, limit: int) -> pd.DataFrame | None:
    """
    Fetch OHLCV candles as a DataFrame with columns
    [ts, open, high, low, close, volume]. The still-forming candle is
    dropped so every rule operates on CLOSED candles only.

    Returns None when the symbol can't be fetched (delisted, API error…)
    so the caller can simply skip it.
    """
    try:
        raw = _with_retries(exchange.fetch_ohlcv, symbol,
                            timeframe=timeframe, limit=limit)
    except ccxt.BaseError as exc:
        log.warning("fetch_ohlcv failed for %s %s: %s", symbol, timeframe, exc)
        return None

    if not raw or len(raw) < 2:
        return None

    df = pd.DataFrame(raw, columns=["ts", "open", "high", "low",
                                    "close", "volume"])
    # Last row is the live, unfinished candle — drop it.
    df = df.iloc[:-1].reset_index(drop=True)
    return df
