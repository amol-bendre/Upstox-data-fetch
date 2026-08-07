"""
GitHub Contents API read/write helper for the shared data repo.

Read path uses the 'raw' media type instead of the default JSON+base64
envelope -- the default envelope silently omits the 'content' field for
any file over 1MB, which several of the files this repo writes (options
OHLC especially, and eventually the widened OI file) will cross well
before end of day. This was a real, confirmed gap in the existing OI
app's own read path -- fixed here from the start rather than repeated.

Write path still uses the standard base64 JSON PUT -- GitHub's write-size
ceiling via Contents API is much higher (tens of MB), so no equivalent
fix is needed there.
"""
import base64

import requests

from lib.config import DATA_REPO

API_ROOT = "https://api.github.com"


class GitHubConflictError(Exception):
    """Raised specifically on HTTP 409 -- the file's sha changed between
    our read and our write, meaning another process wrote to it
    concurrently. Distinct from other failures because it's worth
    retrying (by re-reading fresh content, not just a fresh sha) rather
    than treating it as a hard failure."""
    pass


def _headers(token: str, raw: bool = False) -> dict:
    accept = "application/vnd.github.v3.raw" if raw else "application/vnd.github.v3+json"
    return {"Accept": accept, "Authorization": f"token {token}"}


def get_file_raw(path: str, token: str, data_repo: str = DATA_REPO) -> str | None:
    """Returns file content as text, or None if the file doesn't exist.
    Safe for files of any size -- uses the raw media type specifically
    to avoid the 1MB inline-content limit."""
    url = f"{API_ROOT}/repos/{data_repo}/contents/{path}"
    r = requests.get(url, headers=_headers(token, raw=True), timeout=30)
    if r.status_code == 404:
        return None
    if r.status_code != 200:
        raise RuntimeError(
            f"HTTP {r.status_code} from GitHub GET {path} (raw). Response body: {r.text[:1000]}"
        )
    return r.text


def get_file_sha(path: str, token: str, data_repo: str = DATA_REPO) -> str | None:
    """Returns just the file's sha (needed for updates), or None if it
    doesn't exist yet. Uses the default JSON media type -- GitHub still
    reliably returns 'sha' in the JSON metadata even for files over 1MB,
    it just omits the 'content' field, which we don't need here."""
    url = f"{API_ROOT}/repos/{data_repo}/contents/{path}"
    r = requests.get(url, headers=_headers(token, raw=False), timeout=30)
    if r.status_code == 404:
        return None
    if r.status_code != 200:
        raise RuntimeError(
            f"HTTP {r.status_code} from GitHub GET {path} (sha lookup). Response body: {r.text[:1000]}"
        )
    return r.json().get("sha")


def put_file(path: str, content: str, token: str, message: str, data_repo: str = DATA_REPO) -> None:
    """Creates or updates a file. Automatically fetches the current sha
    first if the file already exists (required by the Contents API for
    updates)."""
    sha = get_file_sha(path, token, data_repo)
    url = f"{API_ROOT}/repos/{data_repo}/contents/{path}"
    payload = {
        "message": message,
        "content": base64.b64encode(content.encode("utf-8")).decode("utf-8"),
    }
    if sha:
        payload["sha"] = sha

    r = requests.put(url, headers=_headers(token, raw=False), json=payload, timeout=60)
    if r.status_code == 409:
        raise GitHubConflictError(
            f"409 conflict writing {path} -- file was modified concurrently. "
            f"Response body: {r.text[:500]}"
        )
    if r.status_code not in (200, 201):
        raise RuntimeError(
            f"HTTP {r.status_code} from GitHub PUT {path}. Response body: {r.text[:1000]}"
        )
