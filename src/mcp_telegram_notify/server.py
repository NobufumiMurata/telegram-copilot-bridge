"""MCP server exposing Telegram notification and approval tools."""

from __future__ import annotations

import os

from mcp.server.fastmcp import FastMCP

from .config import load_config
from .telegram import TelegramClient

mcp = FastMCP(
    "telegram-notify",
    instructions="Telegram notifications, approvals, and remote prompts for VS Code Copilot",
)

_client: TelegramClient | None = None


def _get_client() -> TelegramClient:
    global _client
    if _client is None:
        config_path = os.environ.get("TELEGRAM_CONFIG_PATH")
        cfg = load_config(config_path)
        _client = TelegramClient(
            bot_token=cfg.bot_token,
            chat_id=cfg.chat_id,
            allowed_users=cfg.allowed_users,
        )
    return _client


# ------------------------------------------------------------------
# MCP Tools
# ------------------------------------------------------------------


@mcp.tool()
def telegram_notify(message: str) -> str:
    """Send a notification message to Telegram.

    Use this to report task completions, status updates, or any information
    the user should see on their mobile device.

    Args:
        message: The message text to send. Supports HTML formatting.
    """
    client = _get_client()
    client.send_message(message)
    return "Message sent successfully."


@mcp.tool()
def telegram_ask_approval(
    question: str,
    options: list[str] | None = None,
    timeout_minutes: int = 5,
) -> str:
    """Send an approval request with inline buttons and wait for the user's choice.

    Use this before destructive operations (VM deletion, resource removal,
    network changes) to get explicit user approval via their smartphone.

    Args:
        question: The question to display (e.g. "Delete VM-FWTest-001?").
        options: Button labels (default: ["Approve", "Reject"]).
        timeout_minutes: How long to wait for a response (default: 5).
    """
    if options is None:
        options = ["Approve", "Reject"]

    client = _get_client()
    buttons = [[{"text": opt, "callback_data": opt} for opt in options]]
    client.send_inline_keyboard(question, buttons)

    result = client.wait_for_callback(timeout_seconds=timeout_minutes * 60)
    if result is None:
        return f"TIMEOUT: No response received within {timeout_minutes} minutes."
    return f"User selected: {result}"


@mcp.tool()
def telegram_wait_response(
    prompt: str,
    timeout_minutes: int = 10,
) -> str:
    """Send a prompt and wait for a free-text reply from the user's smartphone.

    Use this after completing a task to receive the next instruction,
    or when you need additional information from the user.

    Args:
        prompt: The prompt message to send (e.g. "What should I do next?").
        timeout_minutes: How long to wait for a response (default: 10).
    """
    client = _get_client()
    client.send_message(prompt)

    result = client.wait_for_text(timeout_seconds=timeout_minutes * 60)
    if result is None:
        return f"TIMEOUT: No response received within {timeout_minutes} minutes."
    return result


@mcp.tool()
def telegram_send_file(
    file_path: str,
    caption: str = "",
) -> str:
    """Send a file to Telegram.

    Use this to share logs, JSON results, screenshots, or other artifacts
    with the user on their mobile device.

    Args:
        file_path: Absolute path to the file to send.
        caption: Optional caption for the file.
    """
    client = _get_client()
    client.send_document(file_path, caption=caption)
    return f"File sent: {file_path}"
