#!/usr/bin/env python3
"""BK-Aggregator backend entry point."""

from __future__ import annotations

import argparse
import sys


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="BK-Aggregator backend (Fonbet import, poll, adapter).",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser(
        "import",
        help="Import a Fonbet JSON file into PostgreSQL",
        description="Import Fonbet JSON packet into PostgreSQL.",
    )
    sub.add_parser(
        "poll",
        help=(
            "Poll bookmaker API — fonbet, ligastavok-live, ligastavok-line, bet365, "
            "bet365-line, betcity-live, betcity-line, lxbet-line, or lxbet-live"
        ),
        description=(
            "Poll bookmaker API and import to PostgreSQL. "
            "Usage: python main.py poll "
            "[fonbet|ligastavok-live|ligastavok-line|bet365|bet365-line|"
            "betcity-live|betcity-line|lxbet-line|lxbet-live] ..."
        ),
    )
    sub.add_parser(
        "adapter",
        help="Map bookmaker packet to normalized changes (no DB)",
        description="Bookmaker adapter — fonbet (default) or ligastavok.",
    )
    sub.add_parser(
        "setup",
        help="Phase 0: init schema, import test.json, verify booker_adapter",
    )
    sub.add_parser(
        "fetch",
        help="Download bookmaker snapshot JSON (ligastavok)",
        description="Fetch HTTP snapshot — ligastavok only for now.",
    )
    sub.add_parser(
        "listen",
        help="Listen to bookmaker WebSocket (bet365 ZAP, betcity live)",
        description="Stream WebSocket frames — bet365 ZAP or betcity live socket.",
    )
    sub.add_parser(
        "capture",
        help="Capture session from browser (bet365 uid + cookie)",
        description="CDP Chrome capture — bet365 ZAP uid and pstk.",
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    argv = list(argv if argv is not None else sys.argv[1:])

    if not argv or argv[0] in ("-h", "--help"):
        _build_parser().print_help()
        return

    # Legacy: `python main.py --poll` (importer poll mode)
    if argv[0].startswith("-") and "--poll" in argv:
        _run_import(argv)
        return

    command = argv[0]
    rest = argv[1:]

    if command == "import":
        _run_import(rest)
    elif command == "poll":
        _run_poll(rest)
    elif command == "adapter":
        _run_adapter(rest)
    elif command == "setup":
        _run_setup()
    elif command == "fetch":
        _run_fetch(rest)
    elif command == "listen":
        _run_listen(rest)
    elif command == "capture":
        _run_capture(rest)
    elif command not in ("import", "poll", "adapter", "setup", "fetch", "listen", "capture") and not command.startswith("-"):
        # Legacy: `python main.py file.json` → import
        _run_import(argv)
        return
    else:
        _build_parser().print_help()
        raise SystemExit(f"Unknown command: {command}")


def _run_import(argv: list[str]) -> None:
    sys.argv = ["import", *argv]
    from fonbet.importer import main as import_main

    import_main()


def _run_poll(argv: list[str]) -> None:
    bookmaker = (argv[0].lower() if argv else "fonbet")
    # Accept common typo "fontbet".
    if bookmaker in ("fonbet", "fontbet"):
        rest = argv[1:] if argv and argv[0].lower() in ("fonbet", "fontbet") else argv
        sys.argv = ["poll", *rest]
        from fonbet.poll import main as poll_main
    elif bookmaker in ("ligastavok", "ligastavok-live", "ligastavok_live", "ligastavoklive"):
        sys.argv = ["poll", *argv[1:]]
        from ligastavok_live.poll import main as poll_main
    elif bookmaker in ("ligastavok-line", "ligastavok_line", "ligastavokline"):
        sys.argv = ["poll", *argv[1:]]
        from ligastavok_line.poll import main as poll_main
    elif bookmaker == "bet365":
        sys.argv = ["poll", *argv[1:]]
        from bet365.poll import main as poll_main
    elif bookmaker in ("bet365-line", "bet365_line", "bet365line"):
        sys.argv = ["poll", *argv[1:]]
        from bet365_line.poll import main as poll_main
    elif bookmaker in ("betcity-line", "betcity_line", "betcityline"):
        sys.argv = ["poll", *argv[1:]]
        from betcity_line.poll import main as poll_main
    elif bookmaker in (
        "lxbet-line",
        "lxbet_line",
        "lxbetline",
        "1xbet-line",
        "1xbet_line",
    ):
        sys.argv = ["poll", *argv[1:]]
        from lxbet_line.poll import main as poll_main
    elif bookmaker in (
        "lxbet-live",
        "lxbet_live",
        "lxbetlive",
        "1xbet-live",
        "1xbet_live",
        "1xbet",
        "lxbet",
    ):
        # Bare 1xbet/lxbet defaults to live (dashboard Live tab).
        sys.argv = ["poll", *argv[1:]]
        from lxbet_live.poll import main as poll_main
    elif bookmaker in ("betcity", "betcity-live", "betcity_live", "betcitylive"):
        sys.argv = ["poll", *argv[1:]]
        from betcity_live.poll import main as poll_main
    elif argv and not argv[0].startswith("-"):
        raise SystemExit(
            "Usage: python main.py poll "
            "[fonbet|ligastavok-live|ligastavok-line|bet365|bet365-line|"
            "betcity-live|betcity-line|lxbet-line|lxbet-live] "
            "[options]\n"
            f"Unknown bookmaker: {argv[0]!r}"
        )
    else:
        # Bare `poll --once` etc. → Fonbet (backward compatible).
        sys.argv = ["poll", *argv]
        from fonbet.poll import main as poll_main

    poll_main()


def _run_adapter(argv: list[str]) -> None:
    if argv and argv[0] in ("ligastavok", "ligastavok-live"):
        sys.argv = ["adapter", *argv[1:]]
        from ligastavok_live.run_adapter import main as adapter_main
    else:
        sys.argv = ["adapter", *argv]
        from fonbet.run_adapter import main as adapter_main

    adapter_main()


def _run_fetch(argv: list[str]) -> None:
    if not argv or argv[0] not in (
        "ligastavok",
        "ligastavok-live",
        "ligastavok_live",
        "ligastavok-line",
        "ligastavok_line",
    ):
        raise SystemExit(
            "Usage: python main.py fetch ligastavok-live|ligastavok-line "
            "[--ns live|prematch] [--curl file.curl]"
        )
    bookmaker = argv[0].replace("_", "-")
    rest = argv[1:]
    # Default ns from package when not passed.
    if bookmaker.endswith("-line") and "--ns" not in rest:
        rest = ["--ns", "prematch", *rest]
    elif bookmaker.endswith("-live") or bookmaker == "ligastavok":
        if "--ns" not in rest:
            rest = ["--ns", "live", *rest]
    sys.argv = ["fetch", *rest]
    if "line" in bookmaker:
        from ligastavok_line.fetch_snapshot import main as fetch_main
    else:
        from ligastavok_live.fetch_snapshot import main as fetch_main

    fetch_main()


def _run_capture(argv: list[str]) -> None:
    if not argv or argv[0] != "bet365":
        raise SystemExit("Usage: python main.py capture bet365 [--env]")
    sys.argv = ["capture", *argv[1:]]
    from bet365.capture_session import main as capture_main

    capture_main()


def _run_listen(argv: list[str]) -> None:
    if not argv or argv[0] not in ("bet365", "betcity"):
        raise SystemExit(
            "Usage: python main.py listen bet365 [--browser] [--direct] [--seconds 60]\n"
            "       python main.py listen betcity [--browser] [--proxy host:port] "
            "[--seconds 30] [--cookie ...] [--save]"
        )
    bookmaker = argv[0]
    rest = argv[1:]
    sys.argv = ["listen", *rest]
    if bookmaker == "betcity":
        from betcity_live.listen import main as listen_main
    else:
        from bet365.listen import main as listen_main

    listen_main()


def _run_setup() -> None:
    from scripts.phase0_setup import main as setup_main

    raise SystemExit(setup_main())


if __name__ == "__main__":
    main()
