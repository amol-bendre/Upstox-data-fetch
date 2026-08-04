"""
Instrument-key lookup for Nifty options, reusing the exact same endpoint
and response shape cloud_app_v2.py already relies on (confirmed working
in tonight's live testing -- "Chain returned 184 instrument keys").
"""
import io
from datetime import datetime, timedelta

import pandas as pd
import requests

from lib import github_io
from lib.config import BASE_V2, NIFTY_KEY


def get_option_chain(expiry: str, token: str) -> dict:
    """Returns {(strike:int, 'CE'|'PE'): instrument_key} for one expiry."""
    r = requests.get(
        f"{BASE_V2}/option/chain",
        headers={"Accept": "application/json", "Authorization": f"Bearer {token}"},
        params={"instrument_key": NIFTY_KEY, "expiry_date": expiry},
        timeout=30,
    )
    if r.status_code != 200:
        raise RuntimeError(
            f"HTTP {r.status_code} from GET /option/chain (expiry={expiry}). "
            f"Response body: {r.text[:1000]}"
        )
    chain = r.json().get("data", [])

    keymap = {}
    for entry in chain:
        strike = int(entry.get("strike_price", 0))
        ce = entry.get("call_options", {}).get("instrument_key", "")
        pe = entry.get("put_options", {}).get("instrument_key", "")
        if ce:
            keymap[(strike, "CE")] = ce
        if pe:
            keymap[(strike, "PE")] = pe
    return keymap


def get_next_two_expiries(on_or_after: str, github_token: str, max_lookback_days: int = 10) -> list:
    """
    Reads the most recent available NSE F&O bhavcopy (from stock-market-data,
    written daily by NSE-data-fetch) and derives the two nearest Nifty
    expiries on/after `on_or_after` (YYYY-MM-DD), sorted ascending.

    Replaces an earlier version that used Upstox's /v2/option/contract
    endpoint -- that endpoint returned 401 Unauthorized in production
    (4-Aug-2026), matching a report from another developer hitting the
    same wall for this exact use case. Bhavcopy is a more robust source
    here anyway: it's data we already reliably produce ourselves, not a
    dependency on an unverified third-party endpoint.

    Searches backward from `on_or_after` for the most recent bhavcopy
    that actually exists -- same-day bhavcopy isn't published until well
    after this script's 6 PM run, and there's no need to wait for it:
    which contracts exist rarely changes day to day, and bhavcopy
    typically carries expiries several months into the future, so a
    slightly-older bhavcopy still correctly identifies the nearest two
    expiries relative to `on_or_after`.
    """
    search_date = datetime.strptime(on_or_after, "%Y-%m-%d").date()

    for _ in range(max_lookback_days):
        path = f"options-bhavcopy/fno_bhavcopy_{search_date}.csv"
        content = github_io.get_file_raw(path, github_token)
        if content is not None:
            df = pd.read_csv(io.StringIO(content))
            nifty = df[df["TckrSymb"] == "NIFTY"]
            expiries = sorted(nifty["XpryDt"].unique())
            upcoming = [e for e in expiries if e >= on_or_after]
            if len(upcoming) >= 2:
                print(f"[option_chain] Found expiries via {path}")
                return upcoming[:2]
            print(f"[option_chain] WARNING: only {len(upcoming)} expiries >= {on_or_after} "
                  f"found in {path} -- trying an earlier bhavcopy anyway in case this one is thin.")
        search_date -= timedelta(days=1)

    raise RuntimeError(
        f"No usable bhavcopy found in the last {max_lookback_days} days searching "
        f"backward from {on_or_after} -- cannot determine tracked expiries."
    )
