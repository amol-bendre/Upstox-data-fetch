"""
Confirmed tonight (30/31-Jul-2026 live test): the Intraday endpoint has
no date parameter -- it's implicitly "whatever calendar day it is right
now" by Upstox's clock. If a run starts before midnight IST targeting
"today" and is still running after midnight, Intraday silently starts
answering for the NEW day (which hasn't opened yet), not the day the run
actually meant to fetch. There is no retry that fixes this -- the run
just needs to recognize it happened and fail loudly rather than write
wrong/empty data under the original date's filename.

This only matters for same-day (Intraday) runs. Backfill runs (Historical,
explicit date) aren't affected -- Historical's date param doesn't change
meaning based on wall-clock time.
"""
from lib.date_utils import today_ist_str


class RunDateGuard:
    def __init__(self, target_date: str):
        self.target_date = target_date
        self.is_same_day_run = (target_date == today_ist_str())
        self._start_date = today_ist_str()

    def check(self) -> bool:
        """Call this right before writing anything. Returns True if safe
        to proceed, False if the wall-clock date has moved on since the
        run started (only possible/relevant for same-day runs)."""
        if not self.is_same_day_run:
            return True  # backfill runs aren't exposed to this
        return today_ist_str() == self._start_date

    def failure_message(self) -> str:
        return (
            f"Run started targeting {self.target_date} (today), but the wall clock "
            f"crossed into {today_ist_str()} before the run finished. Intraday endpoint "
            f"can no longer serve {self.target_date}'s data -- this date now needs to be "
            f"picked up via the Historical-endpoint backfill script once it becomes available."
        )
