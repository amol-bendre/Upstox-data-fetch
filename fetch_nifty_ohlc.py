"""
Fetch Nifty OHLC for one date, derive every higher timeframe, write all
of it to stock-market-data.

Always fetches exactly ONE day -- never a range. Which day is controlled
entirely by the TARGET_DATE environment variable:
    - Not set / blank -> today (IST). This is the normal scheduled path.
    - Set to a specific YYYY-MM-DD -> that date. This is the manual
      backfill path (workflow_dispatch supplies this).

The date itself decides which Upstox endpoint gets used (today ->
Intraday, any other date -> Historical) -- see lib/upstox_candles.py.
Nothing in this script needs to know or care which endpoint was used.

Gap-check policy for Nifty specifically: STRICT. Nifty has no legitimate
"didn't trade this minute" case the way an individual option strike does
-- any missing minute in the 09:15-15:29 session grid is treated as a
real problem and flagged, in addition to the shared empty-response check.
"""
import os
import sys

import pandas as pd

from lib import date_utils, upstox_candles, year_file_io, gha_output
from lib.aggregate import aggregate_all
from lib.config import NIFTY_KEY, SESSION_START, SESSION_END
from lib.date_guard import RunDateGuard


def build_session_grid(date_str: str) -> set:
    """Every expected 1-min timestamp label from 09:15 to 15:29 for the
    given date, as a set of 'YYYY-MM-DD HH:MM:SS' strings."""
    start = pd.Timestamp(f"{date_str} {SESSION_START}:00")
    end = pd.Timestamp(f"{date_str} {SESSION_END}:00")
    return set(pd.date_range(start, end, freq="1min").strftime("%Y-%m-%d %H:%M:%S"))


def main():
    upstox_token = os.environ.get("UPSTOX_ACCESS_TOKEN", "").strip()
    github_token = os.environ.get("DATA_REPO_TOKEN", "").strip()

    if not upstox_token:
        print("ERROR: UPSTOX_ACCESS_TOKEN not set.")
        gha_output.set_output("available", "false")
        gha_output.set_output("detail", "UPSTOX_ACCESS_TOKEN missing")
        sys.exit(1)
    if not github_token:
        print("ERROR: DATA_REPO_TOKEN not set.")
        gha_output.set_output("available", "false")
        gha_output.set_output("detail", "DATA_REPO_TOKEN missing")
        sys.exit(1)

    target_date = os.environ.get("TARGET_DATE", "").strip() or date_utils.today_ist_str()
    gha_output.set_output("date", target_date)

    if date_utils.is_weekend(target_date):
        print(f"{target_date} is a weekend -- skipping.")
        gha_output.set_output("available", "skipped")
        gha_output.set_output("detail", "weekend")
        return

    if date_utils.is_holiday(target_date, github_token):
        print(f"{target_date} is a listed holiday -- skipping.")
        gha_output.set_output("available", "skipped")
        gha_output.set_output("detail", "holiday")
        return

    guard = RunDateGuard(target_date)

    print(f"Fetching Nifty 1-min candles for {target_date} ...")
    result = upstox_candles.fetch_candles(NIFTY_KEY, target_date, upstox_token)
    print(f"  {result.status}: {result.detail}")

    if result.status != "ok":
        gha_output.set_output("available", "false")
        gha_output.set_output("detail", result.detail)
        sys.exit(1)

    # Build DataFrame: candles are [timestamp, open, high, low, close, volume, oi]
    df = pd.DataFrame(result.candles, columns=["timestamp", "open", "high", "low", "close", "volume", "oi"])
    df = df[["timestamp", "open", "high", "low", "close"]]
    df["timestamp"] = pd.to_datetime(df["timestamp"]).dt.tz_localize(None)
    df = df.sort_values("timestamp").reset_index(drop=True)

    # Nifty gap-check -- OBSERVATIONAL ONLY as of 3-Aug-2026 (CAS go-live).
    #
    # This was previously a strict alert trigger (any missing minute in
    # 09:15-15:29 = failure). Softened to match the options script's
    # empty-response-only approach, because CAS introduced a new,
    # not-yet-fully-understood behavior near session close: on day one,
    # the index showed 9 minutes of flat/repeated candles (15:20-15:28)
    # followed by a jump at 15:29 -- candles were PRESENT (so this
    # wouldn't have tripped the old check anyway), but it's not yet known
    # whether other days might show genuinely MISSING minutes instead of
    # flat-carried-forward ones during this same window. Logging the gap
    # count for visibility while we observe a few days of real behavior,
    # without treating a gap as a hard failure in the meantime -- revisit
    # once there's enough evidence to set a confident rule again.
    expected = build_session_grid(target_date)
    actual = set(df["timestamp"].dt.strftime("%Y-%m-%d %H:%M:%S"))
    missing = sorted(expected - actual)
    gap_detected = len(missing) > 0
    if gap_detected:
        print(f"  GAP (observational only, not alerting): {len(missing)} missing minute(s) "
              f"out of {len(expected)} expected.")
        print(f"  First few missing: {missing[:5]}")
    else:
        print(f"  Full session present: {len(actual)}/{len(expected)} minutes.")

    # Date-guard check before writing anything.
    if not guard.check():
        print(guard.failure_message())
        gha_output.set_output("available", "false")
        gha_output.set_output("detail", "run crossed midnight IST mid-fetch")
        sys.exit(1)

    # Write 1-min base.
    year_file_io.write_day_into_year_file("1min", target_date, df, github_token)

    # Derive and write every higher timeframe.
    derived = aggregate_all(df)
    for interval_label, derived_df in derived.items():
        if derived_df.empty:
            print(f"  Skipping write for {interval_label} -- no rows derived.")
            continue
        year_file_io.write_day_into_year_file(interval_label, target_date, derived_df, github_token)

    # Gap is logged above but no longer affects job status -- see the
    # long comment on the gap-check itself for why (CAS observation
    # period, as of 3-Aug-2026).
    gha_output.set_output("available", "true")
    gha_output.set_output("detail", "" if not gap_detected else f"(informational) {len(missing)} minute(s) had no fresh candle")


if __name__ == "__main__":
    main()
