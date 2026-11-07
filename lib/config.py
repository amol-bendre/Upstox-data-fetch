"""
Shared constants. Nothing in here should need per-script duplication.
"""
import os

NIFTY_KEY = "NSE_INDEX|Nifty 50"
BASE_V2 = "https://api.upstox.com/v2"
BASE_V3 = "https://api.upstox.com/v3"

# The shared data repo everything reads from / writes to.
DATA_REPO = os.environ.get("DATA_REPO", "amol-bendre/stock-market-data")

# Paths inside DATA_REPO.
NIFTY_OHLC_DIR = "nifty-ohlc"
OPTIONS_OHLC_DIR = "nifty-options-ohlc"
HOLIDAYS_PATH = "holidays.txt"

# Pacing between individual option-instrument fetches in the EOD batch.
# ~600 calls at this pace finishes in ~8-10 min -- comfortably under
# Upstox's rate limits (far below 25 req/sec, 250 req/min) with real margin,
# and fits inside the 6 PM schedule without getting anywhere near midnight.
OPTIONS_FETCH_PACING_SECONDS = 0.8

# Full session grid for the Nifty gap-check (observational only as of
# CAS go-live, 3-Aug-2026 -- see fetch_nifty_ohlc.py). Session end
# reflects the actual extended close (15:40), not the pre-CAS 15:30 --
# this matters even though the index itself didn't populate 15:30-15:39
# on day one, precisely so the observational log can show us if/when
# that changes on a future day, rather than being blind to that window.
#
# NOTE: the grid is no longer driven by these two constants. Per-day times
# come from trading_window.csv via lib/session_window.py (start = trading_start,
# end = trading_end - 1 minute, the last 1-min candle label). These remain only
# as documentation of the built-in normal-day values, which session_window.BUILTIN
# reproduces whenever the file is missing or has no DEFAULT row.
SESSION_START = "09:15"
SESSION_END = "15:39"  # last 1-min candle label of the extended session
