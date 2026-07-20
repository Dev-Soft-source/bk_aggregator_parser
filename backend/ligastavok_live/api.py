"""HTTP client for Liga Stavok line snapshots."""

from __future__ import annotations

import json
import logging
import re
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests
from requests.adapters import HTTPAdapter

from ligastavok_live.config import LigastavokApiConfig
from ligastavok_live.snapshot_body import (
    apply_live_all,
    apply_prematch_all,
    live_all_body,
    parse_body,
    prematch_all_body,
    serialize_body,
)

logger = logging.getLogger(__name__)

_TRANSIENT_HTTP_STATUS = frozenset({429, 502, 503, 504})
_http_session: requests.Session | None = None


class LigastavokApiError(RuntimeError):
    pass


def _get_http_session() -> requests.Session:
    global _http_session
    if _http_session is None:
        session = requests.Session()
        adapter = HTTPAdapter(pool_connections=8, pool_maxsize=8)
        session.mount("https://", adapter)
        session.mount("http://", adapter)
        _http_session = session
    return _http_session


def close_http_session() -> None:
    global _http_session
    if _http_session is not None:
        _http_session.close()
        _http_session = None


_SKIP_CURL_HEADERS = frozenset(
    {"content-length", "connection", "host", "accept-encoding"}
)


def _normalize_header_name(name: str) -> str:
    lower = name.strip().lower()
    if lower == "cookie":
        return "Cookie"
    if lower == "content-type":
        return "Content-Type"
    return name.strip()


def _parse_curl_headers(text: str) -> dict[str, str]:
    headers: dict[str, str] = {}
    for pattern in (
        r"-H\s+'([^:]+):\s((?:\\'|[^'])*)'",
        r'-H\s+"([^:]+):\s((?:\\"|[^"])*)"',
    ):
        for match in re.finditer(pattern, text, re.IGNORECASE):
            name = _normalize_header_name(match.group(1))
            if name.lower() in _SKIP_CURL_HEADERS:
                continue
            value = match.group(2).strip().replace('\\"', '"').replace("\\'", "'")
            headers[name] = value
    return headers


def _normalize_curl_text(text: str) -> str:
    """Convert Windows cmd 'Copy as cURL' (^ escapes) to bash-like text."""
    text = re.sub(r"\^\s*\r?\n", "", text)
    text = text.replace("^\\^\"", '\\"')
    text = re.sub(r"\^(.)", r"\1", text)
    return text


@dataclass(frozen=True)
class CurlRequest:
    url: str
    headers: dict[str, str]
    method: str = "GET"
    body: str | None = None


def _find_balanced_json_object(text: str, start: int) -> str | None:
    depth = 0
    in_string = False
    escape = False
    string_quote = ""
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escape:
                escape = False
                continue
            if char == "\\":
                escape = True
                continue
            if char == string_quote:
                in_string = False
            continue
        if char in ("'", '"'):
            in_string = True
            string_quote = char
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    return None


def _read_quoted_segment(text: str, quote: str) -> str | None:
    if not text or text[0] != quote:
        return None
    parts: list[str] = []
    index = 1
    while index < len(text):
        char = text[index]
        if char == "\\" and index + 1 < len(text):
            parts.append(text[index + 1])
            index += 2
            continue
        if char == quote:
            return "".join(parts)
        parts.append(char)
        index += 1
    return None


def _curl_flag_value(text: str, flag: str) -> str | None:
    match = re.search(rf"{re.escape(flag)}\s+", text, re.IGNORECASE)
    if not match:
        return None
    rest = text[match.end() :].lstrip()
    if not rest:
        return None

    quote = rest[0]
    if quote == "'":
        return _read_quoted_segment(rest, "'")
    if quote == '"':
        inner = _read_quoted_segment(rest, '"')
        if inner is not None:
            return inner
        brace = rest.find("{")
        if brace != -1:
            return _find_balanced_json_object(rest, brace)
        return None

    token = re.match(r"\S+", rest)
    return token.group(0) if token else None


def _curl_quoted_value(text: str, flag: str) -> str | None:
    return _curl_flag_value(text, flag)


def parse_curl_file(path: Path) -> CurlRequest:
    """Parse URL, method, headers, and body from Chrome 'Copy as cURL' export."""
    text = _normalize_curl_text(path.read_text(encoding="utf-8", errors="replace"))
    url_match = re.search(r"curl\s+'([^']+)'", text) or re.search(r'curl\s+"([^"]+)"', text)
    if not url_match:
        url_match = re.search(r"curl\s+(https://\S+)", text)
    if not url_match:
        raise LigastavokApiError(f"Could not find URL in curl file: {path}")

    url = url_match.group(1)
    headers = _parse_curl_headers(text)

    cookie_b = _curl_quoted_value(text, "-b") or _curl_quoted_value(text, "--cookie")
    if cookie_b:
        headers["Cookie"] = cookie_b

    method = "GET"
    if re.search(r"-X\s+['\"]POST['\"]", text, re.IGNORECASE) or re.search(
        r"--request\s+POST", text, re.IGNORECASE
    ):
        method = "POST"

    body = (
        _curl_quoted_value(text, "--data-raw")
        or _curl_quoted_value(text, "--data")
        or _curl_quoted_value(text, "-d")
    )
    if body and method == "GET":
        method = "POST"

    return CurlRequest(url=url, headers=headers, method=method, body=body)


def merge_request_headers(
    config: LigastavokApiConfig,
    curl_headers: dict[str, str] | None,
    *,
    fresh_request_id: bool = True,
) -> dict[str, str]:
    """Curl/browser headers win; config fills only missing keys."""
    merged = dict(config.request_headers())
    if curl_headers:
        merged.update(curl_headers)
    if fresh_request_id:
        merged["x-req-id"] = str(uuid.uuid4())
    return merged


def curl_has_session(headers: dict[str, str]) -> bool:
    cookie = headers.get("Cookie", "")
    return bool(cookie) and (
        "qrator" in cookie.lower()
        or "ligastavok" in cookie.lower()
        or "cfidsgib" in cookie.lower()
    )


_WS_SKIP_HEADERS = frozenset(
    {
        "content-length",
        "sec-fetch-dest",
        "sec-fetch-mode",
        "sec-fetch-site",
        "content-type",
        "connection",
        "host",
        "accept-encoding",
        "accept",
    }
)


def build_ws_handshake(
    config: LigastavokApiConfig,
    curl_headers: dict[str, str] | None,
    *,
    fresh_request_id: bool = True,
) -> tuple[list[str], str | None]:
    """Headers for WebSocket upgrade (strip HTTP-only keys, extract Cookie)."""
    merged = merge_request_headers(
        config,
        curl_headers,
        fresh_request_id=fresh_request_id,
    )
    cookie = merged.pop("Cookie", None)
    ws_headers = {
        key: value
        for key, value in merged.items()
        if key.lower() not in _WS_SKIP_HEADERS
    }
    header_lines = [f"{key}: {value}" for key, value in ws_headers.items()]
    return header_lines, cookie


def _auth_error_message(status_code: int, response_text: str) -> str | None:
    lower = response_text.lower()
    if status_code in (401, 403) and (
        "qrator" in lower or "cfidsgib" in lower or status_code == 403
    ):
        return (
            f"{status_code} Forbidden — Qrator session expired. "
            "Refresh backend/capture.curl from DevTools (must include -b cookies) "
            "or set LIGASTAVOK_COOKIE in .env"
        )
    return None


def resolve_post_body(
    config: LigastavokApiConfig,
    raw_body: str | None,
    *,
    live_all: bool | None = None,
    ns: str | None = None,
) -> dict[str, Any]:
    """Build eventsList POST JSON — default: all sports for the selected namespace."""
    use_live_all = config.live_all_sports if live_all is None else live_all
    namespace = (ns or getattr(config, "snapshot_ns", None) or "live").strip().lower()
    if namespace not in ("live", "prematch"):
        raise LigastavokApiError(f"Unsupported Liga Stavok ns={namespace!r} (use live|prematch)")

    if raw_body:
        body = parse_body(raw_body)
    elif config.snapshot_body:
        body = parse_body(config.snapshot_body)
    elif use_live_all:
        body = (
            prematch_all_body(limit=config.snapshot_limit)
            if namespace == "prematch"
            else live_all_body(limit=config.snapshot_limit)
        )
    else:
        raise LigastavokApiError(
            "No POST body — set LIGASTAVOK_SNAPSHOT_BODY, use --curl with --data-raw, "
            "or enable LIGASTAVOK_LIVE_ALL_SPORTS (default: true)"
        )

    if body is None:
        raise LigastavokApiError("Snapshot body resolved to empty")

    if use_live_all:
        body = (
            apply_prematch_all(body) if namespace == "prematch" else apply_live_all(body)
        )
    else:
        body["ns"] = namespace
    body["limit"] = config.snapshot_limit
    return body


def fetch_page(
    config: LigastavokApiConfig,
    *,
    url: str | None = None,
    ns: str = "live",
    game_id: int | None = None,
    limit: int = 40,
    skip: int = 0,
    headers: dict[str, str] | None = None,
    method: str = "GET",
    body: str | None = None,
    timeout: float = 30,
    max_retries: int = 3,
    session: requests.Session | None = None,
) -> dict[str, Any]:
    target = url or config.snapshot_query(
        ns=ns, game_id=game_id, limit=limit, skip=skip
    )
    last_error: Exception | None = None
    http = session or _get_http_session()

    for attempt in range(max_retries):
        merged_headers = merge_request_headers(
            config,
            headers,
            fresh_request_id=headers is not None,
        )

        try:
            if method.upper() == "POST":
                response = http.post(
                    target,
                    headers=merged_headers,
                    data=body.encode("utf-8") if body is not None else None,
                    timeout=timeout,
                )
            else:
                response = http.get(target, headers=merged_headers, timeout=timeout)
        except requests.RequestException as exc:
            last_error = exc
            if attempt + 1 < max_retries:
                time.sleep(1.5 * (attempt + 1))
                continue
            raise LigastavokApiError(f"HTTP request failed: {exc}") from exc

        auth_msg = _auth_error_message(response.status_code, response.text)
        if auth_msg:
            raise LigastavokApiError(auth_msg)

        if response.status_code in _TRANSIENT_HTTP_STATUS:
            last_error = requests.HTTPError(
                f"{response.status_code} Server Error for url: {target}",
                response=response,
            )
            if attempt + 1 < max_retries:
                logger.warning(
                    "Transient HTTP %s (attempt %s/%s), retrying…",
                    response.status_code,
                    attempt + 1,
                    max_retries,
                )
                time.sleep(1.5 * (attempt + 1))
                continue
            response.raise_for_status()

        try:
            response.raise_for_status()
        except requests.HTTPError as exc:
            last_error = exc
            raise LigastavokApiError(str(exc)) from exc

        try:
            payload = response.json()
        except json.JSONDecodeError as exc:
            raise LigastavokApiError(
                f"Non-JSON response ({response.status_code}): {response.text[:200]}"
            ) from exc

        if not isinstance(payload, dict):
            raise LigastavokApiError(f"Unexpected payload type: {type(payload)}")
        return payload

    if last_error:
        raise LigastavokApiError(str(last_error))
    raise LigastavokApiError("HTTP request failed")


def merge_snapshot_pages(pages: list[dict[str, Any]]) -> dict[str, Any]:
    if not pages:
        return {"id": None, "result": {"data": [], "total": 0}, "error": None, "httpCode": 200}

    merged = deepcopy(pages[0])
    result = merged.setdefault("result", {})
    all_data: list[dict[str, Any]] = []
    seen: set[int] = set()

    for page in pages:
        block = page.get("result") or {}
        for item in block.get("data") or []:
            item_id = item.get("id")
            if item_id is None or int(item_id) in seen:
                continue
            seen.add(int(item_id))
            all_data.append(item)

    result["data"] = all_data
    result["total"] = result.get("total", len(all_data))
    if pages[-1].get("result", {}).get("ts") is not None:
        result["ts"] = pages[-1]["result"]["ts"]
    merged["httpCode"] = 200
    merged["error"] = None
    return merged


def _fetch_post_page(
    cfg: LigastavokApiConfig,
    *,
    url: str,
    headers: dict[str, str] | None,
    body: str,
    timeout: float,
) -> dict[str, Any]:
    return fetch_page(
        cfg,
        url=url,
        headers=headers,
        method="POST",
        body=body,
        timeout=timeout,
        session=_get_http_session(),
    )


def fetch_snapshot(
    config: LigastavokApiConfig | None = None,
    *,
    ns: str = "live",
    game_id: int | None = None,
    limit: int = 40,
    max_pages: int = 1,
    url: str | None = None,
    headers: dict[str, str] | None = None,
    method: str = "GET",
    body: str | None = None,
    live_all: bool | None = None,
) -> dict[str, Any]:
    """Fetch one or more paginated snapshot pages."""
    cfg = config or LigastavokApiConfig.from_env()
    pages: list[dict[str, Any]] = []
    skip = 0
    page_limit = max_pages if max_pages > 0 else cfg.snapshot_max_pages
    if page_limit <= 0:
        page_limit = 10_000

    post_body: dict[str, Any] | None = None
    if method.upper() == "POST" and url:
        post_body = resolve_post_body(cfg, body, live_all=live_all, ns=ns)

    session = _get_http_session()
    t0 = time.perf_counter()

    for page_index in range(page_limit):
        page_body = None
        if post_body is not None:
            page_body = serialize_body(post_body, skip=skip)

        try:
            page = fetch_page(
                cfg,
                url=url if url else None,
                ns=ns,
                game_id=game_id,
                limit=limit,
                skip=skip,
                headers=headers,
                method=method if url else "GET",
                body=page_body if post_body is not None else body if page_index == 0 else None,
                timeout=cfg.http_timeout,
                session=session,
            )
        except LigastavokApiError as exc:
            if pages and post_body is not None and page_index > 0:
                logger.warning(
                    "Pagination stopped at skip=%s after %s page(s): %s — using partial snapshot",
                    skip,
                    len(pages),
                    exc,
                )
                break
            raise

        pages.append(page)

        data = (page.get("result") or {}).get("data") or []
        total = (page.get("result") or {}).get("total")
        skip += len(data)

        if (
            cfg.snapshot_parallel_pages
            and post_body is not None
            and page_index == 0
            and data
            and total is not None
            and skip < int(total)
        ):
            remaining_skips = list(range(skip, int(total), cfg.snapshot_limit))
            max_extra = page_limit - 1
            if cfg.snapshot_max_pages > 0:
                max_extra = min(max_extra, cfg.snapshot_max_pages - 1)
            if max_pages > 0:
                max_extra = min(max_extra, max_pages - 1)
            remaining_skips = remaining_skips[:max_extra]

            if remaining_skips:
                workers = min(cfg.snapshot_parallel_workers, len(remaining_skips))
                logger.debug(
                    "Parallel fetch %s page(s), workers=%s", len(remaining_skips), workers
                )
                with ThreadPoolExecutor(max_workers=workers) as pool:
                    futures = {
                        pool.submit(
                            _fetch_post_page,
                            cfg,
                            url=url,
                            headers=headers,
                            body=serialize_body(post_body, skip=sk),
                            timeout=cfg.http_timeout,
                        ): sk
                        for sk in remaining_skips
                    }
                    by_skip: dict[int, dict[str, Any]] = {}
                    for fut in as_completed(futures):
                        sk = futures[fut]
                        by_skip[sk] = fut.result()
                    for sk in sorted(by_skip):
                        pages.append(by_skip[sk])
                        skip += len((by_skip[sk].get("result") or {}).get("data") or [])
            break

        if post_body is None:
            if not data:
                break
            if total is not None and skip >= int(total):
                break
            url = None
            continue

        if not data:
            break
        if total is not None and skip >= int(total):
            break
        if max_pages > 0 and page_index + 1 >= max_pages:
            break
        if cfg.snapshot_max_pages > 0 and page_index + 1 >= cfg.snapshot_max_pages:
            break

    if cfg.profile:
        elapsed_ms = (time.perf_counter() - t0) * 1000
        logger.info(
            "fetch_snapshot: %s page(s) in %.0fms", len(pages), elapsed_ms
        )

    return merge_snapshot_pages(pages)


def save_snapshot(
    payload: dict[str, Any],
    path: Path,
    *,
    pretty: bool = False,
) -> None:
    if pretty:
        text = json.dumps(payload, indent=4, ensure_ascii=False) + "\n"
    else:
        text = json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n"
    path.write_text(text, encoding="utf-8")
