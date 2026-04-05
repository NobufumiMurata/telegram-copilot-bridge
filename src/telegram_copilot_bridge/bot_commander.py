"""Telegram command router for Copilot CLI remote control.

Routes incoming Telegram messages to the appropriate handler:
    /new [cwd]      — create a new Copilot session
    /list           — list active sessions
    /switch <id>    — switch active session
    /status         — current session status
    /stop [id]      — stop a session
    /done           — stop all sessions and exit hub mode
    (free text)     — send as prompt to active session
"""

from __future__ import annotations

import html
import logging
import os
import threading
from typing import Any, Callable

from .session_manager import SessionManager
from .telegram import TelegramClient

logger = logging.getLogger(__name__)

# Telegram message length limit (with some margin for safety)
TG_MAX_LEN = 4000


class BotCommander:
    """Processes Telegram messages and dispatches Copilot commands.

    This class does NOT poll Telegram itself — it receives pre-validated
    messages from the caller (e.g. the background listener or MCP hub tool).
    """

    def __init__(
        self,
        session_mgr: SessionManager,
        telegram: TelegramClient,
        default_cwd: str | None = None,
    ) -> None:
        self._mgr = session_mgr
        self._tg = telegram
        self._default_cwd = default_cwd or os.getcwd()
        self._prompt_in_progress = False

    def get_permission_handler(self) -> Callable[[dict[str, Any]], str]:
        """Return a permission handler that uses Telegram inline buttons."""
        return self._handle_permission_request

    def _handle_permission_request(self, params: dict[str, Any]) -> str:
        """Ask user via Telegram inline keyboard and return optionId."""
        tool_call = params.get("toolCall", {})
        title = tool_call.get("title", "Unknown action")
        raw_input = tool_call.get("rawInput", {})
        command = raw_input.get("command", "")
        description = raw_input.get("description", "")

        # Build message
        msg_parts = [f"🔐 <b>Permission Request</b>\n\n<b>{html.escape(title)}</b>"]
        if command:
            msg_parts.append(f"\n<code>{html.escape(command)}</code>")
        elif description:
            msg_parts.append(f"\n{html.escape(description)}")
        message = "".join(msg_parts)

        # Build inline keyboard from ACP options
        options = params.get("options", [])
        if not options:
            options = [
                {"optionId": "allow_once", "name": "Allow once"},
                {"optionId": "reject_once", "name": "Deny"},
            ]

        buttons = [[
            {"text": opt["name"], "callback_data": opt["optionId"]}
            for opt in options[:3]  # Telegram row limit
        ]]

        try:
            self._tg.send_inline_keyboard(message, buttons)
            # Wait for callback — 2 min timeout for permission decisions
            result = self._tg.wait_for_callback(timeout_seconds=120)
            if result is None:
                logger.warning("Permission request timed out, denying")
                self._reply("⏰ Permission timed out — denied.")
                return "reject_once"
            self._reply(f"✅ Permission: {result}")
            return result
        except Exception:
            logger.exception("Failed to send permission request")
            return "reject_once"

    # ------------------------------------------------------------------
    # Main dispatch
    # ------------------------------------------------------------------

    def handle(self, text: str) -> str | None:
        """Handle a single message from Telegram.

        Returns a control signal string (``"SESSION_END"``, ``"TIMEOUT"``)
        or ``None`` for normal commands/prompts.
        """
        text = text.strip()
        if not text:
            return None

        if text.startswith("/"):
            return self._handle_command(text)
        else:
            return self._handle_prompt(text)

    # ------------------------------------------------------------------
    # Command handlers
    # ------------------------------------------------------------------

    def _handle_command(self, text: str) -> str | None:
        parts = text.split(maxsplit=1)
        cmd = parts[0].lower()
        arg = parts[1].strip() if len(parts) > 1 else ""

        handlers = {
            "/new": self._cmd_new,
            "/list": self._cmd_list,
            "/switch": self._cmd_switch,
            "/status": self._cmd_status,
            "/stop": self._cmd_stop,
            "/done": self._cmd_done,
            "/help": self._cmd_help,
        }

        handler = handlers.get(cmd)
        if handler:
            return handler(arg)

        self._reply(f"❓ Unknown command: <code>{cmd}</code>\nType /help for commands.")
        return None

    def _cmd_new(self, arg: str) -> str | None:
        cwd = arg or self._default_cwd
        try:
            session = self._mgr.create_session(cwd)
            self._reply(
                f"✅ New session <code>{session.id[:8]}</code>\n"
                f"Model: {session.model}\n"
                f"Mode: {session.mode}\n"
                f"CWD: <code>{session.cwd}</code>\n\n"
                f"Send a message to start working."
            )
        except FileNotFoundError as e:
            self._reply(f"❌ {e}")
        except Exception as e:
            self._reply(f"❌ Failed to create session:\n<code>{e}</code>")
        return None

    def _cmd_list(self, _arg: str) -> str | None:
        report = self._mgr.get_list_report()
        self._reply(report)
        return None

    def _cmd_switch(self, arg: str) -> str | None:
        if not arg:
            self._reply("Usage: /switch &lt;session-id-prefix&gt;")
            return None
        try:
            session = self._mgr.switch_session(arg)
            self._reply(f"👉 Switched to session <code>{session.id[:8]}</code>")
        except ValueError as e:
            self._reply(f"❌ {e}")
        return None

    def _cmd_status(self, arg: str) -> str | None:
        report = self._mgr.get_status(arg or None)
        self._reply(report)
        return None

    def _cmd_stop(self, arg: str) -> str | None:
        try:
            self._mgr.stop_session(arg or None)
            self._reply("🛑 Session stopped.")
        except ValueError as e:
            self._reply(f"❌ {e}")
        return None

    def _cmd_done(self, _arg: str) -> str | None:
        self._mgr.stop_all()
        self._reply("👋 All sessions stopped. Exiting remote control mode.")
        return "SESSION_END"

    def _cmd_help(self, _arg: str) -> str | None:
        self._reply(
            "<b>📖 Commands</b>\n"
            "/new [dir]     — New Copilot session\n"
            "/list          — List sessions\n"
            "/switch &lt;id&gt;  — Switch active session\n"
            "/status        — Session status\n"
            "/stop [id]     — Stop a session\n"
            "/done          — Stop all & exit\n"
            "/help          — This message\n"
            "\n(any text)     — Send as prompt"
        )
        return None

    # ------------------------------------------------------------------
    # Prompt handler
    # ------------------------------------------------------------------

    def _handle_prompt(self, text: str) -> str | None:
        if not self._mgr.active_session:
            self._reply(
                "⚠️ No active session.\n"
                "Use <code>/new</code> to create one first."
            )
            return None

        if self._prompt_in_progress:
            self._reply("⏳ Still processing the previous prompt. Please wait.")
            return None

        self._prompt_in_progress = True
        self._reply("⏳ Processing…")

        threading.Thread(
            target=self._run_prompt, args=(text,), daemon=True, name="prompt-worker"
        ).start()
        return None

    def _run_prompt(self, text: str) -> None:
        """Execute a Copilot prompt in a background thread."""
        try:
            result = self._mgr.send_prompt(text, timeout=300.0)
            response_text = result.text or "(empty response)"
            # Copilot returns Markdown — escape HTML entities so Telegram
            # doesn't choke on unmatched < > & characters.
            self._send_long_message(html.escape(response_text))
        except TimeoutError:
            self._reply("⏰ Copilot response timed out after 5 minutes.")
        except Exception as e:
            logger.exception("Prompt execution failed")
            self._reply(f"❌ Error:\n<pre>{html.escape(str(e))}</pre>")
        finally:
            self._prompt_in_progress = False

    # ------------------------------------------------------------------
    # Telegram helpers
    # ------------------------------------------------------------------

    def _reply(self, text: str) -> None:
        try:
            self._tg.send_message(text)
        except Exception:
            logger.exception("Failed to send Telegram message")

    def _send_long_message(self, text: str) -> None:
        """Split and send text that may exceed Telegram's 4096 char limit."""
        if len(text) <= TG_MAX_LEN:
            self._reply(text)
            return

        # Split on newlines when possible
        chunks: list[str] = []
        current = ""
        for line in text.split("\n"):
            if len(current) + len(line) + 1 > TG_MAX_LEN:
                if current:
                    chunks.append(current)
                current = line[:TG_MAX_LEN]  # truncate single long lines
            else:
                current = current + "\n" + line if current else line
        if current:
            chunks.append(current)

        for i, chunk in enumerate(chunks):
            prefix = f"<b>[{i + 1}/{len(chunks)}]</b>\n" if len(chunks) > 1 else ""
            self._reply(prefix + chunk)
