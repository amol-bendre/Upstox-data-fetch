"""
Aggregation -- builds every higher timeframe FROM the 1-min base layer
fetched by fetch_nifty_ohlc.py.

Ported from nifty-fii-analytics' original aggregate.py (which built
15/30/1h/daily from a merged Yahoo+Upstox 5-min base) with two changes:

  1. Base input is now 1-min, not 5-min -- so 5min is added as a derived
     target alongside the existing 15min/30min/1h/daily.

  2. Origin is now an EXPLICIT session-open timestamp (09:15 by default; a
     special session passes its own trading_start) constructed per day,
     instead of origin='start' (which anchored to whatever the first
     row in that day's data happened to be). This was a deliberate
     safeguard: if the 09:15 candle is ever missing from the 1-min base
     (fetch gap, delayed start), origin='start' would have silently
     shifted the entire day's bucket grid to start from whatever candle
     WAS first -- this version keeps the grid pinned to true session
     open regardless of what's actually present in the data.

This module still doesn't know or care where the 1-min data came from
(Intraday vs Historical) -- that's fetch_nifty_ohlc.py's job.
"""
from datetime import datetime, time

import pandas as pd

TARGET_RULES = {
    "5min": "5min",
    "15min": "15min",
    "30min": "30min",
    "1h": "60min",
}


def aggregate_from_1min(df_1min: pd.DataFrame, target: str, origin_hm=(9, 15)) -> pd.DataFrame:
    """
    target: one of '5min', '15min', '30min', '1h', 'daily'
    origin_hm: (hour, minute) of the session open the bucket grid is pinned
        to. Default (9, 15) is the normal session; a special session such as
        Muhurat passes its own trading_start, e.g. (14, 20).
    """
    if df_1min.empty:
        return df_1min.copy()

    df = df_1min.copy()
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df = df.sort_values("timestamp")
    df["_date"] = df["timestamp"].dt.date

    if target == "daily":
        return _aggregate_daily(df)

    if target not in TARGET_RULES:
        raise ValueError(f"Unknown target interval: {target!r}. Expected one of {list(TARGET_RULES) + ['daily']}")

    rule = TARGET_RULES[target]
    out_frames = []

    for day_date, day_df in df.groupby("_date"):
        # Explicit 09:15 origin for THIS day, independent of whatever
        # timestamp actually appears first in day_df -- see module
        # docstring for why this matters.
        day_origin = pd.Timestamp(datetime.combine(day_date, time(origin_hm[0], origin_hm[1])))

        day_df = day_df.set_index("timestamp")
        resampled = day_df.resample(rule, origin=day_origin, label="left", closed="left").agg(
            open=("open", "first"),
            high=("high", "max"),
            low=("low", "min"),
            close=("close", "last"),
        )
        resampled = resampled.dropna(subset=["open"])  # drop buckets with no trades in them
        resampled = resampled.reset_index()
        out_frames.append(resampled)

    if not out_frames:
        return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close"])

    result = pd.concat(out_frames, ignore_index=True)
    result = result.sort_values("timestamp").reset_index(drop=True)
    return result


def _aggregate_daily(df: pd.DataFrame) -> pd.DataFrame:
    grouped = (
        df.groupby("_date")
        .agg(
            timestamp=("timestamp", "first"),  # first candle of the day = 09:15
            open=("open", "first"),
            high=("high", "max"),
            low=("low", "min"),
            close=("close", "last"),
        )
        .reset_index(drop=True)
    )
    return grouped.sort_values("timestamp").reset_index(drop=True)


def aggregate_all(df_1min: pd.DataFrame, origin_hm=(9, 15)) -> dict:
    """Convenience: build every derived granularity in one call.
    Returns {'5min': df, '15min': df, '30min': df, '1h': df, 'daily': df}"""
    return {
        "5min": aggregate_from_1min(df_1min, "5min", origin_hm),
        "15min": aggregate_from_1min(df_1min, "15min", origin_hm),
        "30min": aggregate_from_1min(df_1min, "30min", origin_hm),
        "1h": aggregate_from_1min(df_1min, "1h", origin_hm),
        "daily": aggregate_from_1min(df_1min, "daily", origin_hm),
    }
