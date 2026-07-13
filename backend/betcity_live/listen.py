#!/usr/bin/env python3
"""Listen to Betcity live WebSocket and dump raw frames (protocol explorer)."""

from __future__ import annotations

import argparse
import logging
import sys
from dataclasses import replace
from pathlib import Path

from betcity_live.browser_session import BetcityBrowserError, listen_from_browser
from betcity_live.config import BetcityConfig, normalize_proxy
from betcity_live.ws_client import BetcityWsError, RawFrame, listen_sync


def _safe_print(text: str) -> None:
    """Print without crashing on Windows consoles that cannot encode Cyrillic."""
    try:
        print(text)
    except UnicodeEncodeError:
        encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
        print(text.encode(encoding, errors="replace").decode(encoding, errors="replace"))


def _on_frame(frame: RawFrame) -> None:
    _safe_print(f"[{frame.index}] {frame.kind}: {frame.preview}")


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    parser = argparse.ArgumentParser(
        description="Listen to Betcity live WebSocket and print/save raw frames.",
    )
    parser.add_argument(
        "--url",
        help="Override BETCITY_WS_URL (default wss://sc.betcity.ru/?id=live&csn=...)",
    )
    parser.add_argument(
        "--cookie",
        help="Cookie header from betcity.ru (or set BETCITY_COOKIE)",
    )
    parser.add_argument(
        "--seconds",
        type=float,
        default=None,
        help="How long to listen (default BETCITY_LISTEN_SECONDS or 30)",
    )
    parser.add_argument(
        "--max-frames",
        type=int,
        default=None,
        help="Stop after N frames",
    )
    parser.add_argument(
        "--save",
        nargs="?",
        const="samples",
        default=None,
        metavar="DIR",
        help="Save frames under DIR (default: betcity_live/samples when flag set)",
    )
    parser.add_argument(
        "--browser",
        action="store_true",
        help="Tap frames from CDP Chrome (recommended when using a proxy)",
    )
    parser.add_argument(
        "--direct",
        action="store_true",
        help="Force direct Python WebSocket",
    )
    parser.add_argument(
        "--proxy",
        default=None,
        help="Proxy host:port for catalog / Chrome launcher env hint",
    )
    args = parser.parse_args()

    cfg = BetcityConfig.from_env()
    overrides: dict = {}
    if args.url:
        overrides["ws_url"] = args.url
    if args.cookie:
        overrides["cookie"] = args.cookie
    if args.seconds is not None:
        overrides["listen_seconds"] = args.seconds
    if args.max_frames is not None:
        overrides["max_frames"] = args.max_frames
    if args.browser:
        overrides["use_browser"] = True
    if args.direct:
        overrides["use_browser"] = False
    if args.proxy is not None:
        overrides["proxy"] = normalize_proxy(args.proxy)
    if overrides:
        cfg = replace(cfg, **overrides)

    save_dir: Path | None = None
    if args.save is not None:
        save_path = Path(args.save)
        if not save_path.is_absolute():
            save_dir = Path(__file__).resolve().parent / save_path
        else:
            save_dir = save_path

    use_browser = cfg.use_browser and not args.direct
    if use_browser:
        print(f"Mode: browser tap (CDP {cfg.browser_cdp_url})")
        print(f"Page: {cfg.browser_url}")
    else:
        print("Mode: direct WebSocket (protocol explorer)")
        print(f"URL: {cfg.ws_url}")
        print(f"id={cfg.channel_id()!r} csn={cfg.csn()!r}")
        print(f"Origin: {cfg.origin}")
    if cfg.proxy:
        print(f"Proxy: {cfg.proxy}")
    print(f"Listen: {cfg.listen_seconds}s")
    if save_dir is not None:
        print(f"Save: {save_dir}")
    if not use_browser and not cfg.cookie:
        print(
            "\nWarning: no BETCITY_COOKIE - connection may fail with 403.\n"
            "Open https://betcity.ru/ , DevTools, Application, Cookies, "
            "or Network, WS, copy Cookie header.\n"
            "Then: set BETCITY_COOKIE in .env or pass --cookie\n"
            "Or use: python main.py listen betcity --browser\n"
        )

    try:
        if use_browser:
            count = listen_from_browser(
                cfg,
                duration=cfg.listen_seconds,
                max_frames=cfg.max_frames,
                save_dir=save_dir,
                on_frame=_on_frame,
            )
        else:
            count = listen_sync(
                cfg,
                duration=cfg.listen_seconds,
                max_frames=cfg.max_frames,
                save_dir=save_dir,
                on_frame=_on_frame,
            )
        print(f"\nDone. Received {count} frame(s).")
        if count == 0:
            print(
                "No frames received. For browser mode: keep CDP Chrome on the live page "
                "and press F5 once. For direct mode: check cookie/URL.",
                file=sys.stderr,
            )
            raise SystemExit(2)
    except (BetcityWsError, BetcityBrowserError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
