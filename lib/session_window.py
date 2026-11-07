"""
Decides what kind of day a given date is, from two files in the shared data
repo -- the same two files, with the same precedence, as the live OI app
(cloud_app.py's window_for):

  1. trading_window.csv   header: date,pre_start,trading_start,trading_end,post_end
     - a row dated YYYY-MM-DD is a SPECIAL session (e.g. Muhurat). It wins over
       a weekend AND over a holiday.
     - a row dated DEFAULT gives the normal-day times.
  2. holidays.txt         one date per line; only the first whitespace-separated
     token is read, '#' lines and blank lines are ignored, so an optional
     trailing description ("2026-11-10 Diwali") is fine.

Resolution order for date d:
     dated row in trading_window.csv  -> kind "special"
     Saturday/Sunday                  -> kind "weekend"   (skip)
     date listed in holidays.txt      -> kind "holiday"   (skip)
     otherwise                        -> kind "normal"

Fallbacks (this module never raises): an unreadable or garbage
trading_window.csv means "no special sessions, built-in 09:00/09:15/15:40/16:00";
an unreadable holidays.txt means "no listed holidays" (weekends are still
skipped) -- so a transient GitHub problem can at worst make a script TRY a
fetch it would previously have tried anyway, never silently skip a trading day.

Same module, same rules as NSE-data-fetch's session_window.py and the live OI app.

Time fields are minutes since midnight, IST. `fetch_raw(path)` is any callable
returning the file's text or None if it does not exist.
"""
import csv
from datetime import date

BUILTIN = {"pre": 540, "start": 555, "end": 940, "post": 960}  # 09:00 09:15 15:40 16:00
WINDOW_COLS = ["date", "pre_start", "trading_start", "trading_end", "post_end"]
SKIP_DETAIL = "holiday/weekend"

_CACHE = {}


def clear_cache():
    _CACHE.clear()


def hm_to_min(s):
    parts = str(s).strip().split(":")
    if len(parts) not in (2, 3):
        raise ValueError(f"bad time {s!r}")
    h, m = int(parts[0]), int(parts[1])
    if len(parts) == 3:
        int(parts[2])  # tolerate Excel's HH:MM:SS, seconds ignored
    if not (0 <= h <= 23 and 0 <= m <= 59):
        raise ValueError(f"bad time {s!r}")
    return h * 60 + m


def fmt_hm(minutes):
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def parse_holidays(text):
    """Set of 'YYYY-MM-DD' strings. First token per line; bad lines skipped."""
    out = set()
    for raw in text.splitlines():
        line = raw.strip().lstrip("﻿")
        if not line or line.startswith("#"):
            continue
        token = line.split(None, 1)[0]
        try:
            out.add(date.fromisoformat(token).isoformat())
        except ValueError:
            print(f"[window] holidays.txt: ignoring unparseable line {raw!r}")
    return out


def parse_windows(text):
    """Returns (default_or_None, specials, problems).
    default / specials values are dicts with keys pre,start,end,post (minutes).
    Raises ValueError only when the file is unusable as a whole."""
    lines = [ln.strip().lstrip("﻿") for ln in text.splitlines()]
    rows = list(csv.reader([ln for ln in lines if ln and not ln.startswith("#")]))
    if not rows:
        raise ValueError("trading_window.csv is empty")
    header = [c.strip().lower() for c in rows[0]]
    missing = [c for c in WINDOW_COLS if c not in header]
    if missing:
        raise ValueError(f"trading_window.csv header missing {missing}")
    idx = {c: header.index(c) for c in WINDOW_COLS}
    default, specials, problems = None, {}, []
    for row in rows[1:]:
        try:
            cells = [c.strip() for c in row]
            key = cells[idx["date"]]
            pre, start, end, post = (hm_to_min(cells[idx[c]]) for c in
                                     ("pre_start", "trading_start", "trading_end", "post_end"))
            if not (pre < start < end < post):
                raise ValueError("times out of order (need pre < start < end < post)")
            win = {"pre": pre, "start": start, "end": end, "post": post}
            if key.upper() == "DEFAULT":
                default = win
            else:
                specials[date.fromisoformat(key).isoformat()] = win
        except Exception as e:
            problems.append(f"skipping bad row {row}: {e}")
    return default, specials, problems


def _safe_fetch(fetch_raw, path):
    try:
        return fetch_raw(path)
    except Exception as e:
        print(f"[window] could not read {path} ({e})")
        return None


def resolve_day(d: date, fetch_raw):
    """Returns {'date','kind','skip','detail','pre','start','end','post'}.
    kind in special|weekend|holiday|normal; skip is True for weekend/holiday.
    Times are always filled (special row, else DEFAULT row, else built-in)."""
    key = d.isoformat()
    if key in _CACHE:
        return _CACHE[key]

    default, specials = None, {}
    text = _safe_fetch(fetch_raw, "trading_window.csv")
    if text is None:
        print("[window] trading_window.csv not found/unreadable -- built-in 09:00/09:15/15:40/16:00, no special sessions")
    else:
        try:
            default, specials, problems = parse_windows(text)
            for p in problems:
                print(f"[window] {p}")
        except Exception as e:
            print(f"[window] trading_window.csv unusable ({e}) -- built-in times, no special sessions")
            default, specials = None, {}

    holidays = set()
    htext = _safe_fetch(fetch_raw, "holidays.txt")
    if htext is None:
        print("[window] holidays.txt not found/unreadable -- assuming no listed holidays (weekends still skipped)")
    else:
        holidays = parse_holidays(htext)

    if key in specials:
        kind, times = "special", specials[key]
    else:
        times = default or BUILTIN
        if d.weekday() >= 5:
            kind = "weekend"
        elif key in holidays:
            kind = "holiday"
        else:
            kind = "normal"

    info = {"date": key, "kind": kind, "skip": kind in ("weekend", "holiday"),
            "detail": SKIP_DETAIL if kind in ("weekend", "holiday") else "", **times}
    print(f"[window] {key}: {kind}"
          f"{' (pre ' + fmt_hm(times['pre']) + ', trading ' + fmt_hm(times['start']) + '-' + fmt_hm(times['end']) + ', post ' + fmt_hm(times['post']) + ')' if kind in ('special', 'normal') else ''}")
    _CACHE[key] = info
    return info
