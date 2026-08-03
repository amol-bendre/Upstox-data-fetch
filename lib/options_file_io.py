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


def write_day_file(date_str: str, rows: list, token: str) -> None:
    """rows: list of dicts, each matching DISK_COLUMNS (missing values as
    None/NaN are fine -- they'll write out as empty CSV cells)."""
    path = day_file_path(date_str)
    df = pd.DataFrame(rows, columns=DISK_COLUMNS)
    df = df.sort_values(["time", "strike", "expiry"]).reset_index(drop=True)

    csv_text = df.to_csv(index=False)
    github_io.put_file(
        path, csv_text, token,
        message=f"Options EOD OHLC for {date_str}",
    )
    print(f"[options_file_io] Wrote {len(df)} rows to {path}")
