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
        help="Poll bookmaker API (fonbet default, or ligastavok) — both import to PostgreSQL",
        description="Poll bookmaker API — fonbet, ligastavok, or bet365 imports to PostgreSQL every ~3.5s.",
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
        help="Listen to bookmaker WebSocket (bet365 ZAP)",
        description="Stream WebSocket frames — bet365 ZAP protocol.",
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
    if argv and argv[0] == "ligastavok":
        sys.argv = ["poll", *argv[1:]]
        from ligastavok.poll import main as poll_main
    elif argv and argv[0] == "bet365":
        sys.argv = ["poll", *argv[1:]]
        from bet365.poll import main as poll_main
    else:
        sys.argv = ["poll", *argv]
        from fonbet.poll import main as poll_main

    poll_main()


def _run_adapter(argv: list[str]) -> None:
    if argv and argv[0] == "ligastavok":
        sys.argv = ["adapter", *argv[1:]]
        from ligastavok.run_adapter import main as adapter_main
    else:
        sys.argv = ["adapter", *argv]
        from fonbet.run_adapter import main as adapter_main

    adapter_main()


def _run_fetch(argv: list[str]) -> None:
    if not argv or argv[0] != "ligastavok":
        raise SystemExit("Usage: python main.py fetch ligastavok [--ns live|prematch] [--curl file.curl]")
    sys.argv = ["fetch", *argv[1:]]
    from ligastavok.fetch_snapshot import main as fetch_main

    fetch_main()


def _run_capture(argv: list[str]) -> None:
    if not argv or argv[0] != "bet365":
        raise SystemExit("Usage: python main.py capture bet365 [--env]")
    sys.argv = ["capture", *argv[1:]]
    from bet365.capture_session import main as capture_main

    capture_main()


def _run_listen(argv: list[str]) -> None:
    if not argv or argv[0] != "bet365":
        raise SystemExit(
            "Usage: python main.py listen bet365 [--browser] [--direct] [--seconds 60]"
        )
    sys.argv = ["listen", *argv[1:]]
    from bet365.listen import main as listen_main

    listen_main()


def _run_setup() -> None:
    from scripts.phase0_setup import main as setup_main

    raise SystemExit(setup_main())


if __name__ == "__main__":
    main()
