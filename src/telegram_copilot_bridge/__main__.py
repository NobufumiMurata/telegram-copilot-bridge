"""Entry point for ``python -m telegram_copilot_bridge``.

Modes:
    (default)   Start as MCP stdio server.
    --hub       Start standalone Copilot remote-control hub (no MCP).
"""

from __future__ import annotations

import argparse
import logging
import sys


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="telegram_copilot_bridge",
        description="Telegram ↔ Copilot bridge",
    )
    parser.add_argument(
        "--hub",
        action="store_true",
        help="Run standalone Copilot remote-control hub (Telegram → Copilot CLI).",
    )
    parser.add_argument(
        "--cwd",
        default="",
        help="Default working directory for Copilot sessions (hub mode).",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=60,
        help="Hub timeout in minutes (default: 60).",
    )
    parser.add_argument(
        "--model",
        default="",
        help="AI model to use (e.g. claude-opus-4.6, claude-sonnet-4.6).",
    )
    parser.add_argument(
        "--autopilot",
        action="store_true",
        help="Enable autopilot mode (auto-approve tool calls).",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable debug logging.",
    )
    args = parser.parse_args()

    if args.verbose:
        logging.basicConfig(level=logging.DEBUG, stream=sys.stderr)

    if args.hub:
        from .hub import run_hub

        result = run_hub(
            default_cwd=args.cwd,
            timeout_minutes=args.timeout,
            model=args.model or None,
            autopilot=args.autopilot,
        )
        print(result)
    else:
        from .server import mcp

        mcp.run()


main()
