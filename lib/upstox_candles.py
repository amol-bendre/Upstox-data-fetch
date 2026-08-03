"""
The one shared fetch function used by both the Nifty OHLC script and the
options EOD batch script.

Confirmed empirically (not assumed) on 30-31 Jul 2026:
  - Historical endpoint does NOT have today's 1-min data, even as late as
    11:30 PM IST, and still doesn't a few minutes past midnight either.
  - Intraday endpoint DOES reliably have a full day's 1-min data, tested
    as late as 11:30 PM IST.
  - Intraday is calendar-day-based, not session-based: the instant the
    wall clock crosses midnight IST, Intraday silently starts answering
    for the NEW (unopened) day -- there is no way to ask it for
    "yesterday". This is why the date-guard in fetch_runner.py exists.

So: target_date == today -> Intraday. Any other date -> Historical.
"""
from datetime import datetime
from typing import NamedTuple

import requests

from lib.config import BASE_V2, BASE_V3
from lib.date_utils import today_ist_str


class CandleResult(NamedTuple):
    status: str          # 'ok' | 'empty' | 'http_error'
    candles: list         # list of [timestamp, open, high, low, close, volume, oi]
    http_status: int | None
    detail: str           # short human-readable note, for logging


def fetch_candles(instrument_key: str, target_date: str, token: str) -> CandleResult:
    headers = {"Accept": "application/json", "Authorization": f"Bearer {token}"}

    if target_date == today_ist_str():
        url = f"{BASE_V2}/historical-candle/intraday/{instrument_key}/1minute"
    else:
        url = f"{BASE_V3}/historical-candle/{instrument_key}/minutes/1/{target_date}/{target_date}"

    try:
        r = requests.get(url, headers=headers, timeout=20)
    except requests.RequestException as e:
        return CandleResult("http_error", [], None, f"request failed: {e}")

    if r.status_code != 200:
        return CandleResult("http_error", [], r.status_code, f"HTTP {r.status_code}: {r.text[:200]}")

    try:
        candles = r.json().get("data", {}).get("candles", [])
    except ValueError:
        return CandleResult("http_error", [], r.status_code, "response was not valid JSON")

    if not candles:
        return CandleResult("empty", [], r.status_code, "zero candles returned")

    return CandleResult("ok", candles, r.status_code, f"{len(candles)} candles")
