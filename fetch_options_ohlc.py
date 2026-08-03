"""
Fetch 1-min OHLC for every strike (CE+PE) across the two nearest Nifty
expiries, for one date, and write one day-file to stock-market-data.

Always fetches exactly ONE day -- same TARGET_DATE convention as
fetch_nifty_ohlc.py (blank = today via Intraday, explicit date = backfill
via Historical).

--- Alert-scope decision, worth being explicit about ---
Tonight's live testing confirmed: illiquid-but-genuinely-traded strikes
NEVER return empty (down to just 6 traded minutes all day); only
strikes with ZERO activity all day return empty. That's what justified
"empty response = alert" as a simple, reliable signal, tested against a
handful of near-term strikes.

BUT: "full chain, 2 expiries" necessarily includes some strikes so far
from spot they may legitimately never trade at all within the tracked
expiries too -- not just the 3-months-out extreme examples used for
testing. Alerting on EVERY per-strike empty response would therefore
produce constant noise from strikes that are correctly, expectedly
empty -- not failures.

So the empty-response rule is applied at TWO levels, not one:
  - Per-instrument: an HTTP error (non-200, timeout, bad JSON) is always
    counted as a real failure -- this can't be explained by illiquidity.
  - Per-instrument: an empty-but-HTTP-200 response is treated as normal
    (no row written for that instrument-minute, no alert) -- consistent
    with tonight's evidence that genuine trading activity never produces
    empty, so an empty result here just means "didn't trade."
  - Job-level: if EVERY SINGLE instrument in the whole batch came back
    empty (zero non-empty results across hundreds of strikes), that's
    treated as a real failure regardless -- statistically implausible
    for a full chain to be universally dead, so this pattern almost
    certainly means the whole batch hit a systemic problem (auth, wrong
    date, etc.), mirroring the Nifty-index control-check logic from
    tonight's testing.

This is a judgment call made during implementation, not something
explicitly settled in conversation -- flag if a stricter per-strike rule
was actually intended.
"""
import os
import sys
import time as time_module

import pandas as pd

from lib import date_utils, upstox_candles, option_chain, options_file_io, gha_output
from lib.config import OPTIONS_FETCH_PACING_SECONDS
from lib.date_guard import RunDateGuard


def main():
    token = os.environ.get("UPSTOX_ACCESS_TOKEN", "").strip()
    if not token:
        print("ERROR: UPSTOX_ACCESS_TOKEN not set.")
        gha_output.set_output("available", "false")
        gha_output.set_output("detail", "UPSTOX_ACCESS_TOKEN missing")
        sys.exit(1)

    target_date = os.environ.get("TARGET_DATE", "").strip() or date_utils.today_ist_str()
    gha_output.set_output("date", target_date)

    if date_utils.is_weekend(target_date):
        print(f"{target_date} is a weekend -- skipping.")
        gha_output.set_output("available", "skipped")
        gha_output.set_output("detail", "weekend")
        return

    if date_utils.is_holiday(target_date, token):
        print(f"{target_date} is a listed holiday -- skipping.")
        gha_output.set_output("available", "skipped")
        gha_output.set_output("detail", "holiday")
        return

    guard = RunDateGuard(target_date)

    print(f"Looking up next two expiries on/after {target_date} ...")
    try:
        expiries = option_chain.get_next_two_expiries(token, target_date)
    except Exception as e:
        print(f"  FAILED to get expiry list: {e}")
        gha_output.set_output("available", "false")
        gha_output.set_output("detail", f"expiry lookup failed: {e}")
        sys.exit(1)

    if len(expiries) < 2:
        print(f"  WARNING: only found {len(expiries)} expiries on/after {target_date}: {expiries}")
    print(f"  Tracking expiries: {expiries}")

    # Gather instrument keys for every strike, both sides, across both expiries.
    all_instruments = []  # list of (expiry, strike, 'CE'/'PE', instrument_key)
    for expiry in expiries:
        try:
            keymap = option_chain.get_option_chain(expiry, token)
        except Exception as e:
            print(f"  FAILED to get option chain for {expiry}: {e}")
            gha_output.set_output("available", "false")
            gha_output.set_output("detail", f"chain lookup failed for {expiry}: {e}")
            sys.exit(1)
        print(f"  {expiry}: {len(keymap)} instrument keys")
        for (strike, opt_type), key in keymap.items():
            all_instruments.append((expiry, strike, opt_type, key))

    print(f"Total instruments to fetch: {len(all_instruments)}")

    # per_minute[(date, time, strike, expiry)] = {'call_open':..., 'put_open':..., ...}
    per_minute = {}
    http_error_count = 0
    empty_count = 0
    ok_count = 0

    for i, (expiry, strike, opt_type, key) in enumerate(all_instruments, start=1):
        result = upstox_candles.fetch_candles(key, target_date, token)

        if result.status == "http_error":
            http_error_count += 1
            print(f"  [{i}/{len(all_instruments)}] {strike} {opt_type} {expiry}: HTTP ERROR -- {result.detail}")
        elif result.status == "empty":
            empty_count += 1
        else:
            ok_count += 1
            side_prefix = "call" if opt_type == "CE" else "put"
            for candle in result.candles:
                ts = pd.Timestamp(candle[0]).tz_localize(None)
                date_str = ts.strftime("%Y-%m-%d")
                time_str = ts.strftime("%H:%M:%S")
                row_key = (date_str, time_str, strike, expiry)
                row = per_minute.setdefault(row_key, {
                    "date": date_str, "time": time_str, "strike": strike, "expiry": expiry,
                    "call_open": None, "call_high": None, "call_low": None, "call_close": None,
                    "put_open": None, "put_high": None, "put_low": None, "put_close": None,
                })
                row[f"{side_prefix}_open"] = candle[1]
                row[f"{side_prefix}_high"] = candle[2]
                row[f"{side_prefix}_low"] = candle[3]
                row[f"{side_prefix}_close"] = candle[4]

        time_module.sleep(OPTIONS_FETCH_PACING_SECONDS)

    print(f"Done: {ok_count} ok, {empty_count} empty (expected for illiquid strikes), "
          f"{http_error_count} HTTP errors.")

    # Date-guard check before writing anything.
    if not guard.check():
        print(guard.failure_message())
        gha_output.set_output("available", "false")
        gha_output.set_output("detail", "run crossed midnight IST mid-fetch")
        sys.exit(1)

    rows = list(per_minute.values())
    if rows:
        options_file_io.write_day_file(target_date, rows, token)

    # Job-level failure conditions (see module docstring for reasoning):
    #   - any HTTP-level error, OR
    #   - literally zero non-empty results across the whole batch
    if http_error_count > 0:
        gha_output.set_output("available", "partial")
        gha_output.set_output("detail", f"{http_error_count} instrument(s) had HTTP errors")
    elif ok_count == 0:
        gha_output.set_output("available", "false")
        gha_output.set_output("detail", "zero non-empty results across entire batch")
        sys.exit(1)
    else:
        gha_output.set_output("available", "true")
        gha_output.set_output("detail", "")


if __name__ == "__main__":
    main()
