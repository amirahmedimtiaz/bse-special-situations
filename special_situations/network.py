from __future__ import annotations

import threading
import time
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse

import requests

_local = threading.local()
_lock = threading.Lock()
_next: dict[str, float] = {}


def session():
    if not hasattr(_local, "session"):
        _local.session = requests.Session()
    return _local.session


def request(method: str, url: str, **kwargs):
    host = urlparse(url).hostname or ""
    pace = 0.5 if host.endswith("bseindia.com") else 0.05
    timeout = kwargs.pop("timeout", (10, 90))
    for attempt in range(3):
        while True:
            with _lock:
                wait = _next.get(host, 0) - time.monotonic()
                if wait <= 0:
                    _next[host] = time.monotonic() + pace
                    break
            if wait > 60:
                raise RuntimeError(f"Upstream cooldown: {host}; retry next run")
            time.sleep(wait)
        try:
            response = session().request(method, url, timeout=timeout, **kwargs)
            if response.status_code not in (408, 429, 500, 502, 503, 504):
                response.raise_for_status()
                return response
            if attempt == 2:
                response.raise_for_status()
            delay = 2 ** (attempt + 1)
            token = response.headers.get("Retry-After")
            if token:
                try:
                    delay = max(delay, float(token))
                except ValueError:
                    delay = max(delay, parsedate_to_datetime(token).timestamp() - time.time())
            response.close()
            with _lock:
                _next[host] = max(_next.get(host, 0), time.monotonic() + delay)
        except (requests.Timeout, requests.ConnectionError):
            if attempt == 2:
                raise
            time.sleep(2 ** attempt)
    raise RuntimeError("Upstream request failed")
