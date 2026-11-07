"""
IST-aware date/time helpers, and the holiday check every fetch script
runs before doing anything else.
"""
import os
from datetime import datetime, timezone, timedelta

from datetime import date as _date

from lib import github_io, session_window
from lib.config import HOLIDAYS_PATH

IST = timezone(timedelta(hours=5, minutes=30))


def now_ist() -> datetime:
    return datetime.now(IST)


def today_ist_str() -> str:
    return now_ist().strftime("%Y-%m-%d")


def is_holiday(date_str: str, github_token: str) -> bool:
    """
    Reads holidays.txt from the shared data repo. Expected format: one
    YYYY-MM-DD per line (matches what the existing OI app / bhavcopy
    fetcher already read from this same file). Missing file / read error
    is treated as "not a holiday" -- we'd rather attempt a fetch that
    turns out empty than silently skip a real trading day because this
    file was unreachable.
    """
    content = github_io.get_file_raw(HOLIDAYS_PATH, github_token)
    if content is None:
        print(f"[date_utils] Could not read {HOLIDAYS_PATH} -- assuming NOT a holiday.")
        return False

    # Shared tolerant parser: first token per line, '#' comments ignored.
    return date_str in session_window.parse_holidays(content)


def is_weekend(date_str: str) -> bool:
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    return dt.weekday() >= 5  # 5=Sat, 6=Sun


def resolve_day(date_str: str, github_token: str) -> dict:
    """Day kind + session times for date_str, from trading_window.csv and
    holidays.txt in the data repo (see lib/session_window.py).

    Returns {'kind': special|weekend|holiday|normal, 'skip': bool,
    'detail': 'holiday/weekend' | '', 'pre','start','end','post': minutes}.
    A special session (dated row in trading_window.csv) is never skipped,
    even on a weekend or listed holiday. Never raises.
    """
    return session_window.resolve_day(
        _date.fromisoformat(date_str),
        lambda path: github_io.get_file_raw(path, github_token),
    )


def force_enabled() -> bool:
    """FORCE=true (manual dispatch only) bypasses the weekend/holiday skip."""
    return os.environ.get("FORCE", "").strip().lower() == "true"
