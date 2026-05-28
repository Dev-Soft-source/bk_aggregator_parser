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
        help="Poll Fonbet live API and import into PostgreSQL",
        description="Poll Fonbet API and import to PostgreSQL.",
    )
    sub.add_parser(
        "adapter",
        help="Map Fonbet packet to normalized changes (no DB)",
        description="Fonbet adapter — map packet or stream live API.",
    )
    sub.add_parser(
        "setup",
        help="Phase 0: init schema, import test.json, verify booker_adapter",
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
    elif command not in ("import", "poll", "adapter", "setup") and not command.startswith("-"):
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
    sys.argv = ["poll", *argv]
    from fonbet.poll import main as poll_main

    poll_main()


def _run_adapter(argv: list[str]) -> None:
    sys.argv = ["adapter", *argv]
    from fonbet.run_adapter import main as adapter_main

    adapter_main()


def _run_setup() -> None:
    from scripts.phase0_setup import main as setup_main

    raise SystemExit(setup_main())


if __name__ == "__main__":
    main()
