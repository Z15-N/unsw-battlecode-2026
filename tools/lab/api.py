"""Clients for the contest API (authenticated) and the site's public game list."""

from __future__ import annotations

import json
import pathlib
import threading
import time
import urllib.error
import urllib.request

API = "https://game.battlecode.au/api/v1"
SITE = "https://game.battlecode.au"
USER_AGENT = "weneedmoretokens-lab/1.0"


def api_key() -> str:
    keys = json.loads((pathlib.Path.home() / ".unswbc" / "keys.json").read_text())
    for value in keys.values():
        if isinstance(value, str) and value.startswith("bc_"):
            return value
    raise RuntimeError("no API key: run `unswbc auth set bc_...`")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


class RateLimiter:
    def __init__(self, per_minute: float) -> None:
        self.gap = 60.0 / per_minute
        self.next = 0.0
        self.lock = threading.Lock()

    def wait(self) -> None:
        with self.lock:
            now = time.monotonic()
            if self.next > now:
                time.sleep(self.next - now)
            self.next = max(now, self.next) + self.gap


class Client:
    """120 requests a minute is the API's cap; stay under it with headroom."""

    def __init__(self, per_minute: float = 100, site_per_minute: float = 60) -> None:
        self.key = api_key()
        self.api_limit = RateLimiter(per_minute)
        self.site_limit = RateLimiter(site_per_minute)
        self.storage_limit = RateLimiter(1200)     # signed replay links live on object storage
        self.no_redirect = urllib.request.build_opener(_NoRedirect)

    def _open(self, request, opener=None, limiter=None, tries: int = 6):
        for attempt in range(tries):
            (limiter or self.api_limit).wait()
            try:
                return (opener or urllib.request.build_opener()).open(request, timeout=60)
            except urllib.error.HTTPError as error:
                if error.code in (301, 302, 303, 307, 308):
                    return error
                if error.code == 429 or error.code >= 500:
                    delay = float(error.headers.get("Retry-After") or 2 ** attempt)
                    time.sleep(min(delay, 60))
                    continue
                raise
            except (urllib.error.URLError, TimeoutError, ConnectionError):
                time.sleep(2 ** attempt)
        raise RuntimeError(f"giving up on {request.full_url}")

    def get(self, path: str):
        req = urllib.request.Request(API + path, headers={"Authorization": "Bearer " + self.key,
                                                          "User-Agent": USER_AGENT})
        return json.loads(self._open(req).read())

    def post(self, path: str, body: dict):
        req = urllib.request.Request(API + path, data=json.dumps(body).encode(), method="POST",
                                     headers={"Authorization": "Bearer " + self.key,
                                              "Content-Type": "application/json",
                                              "User-Agent": USER_AGENT})
        return json.loads(self._open(req).read())

    def replay(self, game_id: int) -> bytes:
        """The API answers with a signed redirect; the key must not follow it."""
        req = urllib.request.Request(f"{API}/battles/{game_id}/replay",
                                     headers={"Authorization": "Bearer " + self.key,
                                              "User-Agent": USER_AGENT})
        first = self._open(req, opener=self.no_redirect)
        location = first.headers.get("Location") if hasattr(first, "headers") else None
        if not location:
            return first.read()
        return self._open(urllib.request.Request(location, headers={"User-Agent": USER_AGENT}),
                          limiter=self.storage_limit).read()

    # ---- public site data (SvelteKit __data.json, devalue-encoded) --------
    def site_data(self, path: str) -> dict:
        req = urllib.request.Request(f"{SITE}{path}", headers={"User-Agent": USER_AGENT})
        payload = json.loads(self._open(req, limiter=self.site_limit).read())
        return devalue(payload["nodes"][1]["data"])

    def team_games(self, team_id: int, page: int = 1) -> dict:
        return self.site_data(f"/games/__data.json?teams={team_id}&page={page}")


def devalue(arr: list):
    """Decode SvelteKit's flattened devalue format (enough for this site's data)."""
    cache: dict = {}

    def hydrate(i):
        if i == -1:
            return None
        if i in cache:
            return cache[i]
        v = arr[i]
        if isinstance(v, dict):
            out: dict = {}
            cache[i] = out
            for k, j in v.items():
                out[k] = hydrate(j)
            return out
        if isinstance(v, list):
            if v and isinstance(v[0], str) and v[0] in ("Date", "Set", "Map", "BigInt", "RegExp"):
                return v[1] if v[0] in ("Date", "BigInt") else v
            out_list: list = []
            cache[i] = out_list
            out_list.extend(hydrate(j) for j in v)
            return out_list
        return v

    return hydrate(0)
