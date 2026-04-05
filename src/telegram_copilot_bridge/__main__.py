"""Entry point for ``python -m telegram_copilot_bridge``.

Starts the Copilot remote-control hub (Telegram → Copilot CLI via ACP).
"""

from __future__ import annotations

import argparse
import logging
import sys


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="telegram_copilot_bridge",
        description="Telegram → Copilot CLI remote-control bridge",
    )
    parser.add_argument(
        "--cwd",
        default="",
        help="Default working directory for Copilot sessions.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=0,
        help="Hub timeout in minutes (0 = no timeout, default: 0).",
    )
    parser.add_argument(
        "--model",
        default="claude-opus-4.6",
        help="AI model to use (default: claude-opus-4.6).",
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

    from .hub import run_hub

    try:
        result = run_hub(
            default_cwd=args.cwd,
            timeout_minutes=args.timeout,
            model=args.model or None,
            autopilot=args.autopilot,
        )
    except RuntimeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
    print(result)


main()
