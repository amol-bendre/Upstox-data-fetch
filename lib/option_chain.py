"""
Instrument-key lookup for Nifty options, reusing the exact same endpoint
and response shape cloud_app_v2.py already relies on (confirmed working
in tonight's live testing -- "Chain returned 184 instrument keys").
"""
import requests

from lib.config import BASE_V2, NIFTY_KEY


def get_option_chain(expiry: str, token: str) -> dict:
    """Returns {(strike:int, 'CE'|'PE'): instrument_key} for one expiry."""
    r = requests.get(
        f"{BASE_V2}/option/chain",
        headers={"Accept": "application/json", "Authorization": f"Bearer {token}"},
        params={"instrument_key": NIFTY_KEY, "expiry_date": expiry},
        timeout=30,
    )
    r.raise_for_status()
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


def get_next_two_expiries(token: str, on_or_after: str) -> list:
    """
    Returns the two nearest Nifty weekly/monthly expiries on or after
    `on_or_after` (YYYY-MM-DD), sorted ascending.

    ASSUMPTION TO VERIFY: this uses Upstox's /v2/option/contract endpoint
    (instrument_key only, no expiry_date param) to list all currently
    listed contracts and derive the distinct expiry dates from them. This
    endpoint wasn't exercised in tonight's live testing -- worth a quick
    manual check the first time this script actually runs, since the
    option chain lookup (get_option_chain, above) WAS confirmed working
    tonight but this contract-listing call was not.
    """
    r = requests.get(
        f"{BASE_V2}/option/contract",
        headers={"Accept": "application/json", "Authorization": f"Bearer {token}"},
        params={"instrument_key": NIFTY_KEY},
        timeout=30,
    )
    r.raise_for_status()
    contracts = r.json().get("data", [])

    expiries = sorted({c["expiry"] for c in contracts if c.get("expiry")})
    upcoming = [e for e in expiries if e >= on_or_after]
    return upcoming[:2]
