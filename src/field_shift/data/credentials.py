"""Credential lookups. These only check presence or hand a value to a request;
they never print, log or store a secret.

- NASS QuickStats key: `NASS_API_KEY` in `.env` (or the environment).
- NASA Earthdata: `~/.netrc` entry for urs.earthdata.nasa.gov, or
  `EARTHDATA_USERNAME`/`EARTHDATA_PASSWORD`, or `EARTHDATA_TOKEN`.
  In mock mode only `MOCK_EARTHDATA_TOKEN` is used (any non-empty value works),
  so a fake token can never be sent to the real Earthdata servers.
"""

from __future__ import annotations

import logging
import netrc
import os
from pathlib import Path

from dotenv import load_dotenv

from field_shift.config import REPO_ROOT, Config

log = logging.getLogger(__name__)

EARTHDATA_HOST = "urs.earthdata.nasa.gov"
_dotenv_loaded = False


def _load_dotenv() -> None:
    global _dotenv_loaded
    if not _dotenv_loaded:
        load_dotenv(REPO_ROOT / ".env", override=False)
        _dotenv_loaded = True


def nass_api_key() -> str | None:
    _load_dotenv()
    key = os.environ.get("NASS_API_KEY", "").strip()
    return key or None


def _netrc_has_earthdata() -> bool:
    path = Path.home() / ".netrc"
    if not path.exists():
        return False
    try:
        return netrc.netrc(str(path)).authenticators(EARTHDATA_HOST) is not None
    except (netrc.NetrcParseError, OSError):
        return False


def _mock_token() -> str | None:
    return os.environ.get("MOCK_EARTHDATA_TOKEN", "").strip() or None


def earthdata_available(config: Config) -> bool:
    """True if some Earthdata credential is configured for the current mode."""
    _load_dotenv()
    if config.is_mock:
        return _mock_token() is not None
    if os.environ.get("EARTHDATA_TOKEN", "").strip():
        return True
    if os.environ.get("EARTHDATA_USERNAME") and os.environ.get("EARTHDATA_PASSWORD"):
        return True
    return _netrc_has_earthdata()


def earthdata_token(config: Config) -> str | None:
    """A bearer token for Earthdata downloads, or None if no login is set up.

    Real mode uses `EARTHDATA_TOKEN` if set, otherwise logs in through earthaccess
    (netrc, then environment variables) and asks it for a token.
    """
    _load_dotenv()
    if config.is_mock:
        return _mock_token()
    token = os.environ.get("EARTHDATA_TOKEN", "").strip()
    if token:
        return token
    if not earthdata_available(config):
        return None
    import earthaccess  # imported lazily: slow, and not needed in mock mode

    for strategy in ("netrc", "environment"):
        try:
            auth = earthaccess.login(strategy=strategy)
        except Exception:  # earthaccess raises a variety of errors on bad creds
            continue
        if auth is not None and getattr(auth, "authenticated", False):
            token_info = getattr(auth, "token", None) or {}
            access = token_info.get("access_token") if isinstance(token_info, dict) else None
            if access:
                return str(access)
    log.warning("Earthdata login is configured but earthaccess could not obtain a token")
    return None
