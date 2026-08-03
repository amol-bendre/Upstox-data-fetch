# Upstox-data-fetch

Fetches Nifty 1-min OHLC (+derived 5/15/30/1h/daily) and options EOD OHLC
(full chain, 2 nearest expiries), writes both to `stock-market-data`.
Runs daily at 6 PM IST via GitHub Actions; supports manual backfill via
`workflow_dispatch`.

## Structure

```
lib/
  config.py           constants (NIFTY_KEY, repo paths, pacing, etc.)
  date_utils.py        IST time helpers, holiday check
  github_io.py         GitHub Contents API read/write (1MB-safe reads)
  upstox_candles.py    shared fetch_candles() -- Intraday vs Historical
  option_chain.py      instrument-key lookup, expiry list
  date_guard.py         midnight-crossing guard for same-day runs
  aggregate.py          1-min -> 5/15/30/1h/daily derivation
  year_file_io.py       Nifty OHLC read/write (year-files, date+time cols)
  options_file_io.py    options OHLC read/write (day-files, date+time cols)
  gha_output.py         GitHub Actions output helper
fetch_nifty_ohlc.py      main script: Nifty OHLC
fetch_options_ohlc.py    main script: options EOD OHLC
telegram_alert.py        ported as-is from NSE-data-fetch
requirements.txt
.github/workflows/daily-fetch.yml
```

## Required secrets (set in this repo's Settings -> Secrets)

- `UPSTOX_ACCESS_TOKEN` -- daily OAuth token, pasted in manually each
  morning (same pattern as the old `fetch_ohlc_upstox.py`). Separate
  copy from any other repo's secret of the same name -- GitHub secrets
  aren't shared across repos.
- `DATA_REPO_TOKEN` -- write access to `stock-market-data`.
- `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` -- same bot as other repos.

## Things worth verifying / testing before fully trusting this

These weren't directly confirmed in tonight's live testing and are
flagged in code comments too:

1. **`option_chain.get_next_two_expiries()`** uses Upstox's
   `/v2/option/contract` endpoint to list all contracts and derive
   expiry dates. This specific call wasn't exercised tonight --
   `get_option_chain()` (single-expiry lookup) WAS confirmed working.
   Worth a manual check the first time this runs for real.

2. **Options alert-scope decision** (see the long comment at the top of
   `fetch_options_ohlc.py`): empty-response-only alerting was confirmed
   correct for near-term strikes tonight, but "full chain" will include
   some strikes that are legitimately, permanently dead even within the
   two tracked expiries. Per-instrument empty responses are treated as
   normal (no alert); only HTTP-level errors or a total-batch-empty
   result trigger the alert. This is an implementation judgment call,
   not something explicitly settled in conversation -- flag if a
   stricter rule was actually intended.

3. **Schedule time (6 PM IST)** -- confirmed as final by you, but the
   underlying "is data reliably available by then" question was left
   as an open empirical test (tonight only confirmed data was available
   by 11:30 PM, not how early it becomes available). Worth keeping an
   eye on the first few real runs.

4. **Historical endpoint's actual backfill-readiness timing** is still
   unknown (confirmed empty even a few minutes past midnight tonight).
   Not a blocker for the daily path, but worth knowing before relying
   on the backfill script for a same-week gap.

## CAS (Closing Auction Session), live from 3-Aug-2026

Investigated same-day. Key finding: CAS is a cash-market auction applied
to F&O-eligible *stocks*, not to the derivative contracts themselves.

- **Nifty index** (`fetch_nifty_ohlc.py`): confirmed still stops at
  15:29 on day one, unchanged -- but showed 9 minutes of flat/repeated
  candles (15:20-15:28) followed by a jump at 15:29, consistent with
  constituents being mid-auction. `SESSION_END` is set to **15:39**
  (the full extended session), even though the index didn't populate
  15:30-15:39 on day one -- this is deliberate: since the gap-check is
  now observational-only (see below), using the full extended window
  as "expected" means the log will show us if/when the index starts
  populating that window on a future day, rather than being blind to it.
- **Options** (`fetch_options_ohlc.py`): confirmed candles now run to
  15:39 (10 new minutes), with completely normal continuous price/volume
  action throughout -- no auction applies to the contracts themselves.
  No code change was needed here; the script never hardcoded a session
  end time.
- **Nifty gap-check softened to observational-only** (as of this
  session): since it's not yet known whether the flat-candle behavior
  near close will hold on other days or sometimes show as genuinely
  missing minutes instead, the strict per-minute alert was relaxed to
  match the options script's empty-response-only approach. Gaps are
  still logged in the run output for visibility, just don't fail the
  job. Revisit after observing a few real trading days.

## Deliberately deferred / out of scope for this build

- Volume column on options OHLC (pending a separate test)
- `special_sessions.txt` handling (accepted gap -- will misfire on
  Muhurat trading day specifically)
- Old `nifty_5min_final_2026.csv`-style files -- untouched by this repo;
  manual cleanup/rename is on you, per earlier discussion. Note the new
  files use a `date,time,...` schema instead of the old single
  `timestamp` column, for consistency with the OI/options file
  conventions -- `nifty-fii-analytics`'s read side will need a small
  update once these new files start landing.
