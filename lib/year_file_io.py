"""
Read/write helper for the year-partitioned Nifty OHLC files
(nifty_1min_2026.csv, nifty_5min_2026.csv, etc.) in stock-market-data.

On-disk schema uses separate date/time columns (date, time, open, high,
low, close) -- matching the convention already used by the OI CSVs and
the options OHLC files, rather than a single combined timestamp column.
Internally (in memory, while sorting/deduplicating) this module still
works with a combined pandas 'timestamp' column since that's what
pandas' own resampling/sorting needs -- the split only happens at the
point of writing to / reading from disk.

Write pattern (used identically whether this is a normal daily run or a
manual backfill/correction re-run of an already-written date):
    1. Read the existing year-file, if any.
    2. Drop any existing rows for the date being written -- makes
       re-running a date always safe: it fully replaces that date's
       data rather than duplicating rows.
    3. Append the new rows.
    4. Sort the whole file chronologically.
    5. Write back.

This is deliberately the SAME code path for a normal same-day write and
a backfill write -- no separate branch needed.
"""
import io
import time
from datetime import datetime

import pandas as pd

from lib import github_io
from lib.config import NIFTY_OHLC_DIR

DISK_COLUMNS = ["date", "time", "open", "high", "low", "close"]


def year_file_path(interval_label: str, date_str: str) -> str:
    year = date_str[:4]
    return f"{NIFTY_OHLC_DIR}/nifty_{interval_label}_{year}.csv"


def _to_disk_format(df: pd.DataFrame) -> pd.DataFrame:
    """df must have a 'timestamp' column (datetime). Returns a copy with
    that split into separate 'date' and 'time' string columns, in
    DISK_COLUMNS order."""
    out = df.copy()
    out["date"] = out["timestamp"].dt.strftime("%Y-%m-%d")
    out["time"] = out["timestamp"].dt.strftime("%H:%M:%S")
    return out[DISK_COLUMNS]


def _from_disk_format(df: pd.DataFrame) -> pd.DataFrame:
    """df has separate 'date'/'time' string columns as read from CSV.
    Returns a copy with those combined back into one 'timestamp' column
    for internal sorting/dedup use."""
    out = df.copy()
    out["timestamp"] = pd.to_datetime(out["date"] + " " + out["time"])
    return out


def write_day_into_year_file(interval_label: str, date_str: str, day_df: pd.DataFrame, github_token: str,
                              max_retries: int = 4) -> None:
    """day_df must have a 'timestamp' column (datetime or parseable
    string) plus open/high/low/close -- same shape aggregate.py already
    produces. The date/time split happens here, not upstream.

    Retries on a 409 conflict (confirmed real in production, 7-Aug-2026 --
    two overlapping workflow runs writing to the same year-file). Each
    retry re-reads the file FRESH from GitHub and redoes the whole
    merge, rather than just retrying the write with a new sha -- a
    sha-only retry would silently overwrite whatever the concurrent
    write had just added, since our in-memory 'existing_df' would still
    be the stale pre-conflict version.
    """
    path = year_file_path(interval_label, date_str)
    target_date = datetime.strptime(date_str, "%Y-%m-%d").date()

    for attempt in range(1, max_retries + 1):
        existing_csv = github_io.get_file_raw(path, github_token)
        if existing_csv:
            existing_df = pd.read_csv(io.StringIO(existing_csv), dtype={"date": str, "time": str})
            existing_df = _from_disk_format(existing_df)
        else:
            existing_df = pd.DataFrame(columns=["timestamp", "open", "high", "low", "close"])

        day_df_copy = day_df.copy()
        day_df_copy["timestamp"] = pd.to_datetime(day_df_copy["timestamp"])

        # Drop any existing rows for this exact date -- full replace, not append.
        if not existing_df.empty:
            existing_df = existing_df[existing_df["timestamp"].dt.date != target_date]

        combined = pd.concat([existing_df, day_df_copy], ignore_index=True)
        # Guard: concatenating with an empty existing_df (no year-file yet --
        # true on this repo's very first run for a given interval) can leave
        # 'timestamp' as a generic object dtype rather than datetime64,
        # which breaks .dt access below. Force it back explicitly rather
        # than relying on pandas to infer it correctly from a mixed concat.
        combined["timestamp"] = pd.to_datetime(combined["timestamp"])
        combined = combined.sort_values("timestamp").reset_index(drop=True)

        disk_df = _to_disk_format(combined)
        csv_text = disk_df.to_csv(index=False)

        try:
            github_io.put_file(
                path, csv_text, github_token,
                message=f"Update {interval_label} for {date_str}",
            )
            break
        except github_io.GitHubConflictError as e:
            if attempt == max_retries:
                raise RuntimeError(
                    f"Failed to write {path} after {max_retries} attempts -- "
                    f"repeated concurrent-write conflicts."
                ) from e
            wait = attempt * 2
            print(f"[year_file_io] Conflict writing {path} (attempt {attempt}/{max_retries}) -- "
                  f"re-reading fresh content and retrying in {wait}s...")
            time.sleep(wait)
            continue

    print(f"[year_file_io] Wrote {len(day_df)} rows for {date_str} into {path} "
          f"(file now has {len(disk_df)} total rows)")
