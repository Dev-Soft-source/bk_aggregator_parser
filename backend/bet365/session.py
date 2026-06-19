"""Fetch Bet365 pstk session id from sports-configuration API."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

import requests

from bet365.config import Bet365Config

logger = logging.getLogger(__name__)


class Bet365SessionError(RuntimeError):
    pass


def session_id_from_cookie(cookie: str) -> str | None:
    match = re.search(r"\bpstk=([^;]+)", cookie)
    return match.group(1) if match else None


def fetch_session_id(config: Bet365Config) -> str:
    """Resolve pstk session id from env, cookie, or sports-configuration API."""
    if config.session_id:
        return config.session_id

    if config.cookie:
        from_cookie = session_id_from_cookie(config.cookie)
        if from_cookie:
            return from_cookie

    if not config.cookie:
        raise Bet365SessionError(
            "Set BET365_SESSION_ID, or BET365_COOKIE with pstk=…, "
            "or open bet365.com and copy cookies from DevTools."
        )

    headers = {
        "User-Agent": config.user_agent,
        "Accept": "application/json, text/plain, */*",
        "Origin": config.origin,
        "Referer": f"{config.origin}/",
        "Cookie": config.cookie,
    }
    try:
        resp = requests.get(config.sports_config_url, headers=headers, timeout=30)
        resp.raise_for_status()
        data: dict[str, Any] = resp.json()
    except Exception as exc:
        raise Bet365SessionError(f"sports-configuration failed: {exc}") from exc

    flashvars = data.get("flashvars") or {}
    session_id = flashvars.get("SESSION_ID")
    if session_id:
        return str(session_id)

    raise Bet365SessionError("SESSION_ID not found in sports-configuration response")


def fetch_server_time(config: Bet365Config, session_id: str) -> int | None:
    """Optional SERVER_TIME from sports-configuration (for NST token generation)."""
    if not config.cookie:
        return None
    headers = {
        "User-Agent": config.user_agent,
        "Accept": "application/json",
        "Cookie": f"pstk={session_id}; {config.cookie}",
        "Referer": f"{config.origin}/",
    }
    try:
        resp = requests.get(config.sports_config_url, headers=headers, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        util = (data.get("ns_weblib_util") or {}).get("WebsiteConfig") or {}
        return int(util["SERVER_TIME"]) if util.get("SERVER_TIME") is not None else None
    except Exception as exc:
        logger.debug("SERVER_TIME fetch failed: %s", exc)
        return None
