"""Detect Cloudflare / bot challenge pages and wait for manual verification."""

from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

_CHALLENGE_URL_MARKERS: tuple[str, ...] = (
    "challenges.cloudflare.com",
    "/cdn-cgi/challenge-platform",
    "__cf_chl",
    "cf_chl_opt",
)

_CHALLENGE_TITLE_MARKERS: tuple[str, ...] = (
    "just a moment",
    "attention required",
    "performing security verification",
    "security verification",
    "please wait",
)

_CHALLENGE_BODY_MARKERS: tuple[str, ...] = (
    "verify you are human",
    "cf-turnstile",
    "challenge-platform",
    "security service to protect against malicious bots",
    "checking your browser",
    "enable javascript and cookies",
)


def is_cloudflare_challenge(
    *,
    url: str = "",
    title: str = "",
    body_text: str = "",
) -> bool:
    """True when the page looks like a Cloudflare / Turnstile challenge."""
    url_lower = (url or "").lower()
    if any(marker in url_lower for marker in _CHALLENGE_URL_MARKERS):
        return True

    title_lower = (title or "").lower()
    if any(marker in title_lower for marker in _CHALLENGE_TITLE_MARKERS):
        return True

    body_lower = (body_text or "").lower()
    return any(marker in body_lower for marker in _CHALLENGE_BODY_MARKERS)


def is_bet365_authenticated(
    *,
    url: str = "",
    title: str = "",
    body_text: str = "",
    has_pstk: bool = False,
    has_cf_clearance: bool = False,
) -> bool:
    """True when bet365 passed Cloudflare (entry page), before live hub."""
    if has_pstk or has_cf_clearance:
        return True
    if is_cloudflare_challenge(url=url, title=title, body_text=body_text):
        return False
    if "bet365.com" not in (url or "").lower():
        return False
    title_lower = (title or "").lower()
    if title_lower and "security verification" not in title_lower:
        return True
    body_lower = (body_text or "").lower()
    return bool(body_lower) and "verify you are human" not in body_lower


def is_bet365_live_ready(
    *,
    url: str = "",
    title: str = "",
    body_text: str = "",
    has_pstk: bool = False,
    has_zap_socket: bool = False,
) -> bool:
    """True when bet365 appears loaded past Cloudflare."""
    if is_cloudflare_challenge(url=url, title=title, body_text=body_text):
        return False

    url_lower = (url or "").lower()
    if "bet365.com" not in url_lower:
        return False

    if has_zap_socket or has_pstk:
        return True

    return any(token in url for token in ("#/HO/", "#/IP/", "#/I/", "#/AC/"))


def is_bet365_ready(
    *,
    url: str = "",
    title: str = "",
    body_text: str = "",
    has_pstk: bool = False,
    has_zap_socket: bool = False,
) -> bool:
    """Alias for live-hub readiness (ZAP feed)."""
    return is_bet365_live_ready(
        url=url,
        title=title,
        body_text=body_text,
        has_pstk=has_pstk,
        has_zap_socket=has_zap_socket,
    )


def is_live_hub_url(url: str) -> bool:
    return any(token in (url or "") for token in ("#/HO/", "#/IP/", "#/I/", "#/AC/"))


def challenge_user_message(
    entry_url: str,
    live_url: str,
    *,
    auto_click_delay: float | None = None,
) -> str:
    auto_line = ""
    if auto_click_delay is not None and auto_click_delay > 0:
        auto_line = (
            f"\n  Auto-click: checkbox will be clicked after {auto_click_delay:.0f}s "
            "(if still on this page)."
        )
    return (
        "Cloudflare verification required in CDP Chrome.\n"
        "  1. Switch to the bet365 Chrome window (port 9223 profile).\n"
        f"  2. Complete verification on {entry_url}\n"
        "  3. The adapter will open the live hub after auth succeeds.\n"
        f"  4. Live hub: {live_url}\n"
        "Do not start a second poll."
        f"{auto_line}"
    )


def attempt_turnstile_click(page: Any) -> bool:
    """Try to click the Cloudflare Turnstile checkbox (best-effort)."""
    if page is None:
        return False

    click_timeout = 2500

    def _try_click(locator: Any) -> bool:
        try:
            if locator.count() == 0:
                return False
            target = locator.first
            target.scroll_into_view_if_needed(timeout=click_timeout)
            target.click(timeout=click_timeout)
            return True
        except Exception:
            return False

    # Main document — label / checkbox text.
    text_patterns = (
        re.compile(r"verify you are human", re.I),
        re.compile(r"verify you are a human", re.I),
    )
    for pattern in text_patterns:
        try:
            loc = page.get_by_text(pattern)
            if loc.count() > 0:
                loc.first.click(force=True, timeout=click_timeout)
                logger.info("Cloudflare auto-click: force text %s", pattern.pattern)
                return True
        except Exception:
            pass

    # Click centre of Turnstile iframe (bet365 / Cloudflare widget).
    for iframe_sel in (
        'iframe[src*="challenges.cloudflare.com"]',
        'iframe[src*="turnstile"]',
        'iframe[title*="Widget"]',
        'iframe[title*="Cloudflare"]',
        "iframe",
    ):
        try:
            loc = page.locator(iframe_sel)
            count = min(loc.count(), 6)
        except Exception:
            count = 0
        for idx in range(count):
            try:
                box = loc.nth(idx).bounding_box(timeout=click_timeout)
            except Exception:
                box = None
            if box and box.get("width", 0) > 20 and box.get("height", 0) > 20:
                x = box["x"] + box["width"] / 2
                y = box["y"] + box["height"] / 2
                page.mouse.click(x, y)
                logger.info(
                    "Cloudflare auto-click: mouse click iframe %s[%s] at (%.0f, %.0f)",
                    iframe_sel,
                    idx,
                    x,
                    y,
                )
                return True

    role_names = (
        re.compile(r"verify you are human", re.I),
        re.compile(r"verify", re.I),
    )
    for name in role_names:
        if _try_click(page.get_by_role("checkbox", name=name)):
            logger.info("Cloudflare auto-click: checkbox role name=%s", name.pattern)
            return True

    for selector in (
        'input[type="checkbox"]',
        '[role="checkbox"]',
        "label.ctp-checkbox-label",
        ".ctp-checkbox-label",
        ".cf-turnstile",
        "#cf-turnstile",
        "#challenge-stage",
    ):
        if _try_click(page.locator(selector)):
            logger.info("Cloudflare auto-click: selector %s", selector)
            return True

    # Turnstile lives in iframes on many sites.
    iframe_selectors = (
        'iframe[src*="challenges.cloudflare.com"]',
        'iframe[src*="turnstile"]',
        'iframe[title*="Cloudflare"]',
        'iframe[title*="challenge"]',
        "iframe",
    )
    for iframe_sel in iframe_selectors:
        iframe_loc = page.locator(iframe_sel)
        try:
            count = iframe_loc.count()
        except Exception:
            count = 0
        for idx in range(min(count, 6)):
            frame = iframe_loc.nth(idx).content_frame()
            if frame is None:
                continue
            for sel in ('input[type="checkbox"]', '[role="checkbox"]', "label", "body"):
                if _try_click(frame.locator(sel)):
                    logger.info(
                        "Cloudflare auto-click: iframe %s[%s] selector %s",
                        iframe_sel,
                        idx,
                        sel,
                    )
                    return True
            try:
                iframe_loc.nth(idx).click(timeout=click_timeout)
                logger.info("Cloudflare auto-click: iframe element %s[%s]", iframe_sel, idx)
                return True
            except Exception:
                continue

    return False
