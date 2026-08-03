"""
IST-aware date/time helpers, and the holiday check every fetch script
runs before doing anything else.
"""
from datetime import datetime, timezone, timedelta

from lib import github_io
from lib.config import HOLIDAYS_PATH

IST = timezone(timedelta(hours=5, minutes=30))


def now_ist() -> datetime:
    return datetime.now(IST)


def today_ist_str() -> str:
    return now_ist().strftime("%Y-%m-%d")


def is_holiday(date_str: str, token: str) -> bool:
    """
    Reads holidays.txt from the shared data repo. Expected format: one
    YYYY-MM-DD per line (matches what the existing OI app / bhavcopy
    fetcher already read from this same file). Missing file / read error
    is treated as "not a holiday" -- we'd rather attempt a fetch that
    turns out empty than silently skip a real trading day because this
    file was unreachable.
    """
    content = github_io.get_file_raw(HOLIDAYS_PATH, token)
    if content is None:
        print(f"[date_utils] Could not read {HOLIDAYS_PATH} -- assuming NOT a holiday.")
        return False

    holidays = {line.strip() for line in content.splitlines() if line.strip()}
    return date_str in holidays


def is_weekend(date_str: str) -> bool:
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    return dt.weekday() >= 5  # 5=Sat, 6=Sun
