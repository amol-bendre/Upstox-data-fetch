"""
Writer for the options EOD OHLC day-files (nifty-options-ohlc/options_ohlc_YYYY-MM-DD.csv).

Unlike the Nifty year-files, these are one-file-per-day -- so "re-run
safety" here just means fully overwriting that day's file, no
strip-existing-rows step needed (the whole file IS that date).

Schema: date, time, strike, expiry, call_open, call_high, call_low,
call_close, put_open, put_high, put_low, put_close

Row key is (date, time, strike, expiry) -- same strike/minute but a
different expiry gets a separate row. Missing side (CE traded, PE didn't,
or vice versa) gets null in that side's four columns rather than the row
being dropped -- dropping would lose the side that DID trade.
"""
import time

import pandas as pd

from lib import github_io
from lib.config import OPTIONS_OHLC_DIR

DISK_COLUMNS = [
    "date", "time", "strike", "expiry",
    "call_open", "call_high", "call_low", "call_close",
    "put_open", "put_high", "put_low", "put_close",
]


def day_file_path(date_str: str) -> str:
    return f"{OPTIONS_OHLC_DIR}/options_ohlc_{date_str}.csv"


def write_day_file(date_str: str, rows: list, github_token: str, max_retries: int = 4) -> None:
    """rows: list of dicts, each matching DISK_COLUMNS (missing values as
    None/NaN are fine -- they'll write out as empty CSV cells).

    Retries on a 409 conflict (two overlapping runs writing the same
    day's file -- confirmed possible in production, 7-Aug-2026, for the
    Nifty year-files; same mechanism could hit this file too). Unlike
    year_file_io's retry, no re-read-and-remerge is needed here: each
    run independently rebuilds a complete, self-consistent picture of
    the whole day from its own fetch loop, so on conflict the sensible
    outcome is simply retrying the write with a fresh sha -- there's no
    cross-run content to merge, since this file is always a full
    overwrite for one specific date, not an accumulating multi-date file."""
    path = day_file_path(date_str)
    df = pd.DataFrame(rows, columns=DISK_COLUMNS)
    df = df.sort_values(["time", "strike", "expiry"]).reset_index(drop=True)
    csv_text = df.to_csv(index=False)

    for attempt in range(1, max_retries + 1):
        try:
            github_io.put_file(
                path, csv_text, github_token,
                message=f"Options EOD OHLC for {date_str}",
            )
            break
        except github_io.GitHubConflictError as e:
            if attempt == max_retries:
                raise RuntimeError(
                    f"Failed to write {path} after {max_retries} attempts -- "
                    f"repeated concurrent-write conflicts."
                ) from e
            wait = attempt * 2
            print(f"[options_file_io] Conflict writing {path} (attempt {attempt}/{max_retries}) -- "
                  f"retrying in {wait}s...")
            time.sleep(wait)
            continue

    print(f"[options_file_io] Wrote {len(df)} rows to {path}")
