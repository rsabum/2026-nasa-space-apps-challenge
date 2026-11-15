"""Polite HTTP: one shared session with retries, backoff, timeouts and redaction.

Secrets (API keys, tokens) can appear in query strings. `redact()` strips them
from any URL before it reaches an exception message or a log line.
"""

from __future__ import annotations

import logging
import os
import re
import time
from pathlib import Path
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from field_shift.config import Config

log = logging.getLogger(__name__)

USER_AGENT = "field-shift-data/0.1 (NASA Space Apps 2026 project)"
CONNECT_TIMEOUT_S = 15.0
_SECRET_PARAMS = re.compile(r"(?i)\b(key|api_key|token|access_token|password)=[^&\s]*")


class HttpError(RuntimeError):
    """An HTTP failure with secrets removed from the message."""

    def __init__(self, message: str, status_code: int | None = None, body: str = "") -> None:
        super().__init__(message)
        self.status_code = status_code
        self.body = body


def redact(text: str) -> str:
    """Replace secret query-string values with `***`."""
    return _SECRET_PARAMS.sub(lambda m: f"{m.group(1)}=***", text)


def make_session() -> requests.Session:
    """A session that retries 429 and 5xx responses with exponential backoff."""
    retry = Retry(
        total=5,
        backoff_factor=1.5,  # 0, 3, 6, 12, 24 s
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET", "POST", "HEAD"}),
        respect_retry_after_header=True,
        raise_on_status=False,
    )
    session = requests.Session()
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    session.headers["User-Agent"] = USER_AGENT
    return session


_SESSION: requests.Session | None = None


def session() -> requests.Session:
    """The process-wide shared session."""
    global _SESSION
    if _SESSION is None:
        _SESSION = make_session()
    return _SESSION


def request(
    config: Config,
    method: str,
    url: str,
    *,
    ok_statuses: tuple[int, ...] = (200,),
    stream: bool = False,
    **kwargs: Any,
) -> requests.Response:
    """Send a request with the configured timeout; raise `HttpError` on bad status.

    Statuses in `ok_statuses` are returned to the caller (e.g. NASS uses 400 for
    "no data", which callers may want to handle themselves).
    """
    kwargs.setdefault("timeout", (CONNECT_TIMEOUT_S, config.timeout_s))
    try:
        response = session().request(method, url, stream=stream, **kwargs)
    except requests.ConnectionError as exc:
        raise HttpError(f"could not connect to {redact(url)}: {redact(str(exc))[:300]}") from None
    except requests.Timeout:
        raise HttpError(f"timed out after {config.timeout_s:.0f} s: {redact(url)}") from None
    if response.status_code not in ok_statuses:
        body = response.text[:500] if not stream else ""
        raise HttpError(
            f"HTTP {response.status_code} from {redact(response.url)}: {redact(body)[:300]}",
            status_code=response.status_code,
            body=redact(body),
        )
    return response


def get(config: Config, url: str, **kwargs: Any) -> requests.Response:
    return request(config, "GET", url, **kwargs)


def post(config: Config, url: str, **kwargs: Any) -> requests.Response:
    return request(config, "POST", url, **kwargs)


def download(
    config: Config, url: str, dest: os.PathLike[str] | str, headers: dict[str, str] | None = None
) -> None:
    """Stream a file to `dest` (written to a temp name, then renamed)."""
    dest = Path(dest)
    tmp = dest.with_suffix(dest.suffix + ".part")
    with request(config, "GET", url, stream=True, headers=headers or {}) as response:
        with open(tmp, "wb") as fh:
            for chunk in response.iter_content(chunk_size=1 << 20):
                fh.write(chunk)
    tmp.replace(dest)


def polite_sleep(config: Config) -> None:
    """Pause between repeated calls to the same service (0 s in mock mode)."""
    delay = config.sleep_between_requests_s
    if delay > 0:
        time.sleep(delay)

