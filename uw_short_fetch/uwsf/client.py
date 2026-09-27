"""Unusual Whales REST client: auth, concurrency cap, retries, day-level disk cache.

Standard library only (Python 3.9+). The API token is never written to logs,
raw envelopes or cache files.
"""
from __future__ import annotations

import json
import os
import random
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any, Dict, Optional

BASE_URL = "https://api.unusualwhales.com"
USAGE_HEADERS = (
    "x-uw-daily-req-count",
    "x-uw-token-req-limit",
    "x-uw-req-per-minute-remaining",
    "x-uw-req-per-minute-reset",
)


class UWError(Exception):
    """Non-200 response (after retries) or transport failure."""

    def __init__(self, status: Optional[int], url: str, code: str = "", reason: str = "", message: str = ""):
        self.status, self.url, self.code, self.reason, self.message = status, url, code, reason, message
        bits = [f"HTTP {status}" if status else "transport error"]
        if code:
            bits.append(code)
        if reason:
            bits.append(f"({reason})")
        if message:
            bits.append(f"- {message}")
        super().__init__(" ".join(bits))


def load_token(env_var: str = "UW_API_TOKEN", env_file: str = "~/.openclaw/.env") -> str:
    """Environment variable wins; otherwise read KEY=VALUE from the .env file."""
    tok = os.environ.get(env_var, "").strip()
    if tok:
        return tok
    path = os.path.expanduser(env_file)
    if os.path.exists(path):
        pat = re.compile(r"^\s*(?:export\s+)?" + re.escape(env_var) + r"\s*=\s*(.*?)\s*$")
        with open(path) as fh:
            for line in fh:
                m = pat.match(line)
                if m:
                    return m.group(1).strip().strip('"').strip("'")
    raise SystemExit(f"UW token not found: set ${env_var} or add {env_var}=... to {env_file}")


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class Response:
    __slots__ = ("url", "status", "body", "fetched_at", "from_cache", "usage")

    def __init__(self, url: str, status: int, body: Any, fetched_at: str, from_cache: bool, usage: Dict[str, str]):
        self.url, self.status, self.body = url, status, body
        self.fetched_at, self.from_cache, self.usage = fetched_at, from_cache, usage

    def envelope(self) -> Dict[str, Any]:
        return {"url": self.url, "status": self.status, "fetched_at": self.fetched_at,
                "from_cache": self.from_cache, "usage_headers": self.usage, "body": self.body}


class UWClient:
    def __init__(self, token: str, *, base_url: str = BASE_URL, concurrency: int = 4,
                 timeout: float = 60.0, retries: int = 4, min_interval: float = 0.05):
        self._token = token
        self.base_url = base_url.rstrip("/")
        self.timeout, self.retries, self.min_interval = timeout, retries, min_interval
        self._sem = threading.BoundedSemaphore(max(1, concurrency))
        self._lock = threading.Lock()
        self._last_start = 0.0
        self.network_requests = 0
        self.cache_hits = 0
        self.last_usage: Dict[str, str] = {}

    # -- public ---------------------------------------------------------------
    def url_for(self, path: str, params: Optional[Dict[str, Any]] = None) -> str:
        clean = {k: v for k, v in (params or {}).items() if v is not None}
        q = urllib.parse.urlencode(clean, doseq=True)
        return f"{self.base_url}{path}" + (f"?{q}" if q else "")

    def get(self, path: str, params: Optional[Dict[str, Any]] = None, *,
            cache_file: Optional[str] = None) -> Response:
        """GET a JSON endpoint. With cache_file, a stored body is reused and fresh
        non-empty bodies are stored (callers only pass cache_file for past dates)."""
        url = self.url_for(path, params)
        if cache_file and os.path.exists(cache_file):
            with open(cache_file) as fh:
                env = json.load(fh)
            with self._lock:
                self.cache_hits += 1
            return Response(env.get("url", url), env.get("status", 200), env.get("body"),
                            env.get("fetched_at", ""), True, env.get("usage_headers", {}))
        resp = self._fetch(url)
        if cache_file and _non_empty(resp.body):
            os.makedirs(os.path.dirname(cache_file), exist_ok=True)
            tmp = cache_file + ".tmp"
            with open(tmp, "w") as fh:
                json.dump(resp.envelope(), fh)
            os.replace(tmp, cache_file)
        return resp

    # -- internals ------------------------------------------------------------
    def _pace(self) -> None:
        with self._lock:
            wait = self._last_start + self.min_interval - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            self._last_start = time.monotonic()

    def _fetch(self, url: str) -> Response:
        req = urllib.request.Request(url, headers={
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/json",
            "User-Agent": "uw-short-fetch/1.0",
        })
        attempt = 0
        while True:
            attempt += 1
            status, body_bytes, headers, transport_err = None, b"", {}, None
            with self._sem:
                self._pace()
                with self._lock:
                    self.network_requests += 1
                try:
                    with urllib.request.urlopen(req, timeout=self.timeout) as r:
                        status, body_bytes, headers = r.status, r.read(), dict(r.headers)
                except urllib.error.HTTPError as e:
                    status, headers = e.code, dict(e.headers or {})
                    try:
                        body_bytes = e.read()
                    except Exception:
                        body_bytes = b""
                except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
                    transport_err = e
            usage = {k: v for k, v in headers.items() if k.lower() in USAGE_HEADERS}
            if usage:
                with self._lock:
                    self.last_usage = {k.lower(): v for k, v in usage.items()}

            if transport_err is not None:
                if attempt <= self.retries:
                    time.sleep(self._backoff(attempt))
                    continue
                raise UWError(None, url, message=f"{type(transport_err).__name__}: {transport_err}")

            if status == 200:
                try:
                    body = json.loads(body_bytes) if body_bytes else None
                except ValueError:
                    raise UWError(status, url, message="response is not JSON")
                return Response(url, status, body, _utcnow_iso(), False, usage)

            if status == 429 or (status is not None and status >= 500):
                if attempt <= self.retries:
                    time.sleep(self._retry_after(headers) or self._backoff(attempt))
                    continue
            code, reason, message = _parse_error(body_bytes)
            raise UWError(status, url, code, reason, message)

    @staticmethod
    def _backoff(attempt: int) -> float:
        return min(30.0, 2 ** (attempt - 1)) + random.uniform(0, 0.5)

    @staticmethod
    def _retry_after(headers: Dict[str, str]) -> Optional[float]:
        low = {k.lower(): v for k, v in headers.items()}
        for key, scale in (("retry-after", 1.0), ("x-uw-req-per-minute-reset", 0.001)):
            try:
                if key in low:
                    return min(60.0, float(low[key]) * scale) + 0.25
            except ValueError:
                pass
        return None


def _parse_error(body: bytes):
    try:
        js = json.loads(body)
    except Exception:
        return "", "", (body[:200].decode("utf8", "replace").strip() if body else "")
    if not isinstance(js, dict):
        return "", "", str(js)[:200]
    return (str(js.get("code") or ""), str(js.get("reason") or ""),
            str(js.get("message") or js.get("msg") or "")[:300])


def _non_empty(body: Any) -> bool:
    if body is None:
        return False
    if isinstance(body, list):
        return len(body) > 0
    if isinstance(body, dict):
        for key in ("data", "si", "chains"):
            if key in body:
                v = body[key]
                return bool(v) if isinstance(v, (list, dict)) else v is not None
        return bool(body)
    return True
