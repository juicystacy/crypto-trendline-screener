"""
Watchlist state management.

The watchlist survives between hourly scan cycles (and process restarts)
as a JSON file. Entries are keyed "SYMBOL|timeframe" so the same coin can
be on the list independently for m15, h1, h4 and d1.
"""

import json
import logging
import os
import tempfile
import time

import config

log = logging.getLogger("screener.watchlist")


def entry_key(symbol: str, timeframe: str) -> str:
    return f"{symbol}|{timeframe}"


# Keys the engine reads on every cycle — an entry missing any of these
# (hand-edited file, older schema…) would crash the scan loop.
_REQUIRED_KEYS = {"symbol", "timeframe", "direction", "trendline", "added_ts"}
_REQUIRED_TL_KEYS = {"slope", "intercept", "anchor_ts"}


def _entry_is_valid(entry) -> bool:
    return (isinstance(entry, dict)
            and _REQUIRED_KEYS <= entry.keys()
            and entry["timeframe"] in config.TIMEFRAMES
            and isinstance(entry["trendline"], dict)
            and _REQUIRED_TL_KEYS <= entry["trendline"].keys())


def load_watchlist(path: str = config.WATCHLIST_FILE) -> dict:
    """
    Load the watchlist from disk; start empty if missing or corrupt.
    Entries that don't match the expected schema are dropped with a warning
    instead of crashing every subsequent scan cycle.
    """
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (json.JSONDecodeError, OSError) as exc:
        log.warning("Could not read watchlist (%s) — starting empty.", exc)
        return {}
    if not isinstance(data, dict):
        log.warning("Watchlist file has unexpected format — starting empty.")
        return {}

    valid = {k: v for k, v in data.items() if _entry_is_valid(v)}
    for key in data.keys() - valid.keys():
        log.warning("Dropping malformed watchlist entry %r", key)
    return valid


def save_watchlist(watchlist: dict, path: str = config.WATCHLIST_FILE) -> None:
    """Atomic write (tmp file + replace) so a crash can't corrupt state."""
    directory = os.path.dirname(os.path.abspath(path))
    fd, tmp_path = tempfile.mkstemp(dir=directory, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(watchlist, fh, indent=2)
        os.replace(tmp_path, path)
    except OSError as exc:
        log.error("Failed to save watchlist: %s", exc)
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


def upsert_entry(watchlist: dict, symbol: str, timeframe: str,
                 evaluation: dict, corrs: dict) -> None:
    """
    Add a newly qualified coin, or refresh an existing entry with the
    latest trendline/distance (keeps the original added_ts).
    """
    key = entry_key(symbol, timeframe)
    now = int(time.time() * 1000)
    existing = watchlist.get(key)

    watchlist[key] = {
        "symbol": symbol,
        "timeframe": timeframe,
        "direction": evaluation["direction"],
        "trendline": evaluation["trendline"],
        # Open ts of the last closed candle when this line was (re)fitted —
        # breakout candles must come strictly AFTER it.
        "tl_fit_ts": evaluation["last_candle_ts"],
        "distance_pct": evaluation["distance_pct"],
        "close": evaluation["close"],
        "corr_30d": corrs.get(30),
        "corr_90d": corrs.get(90),
        "added_ts": existing["added_ts"] if existing else now,
        "updated_ts": now,
    }


def remove_entry(watchlist: dict, key: str, reason: str) -> None:
    entry = watchlist.pop(key, None)
    if entry:
        log.info("REMOVED %s %s — %s",
                 entry["symbol"], entry["timeframe"], reason)
