"""Bet365 line (prematch) configuration — CDP Chrome on #/AO/."""

from __future__ import annotations

import os
from dataclasses import replace

from dotenv import load_dotenv

from bet365.config import Bet365Config, DEFAULT_LINE_COOKIE_IMPORT_CDP_URL, _env_bool

load_dotenv()

DEFAULT_SITE_NAME = "bet365.com"
# Line feed hub (prematch).
DEFAULT_BROWSER_URL = "https://www.bet365.com/#/AO/"
# Open sports home first (#/HO/), then navigate to #/AO/ after auth.
DEFAULT_BROWSER_ENTRY_URL = "https://www.bet365.com/#/HO/"
DEFAULT_BROWSER_CDP_URL = "http://127.0.0.1:9225"
DEFAULT_POLL_INTERVAL = 10.0
DEFAULT_SAFE_POLL_INTERVAL = 15.0
DEFAULT_INITIAL_LOAD_SECONDS = 90.0


def line_prune_absent_from_env() -> bool:
    return _env_bool("BET365_LINE_PRUNE_ABSENT", False)


def line_initial_load_seconds_from_env() -> float:
    raw = os.getenv("BET365_LINE_INITIAL_LOAD_SECONDS", "").strip()
    if raw:
        return float(raw)
    return DEFAULT_INITIAL_LOAD_SECONDS


def line_config_from_env() -> Bet365Config:
    """
    Build a Bet365Config aimed at the prematch line hub (#/AO/).

    Prefers BET365_LINE_* env vars; falls back to shared BET365_* where useful
    (cookies, Cloudflare, import flags live in the shared bet365 package).
    """
    base = Bet365Config.from_env()

    safe_mode = _env_bool("BET365_LINE_SAFE_MODE", base.safe_mode)
    poll_explicit = (
        os.getenv("BET365_LINE_POLL_INTERVAL_SECONDS")
        or os.getenv("BET365_POLL_INTERVAL_SECONDS")
        or ""
    ).strip()
    if poll_explicit:
        poll_interval = float(poll_explicit)
    elif safe_mode:
        poll_interval = DEFAULT_SAFE_POLL_INTERVAL
    else:
        poll_interval = DEFAULT_POLL_INTERVAL

    cdp = (
        os.getenv("BET365_LINE_BROWSER_CDP_URL", "").strip()
        or DEFAULT_BROWSER_CDP_URL
    )
    browser_url = (
        os.getenv("BET365_LINE_BROWSER_URL", "").strip() or DEFAULT_BROWSER_URL
    )
    entry = (
        os.getenv("BET365_LINE_BROWSER_ENTRY_URL", "").strip()
        or DEFAULT_BROWSER_ENTRY_URL
    )
    import_raw = os.getenv("BET365_LINE_COOKIE_IMPORT_CDP_URL", "").strip().lower()
    if import_raw in ("0", "false", "no", "off"):
        cookie_import_cdp = None
    elif import_raw:
        cookie_import_cdp = import_raw
    else:
        cookie_import_cdp = (
            os.getenv("BET365_BROWSER_CDP_URL", "").strip()
            or DEFAULT_LINE_COOKIE_IMPORT_CDP_URL
        )

    return replace(
        base,
        use_browser=True,
        browser_cdp_url=cdp,
        browser_cookie_import_cdp_url=cookie_import_cdp,
        browser_url=browser_url,
        browser_entry_url=entry,
        poll_interval=poll_interval,
        poll_live_only=False,
        safe_mode=safe_mode,
        browser_auto_reload=_env_bool(
            "BET365_LINE_BROWSER_AUTO_RELOAD",
            _env_bool("BET365_BROWSER_AUTO_RELOAD", not safe_mode),
        ),
        browser_initial_attach=_env_bool(
            "BET365_LINE_BROWSER_INITIAL_ATTACH",
            base.browser_initial_attach,
        ),
        recover_reload=_env_bool(
            "BET365_LINE_RECOVER_RELOAD",
            _env_bool("BET365_RECOVER_RELOAD", not safe_mode),
        ),
    )
