"""Standalone Copilot Remote Control Hub.

Runs the Telegram → Copilot CLI (ACP) bridge without depending on MCP.
Uses its own Bot token (TELEGRAM_HUB_BOT_TOKEN) to avoid conflicts
with the MCP notification Bot.
"""

from __future__ import annotations

import logging
import os
import socket
import time

from .bot_commander import BotCommander
from .config import load_hub_config
from .session_manager import SessionManager
from .telegram import TelegramClient

logger = logging.getLogger(__name__)

# Lock port for singleton enforcement. Override via env var HUB_LOCK_PORT.
_DEFAULT_LOCK_PORT = 47732


def _acquire_hub_lock() -> socket.socket:
    """Acquire a singleton lock by binding a localhost TCP socket.

    Only one Hub instance per machine can hold the lock at a time.
    The socket is released automatically when the process exits.

    Raises:
        RuntimeError: If another Hub instance is already running.
    """
    port = int(os.environ.get("HUB_LOCK_PORT", _DEFAULT_LOCK_PORT))
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    # Explicitly disable SO_REUSEADDR so the bind fails if the port is taken.
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
    try:
        sock.bind(("127.0.0.1", port))
    except OSError:
        sock.close()
        raise RuntimeError(
            f"Hub is already running (lock port {port} is in use). "
            "Stop the existing Hub before starting a new one."
        )
    return sock


def run_hub(
    *,
    default_cwd: str = "",
    timeout_minutes: int = 60,
    model: str | None = None,
    autopilot: bool = False,
) -> str:
    """Run the Copilot remote-control hub.

    Args:
        default_cwd: Default working directory for new sessions.
        timeout_minutes: How long to stay in hub mode.
        model: AI model to use (e.g. claude-opus-4.6).
        autopilot: Enable autopilot mode.

    Returns:
        Status message when the hub exits.
    """
    lock_sock = _acquire_hub_lock()
    try:
        return _run_hub_locked(
            default_cwd=default_cwd,
            timeout_minutes=timeout_minutes,
            model=model,
            autopilot=autopilot,
        )
    finally:
        lock_sock.close()


def _run_hub_locked(
    *,
    default_cwd: str,
    timeout_minutes: int,
    model: str | None,
    autopilot: bool,
) -> str:
    cfg = load_hub_config()
    client = TelegramClient(
        bot_token=cfg.bot_token,
        chat_id=cfg.chat_id,
        allowed_users=cfg.allowed_users,
    )

    copilot_cmd = os.environ.get("COPILOT_CLI_PATH", "copilot")
    allowed_tools_str = os.environ.get("COPILOT_ALLOWED_TOOLS", "")
    allowed_tools = (
        [t.strip() for t in allowed_tools_str.split(",") if t.strip()]
        if allowed_tools_str
        else None
    )
    allowed_dirs_str = os.environ.get("COPILOT_ALLOWED_DIRS", "")
    allowed_dirs = (
        [d.strip() for d in allowed_dirs_str.split(",") if d.strip()]
        if allowed_dirs_str
        else None
    )

    copilot_model = model or os.environ.get("COPILOT_MODEL", "")
    copilot_autopilot = autopilot or os.environ.get("COPILOT_AUTOPILOT", "").lower() in ("1", "true", "yes")

    dirs_root = os.environ.get("COPILOT_DIRS_ROOT", "")

    # Create BotCommander first to get its permission handler
    commander = BotCommander(
        session_mgr=None,  # type: ignore[arg-type]  # set below
        telegram=client,
        default_cwd=default_cwd or os.getcwd(),
        dirs_root=dirs_root or None,
    )

    # Use Telegram-based permission handler unless autopilot is on
    permission_handler = None if copilot_autopilot else commander.get_permission_handler()

    mgr = SessionManager(
        copilot_cmd=copilot_cmd,
        allowed_tools=allowed_tools,
        allowed_dirs=allowed_dirs,
        model=copilot_model or None,
        autopilot=copilot_autopilot,
        permission_handler=permission_handler,
    )
    commander._mgr = mgr

    mode_label = "🤖 Autopilot" if copilot_autopilot else "🔐 Manual approval"
    model_label = copilot_model or "default"
    timeout_label = f"{timeout_minutes} min" if timeout_minutes > 0 else "unlimited"
    client.send_message(
        "🤖 <b>Copilot Remote Control</b>\n\n"
        f"Model: <code>{model_label}</code>\n"
        f"Mode: {mode_label}\n"
        "Send <code>/new</code> to start a session, "
        "or <code>/help</code> for all commands.\n"
        f"Timeout: {timeout_label}."
    )

    client.start_listener(message_handler=commander.handle)

    no_timeout = timeout_minutes <= 0
    deadline = time.time() + timeout_minutes * 60 if not no_timeout else 0
    try:
        while client.listener_active and (no_timeout or time.time() < deadline):
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Hub interrupted by user.")

    if client.listener_active:
        client.stop_listener()
        client.send_message("⏰ Remote control timed out.")
    mgr.stop_all()

    return "Remote control session ended."
