"""Standalone Copilot Remote Control Hub.

Runs the Telegram → Copilot CLI (ACP) bridge without depending on MCP.
Can be used both standalone (``python -m telegram_copilot_bridge --hub``)
and from the MCP tool (``telegram_copilot_hub``).
"""

from __future__ import annotations

import logging
import os
import time

from .bot_commander import BotCommander
from .config import load_config
from .session_manager import SessionManager
from .telegram import TelegramClient

logger = logging.getLogger(__name__)


def run_hub(
    *,
    default_cwd: str = "",
    timeout_minutes: int = 60,
    client: TelegramClient | None = None,
    model: str | None = None,
    autopilot: bool = False,
) -> str:
    """Run the Copilot remote-control hub.

    Args:
        default_cwd: Default working directory for new sessions.
        timeout_minutes: How long to stay in hub mode.
        client: Optional pre-configured TelegramClient (used by MCP tool).
                If None, a new client is created from environment/config.

    Returns:
        Status message when the hub exits.
    """
    if client is None:
        config_path = os.environ.get("TELEGRAM_CONFIG_PATH")
        cfg = load_config(config_path)
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

    # Create BotCommander first to get its permission handler
    commander = BotCommander(
        session_mgr=None,  # type: ignore[arg-type]  # set below
        telegram=client,
        default_cwd=default_cwd or os.getcwd(),
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
    client.send_message(
        "🤖 <b>Copilot Remote Control</b>\n\n"
        f"Model: <code>{model_label}</code>\n"
        f"Mode: {mode_label}\n"
        "Send <code>/new</code> to start a session, "
        "or <code>/help</code> for all commands.\n"
        f"Timeout: {timeout_minutes} min."
    )

    client.start_listener(message_handler=commander.handle)

    deadline = time.time() + timeout_minutes * 60
    try:
        while client.listener_active and time.time() < deadline:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Hub interrupted by user.")

    if client.listener_active:
        client.stop_listener()
        client.send_message("⏰ Remote control timed out.")
    mgr.stop_all()

    return "Remote control session ended."
