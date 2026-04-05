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
        dirs_root: str | None = None,
    ) -> None:
        self._mgr = session_mgr
        self._tg = telegram
        self._default_cwd = default_cwd or os.getcwd()
        self._dirs_root = dirs_root or ""
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
            "/history": self._cmd_history,
            "/resume": self._cmd_resume,
            "/switch": self._cmd_switch,
            "/status": self._cmd_status,
            "/stop": self._cmd_stop,
            "/done": self._cmd_done,
            "/dirs": self._cmd_dirs,
            "/model": self._cmd_model,
            "/mode": self._cmd_mode,
            "/help": self._cmd_help,
        }

        handler = handlers.get(cmd)
        if handler:
            return handler(arg)

        self._reply(f"❓ Unknown command: <code>{cmd}</code>\nType /help for commands.")
        return None

    def _cmd_new(self, arg: str) -> str | None:
        # Show folder picker when no arg and dirs_root is configured
        if not arg and self._dirs_root:
            return self._show_new_folder_picker()

        cwd = self._resolve_cwd(arg) if arg else self._default_cwd
        self._create_session(cwd)
        return None

    def _resolve_cwd(self, arg: str) -> str:
        """Resolve a cwd argument, checking dirs_root for relative names."""
        import pathlib

        p = pathlib.Path(arg)
        if not p.is_absolute() and self._dirs_root:
            candidate = pathlib.Path(self._dirs_root) / arg
            if candidate.is_dir():
                return str(candidate.resolve())
        return arg

    def _create_session(self, cwd: str) -> None:
        """Create a new Copilot session in *cwd* and report the result."""
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

    def _show_new_folder_picker(self) -> str | None:
        """Show inline buttons for subdirectories under dirs_root."""
        import pathlib

        try:
            root = pathlib.Path(self._dirs_root).resolve()
            if not root.is_dir():
                self._reply(f"❌ COPILOT_DIRS_ROOT is not a directory: <code>{html.escape(str(root))}</code>")
                return None

            dirs = sorted(
                e for e in root.iterdir()
                if e.is_dir() and not e.name.startswith(".")
            )
            if not dirs:
                self._reply(
                    f"📂 <code>{html.escape(str(root))}</code>\n"
                    "No subdirectories found. Use <code>/new /path/to/dir</code> directly."
                )
                return None

            buttons = []
            for d in dirs[:20]:
                # Use folder name only (not full path) to stay within
                # Telegram's 64-byte callback_data limit.
                buttons.append([
                    {"text": f"📁 {d.name}", "callback_data": f"newcwd:{d.name}"}
                ])

            text = (
                f"📂 <b>Select working directory</b>\n"
                f"Root: <code>{html.escape(str(root))}</code>"
            )
            if len(dirs) > 20:
                text += f"\n(showing 20 of {len(dirs)} — use <code>/new /path</code> for others)"

            self._tg.send_inline_keyboard(text, buttons)
        except Exception as e:
            self._reply(f"❌ Error: <code>{html.escape(str(e))}</code>")
        return None

    def _cmd_list(self, _arg: str) -> str | None:
        report = self._mgr.get_list_report()
        self._reply(report)
        return None

    def _cmd_history(self, arg: str) -> str | None:
        limit = 3
        if arg.strip().isdigit():
            limit = max(1, int(arg.strip()))
        self._reply("⏳ Discovering persisted sessions…")
        text, sessions = self._mgr.get_history_data(limit=limit)
        if sessions:
            buttons = []
            for s in sessions[:10]:
                sid = s.get("sessionId", "")
                title = s.get("title", "")
                label = f"▶ {sid[:8]}"
                if title:
                    label += f" {title[:24]}"
                buttons.append([
                    {"text": label, "callback_data": f"resume:{sid[:8]}"}
                ])
            self._tg.send_inline_keyboard(text, buttons)
        else:
            self._reply(text)
        return None

    def _cmd_resume(self, arg: str) -> str | None:
        if not arg:
            self._reply(
                "Usage: /resume &lt;session-id-prefix&gt;\n"
                "Use /history to see available sessions."
            )
            return None
        try:
            self._reply("⏳ Resuming session…")
            session = self._mgr.resume_session(arg)
            self._reply(
                f"✅ Resumed session <code>{session.id[:8]}</code>\n"
                f"Model: {session.model}\n"
                f"Mode: {session.mode}\n"
                f"CWD: <code>{session.cwd}</code>\n\n"
                f"Send a message to continue working."
            )
        except ValueError as e:
            self._reply(f"❌ {e}")
        except Exception as e:
            self._reply(f"❌ Failed to resume session:\n<code>{html.escape(str(e))}</code>")
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

    def _cmd_dirs(self, arg: str) -> str | None:
        """List directory contents to help choose a /new target."""
        import pathlib

        target = arg or self._dirs_root or self._default_cwd
        try:
            p = pathlib.Path(target).resolve()
            if not p.is_dir():
                self._reply(f"❌ Not a directory: <code>{html.escape(str(p))}</code>")
                return None

            entries = sorted(p.iterdir())
            dirs = [e.name + "/" for e in entries if e.is_dir() and not e.name.startswith(".")]
            files = [e.name for e in entries if e.is_file() and not e.name.startswith(".")]

            lines = [f"📂 <code>{html.escape(str(p))}</code>\n"]
            if dirs:
                lines.append("<b>Folders:</b>")
                for d in dirs[:30]:
                    lines.append(f"  📁 <code>{html.escape(d)}</code>")
                if len(dirs) > 30:
                    lines.append(f"  ... +{len(dirs) - 30} more")
            if files:
                lines.append("<b>Files:</b>")
                for f in files[:20]:
                    lines.append(f"  📄 <code>{html.escape(f)}</code>")
                if len(files) > 20:
                    lines.append(f"  ... +{len(files) - 20} more")
            if not dirs and not files:
                lines.append("(empty)")

            self._reply("\n".join(lines))
        except Exception as e:
            self._reply(f"❌ Error: <code>{html.escape(str(e))}</code>")
        return None

    def _cmd_model(self, arg: str) -> str | None:
        """Show or change the AI model for new sessions."""
        if not arg:
            current = self._mgr.model or "default"
            self._reply(
                f"🧠 Current model: <code>{html.escape(current)}</code>\n\n"
                "Usage: <code>/model claude-opus-4.6</code>\n"
                "Common models:\n"
                "  <code>claude-opus-4.6</code>\n"
                "  <code>claude-sonnet-4.6</code>\n"
                "  <code>claude-sonnet-4.5</code>\n"
                "  <code>claude-haiku-4.5</code>\n\n"
                "⚠️ Applies to new sessions only."
            )
        else:
            self._mgr.model = arg
            self._reply(f"🧠 Model set to: <code>{html.escape(arg)}</code>\nNew sessions will use this model.")
        return None

    def _cmd_mode(self, arg: str) -> str | None:
        """Toggle between autopilot and manual approval mode."""
        if arg.lower() in ("autopilot", "auto", "on"):
            self._mgr.autopilot = True
        elif arg.lower() in ("manual", "off"):
            self._mgr.autopilot = False
        else:
            # Toggle
            self._mgr.autopilot = not self._mgr.autopilot

        label = "🤖 Autopilot" if self._mgr.autopilot else "🔐 Manual approval"
        self._reply(f"Mode: {label}\n⚠️ Applies to new sessions only.")
        return None

    def _cmd_help(self, _arg: str) -> str | None:
        autopilot_label = "🤖 autopilot" if self._mgr.autopilot else "🔐 manual"
        model_label = self._mgr.model or "default"
        self._reply(
            "<b>📖 Commands</b>\n"
            "/new [dir]     — New Copilot session\n"
            "/history [n]   — List past CLI sessions (default: 3)\n"
            "/resume &lt;id&gt;  — Resume a past session\n"
            "/dirs [dir]    — Browse directories\n"
            "/model [name]  — Show/set AI model\n"
            "/mode          — Toggle autopilot/manual\n"
            "/list          — List active sessions\n"
            "/switch &lt;id&gt;  — Switch active session\n"
            "/status        — Session status\n"
            "/stop [id]     — Stop a session\n"
            "/done          — Stop all & exit\n"
            "/help          — This message\n"
            "\n(any text)     — Send as prompt\n"
            f"\n<b>Current:</b> model=<code>{model_label}</code> mode={autopilot_label}"
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
