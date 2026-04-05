"""Multi-session manager for Copilot CLI ACP processes."""

from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from .copilot_bridge import CopilotProcess, PromptResult

logger = logging.getLogger(__name__)


@dataclass
class Session:
    """Metadata for one Copilot ACP session."""

    id: str
    cwd: str
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    model: str = ""
    mode: str = ""
    prompt_count: int = 0
    last_activity: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def touch(self) -> None:
        self.last_activity = datetime.now(timezone.utc)
        self.prompt_count += 1


class SessionManager:
    """Manages multiple Copilot ACP sessions.

    Each session gets its own ``CopilotProcess``.  The manager tracks an
    *active* session that receives prompts by default.
    """

    def __init__(
        self,
        copilot_cmd: str | None = None,
        allowed_tools: list[str] | None = None,
        allowed_dirs: list[str] | None = None,
        model: str | None = None,
        autopilot: bool = False,
        permission_handler: Any = None,
    ) -> None:
        self._copilot_cmd = copilot_cmd or _find_copilot()
        self._allowed_tools = allowed_tools
        self._allowed_dirs = allowed_dirs  # None = any dir allowed
        self._model = model
        self._autopilot = autopilot
        self._permission_handler = permission_handler
        self._processes: dict[str, CopilotProcess] = {}
        self._sessions: dict[str, Session] = {}
        self._active_session_id: str | None = None

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def active_session(self) -> Session | None:
        if self._active_session_id:
            return self._sessions.get(self._active_session_id)
        return None

    @property
    def active_process(self) -> CopilotProcess | None:
        if self._active_session_id:
            return self._processes.get(self._active_session_id)
        return None

    # ------------------------------------------------------------------
    # Session lifecycle
    # ------------------------------------------------------------------

    def create_session(self, cwd: str) -> Session:
        """Create a new Copilot ACP session in *cwd*.

        Raises ValueError if *cwd* is not in the allowed directories list.
        """
        if self._allowed_dirs:
            normalised = cwd.replace("\\", "/").rstrip("/").lower()
            if not any(
                normalised.startswith(d.replace("\\", "/").rstrip("/").lower())
                for d in self._allowed_dirs
            ):
                raise ValueError(
                    f"Directory not allowed: {cwd}. "
                    f"Allowed: {', '.join(self._allowed_dirs)}"
                )

        proc = CopilotProcess(
            copilot_cmd=self._copilot_cmd,
            allowed_tools=self._allowed_tools,
            model=self._model,
            autopilot=self._autopilot,
        )
        if self._permission_handler:
            proc.set_permission_handler(self._permission_handler)
        proc.start()
        proc.initialize()
        result = proc.new_session(cwd)

        session_id = result["sessionId"]
        model = result.get("models", {}).get("currentModelId", "")
        mode_id = result.get("modes", {}).get("currentModeId", "")
        mode = mode_id.rsplit("#", 1)[-1] if "#" in mode_id else mode_id

        session = Session(id=session_id, cwd=cwd, model=model, mode=mode)
        self._sessions[session_id] = session
        self._processes[session_id] = proc
        self._active_session_id = session_id

        logger.info(
            "Created session %s (cwd=%s, model=%s)", session_id[:8], cwd, model
        )
        return session

    def stop_session(self, session_id: str | None = None) -> None:
        """Stop a session. Defaults to the active session."""
        sid = session_id or self._active_session_id
        if not sid:
            raise ValueError("No session to stop")

        proc = self._processes.pop(sid, None)
        if proc:
            proc.stop()
        self._sessions.pop(sid, None)

        if self._active_session_id == sid:
            # Switch to the most recent remaining session
            if self._sessions:
                self._active_session_id = max(
                    self._sessions, key=lambda s: self._sessions[s].last_activity
                )
            else:
                self._active_session_id = None

        logger.info("Stopped session %s", sid[:8] if sid else "?")

    def stop_all(self) -> None:
        """Stop all sessions."""
        for sid in list(self._processes):
            self.stop_session(sid)

    def switch_session(self, session_id: str) -> Session:
        """Set the active session."""
        if session_id not in self._sessions:
            # Try prefix match
            matches = [
                s for s in self._sessions if s.startswith(session_id)
            ]
            if len(matches) == 1:
                session_id = matches[0]
            else:
                raise ValueError(f"Session not found: {session_id}")

        self._active_session_id = session_id
        return self._sessions[session_id]

    def list_sessions(self) -> list[Session]:
        """Return all active sessions."""
        return list(self._sessions.values())

    # ------------------------------------------------------------------
    # Prompt
    # ------------------------------------------------------------------

    def send_prompt(
        self,
        text: str,
        session_id: str | None = None,
        timeout: float = 300.0,
        on_chunk: Any = None,
    ) -> PromptResult:
        """Send a prompt to a session. Defaults to the active session."""
        sid = session_id or self._active_session_id
        if not sid:
            raise ValueError("No active session. Use /new to create one.")

        proc = self._processes.get(sid)
        if not proc or not proc.alive:
            raise RuntimeError(f"Session {sid[:8]} process is not running")

        session = self._sessions[sid]
        session.touch()

        return proc.prompt(sid, text, timeout=timeout, on_chunk=on_chunk)

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    def get_status(self, session_id: str | None = None) -> str:
        """Return an HTML status report."""
        sid = session_id or self._active_session_id
        if not sid or sid not in self._sessions:
            return "ℹ️ No active session."

        s = self._sessions[sid]
        proc = self._processes.get(sid)
        alive = "✅ running" if proc and proc.alive else "❌ stopped"
        is_active = "👉 " if sid == self._active_session_id else ""

        elapsed = datetime.now(timezone.utc) - s.created_at
        hours, remainder = divmod(int(elapsed.total_seconds()), 3600)
        minutes, seconds = divmod(remainder, 60)

        lines = [
            f"<b>🤖 Session {is_active}{s.id[:8]}</b>",
            f"Status: {alive}",
            f"Model: <code>{s.model}</code>",
            f"Mode: {s.mode}",
            f"CWD: <code>{s.cwd}</code>",
            f"Prompts: {s.prompt_count}",
            f"Uptime: {hours}h {minutes}m {seconds}s",
        ]
        return "\n".join(lines)

    def get_list_report(self) -> str:
        """Return an HTML list of all sessions."""
        if not self._sessions:
            return "ℹ️ No active sessions. Use /new to create one."

        lines = [f"<b>📋 Sessions ({len(self._sessions)})</b>"]
        for s in self._sessions.values():
            active = "👉 " if s.id == self._active_session_id else "   "
            proc = self._processes.get(s.id)
            icon = "🟢" if proc and proc.alive else "🔴"
            lines.append(
                f"{active}{icon} <code>{s.id[:8]}</code> "
                f"| {s.model} | {s.cwd} | {s.prompt_count} prompts"
            )
        lines.append("\nUse /switch &lt;id&gt; to change active session.")
        return "\n".join(lines)


def _find_copilot() -> str:
    """Locate the copilot CLI executable."""
    path = shutil.which("copilot")
    if path:
        return path
    raise FileNotFoundError(
        "copilot CLI not found. Install via: winget install GitHub.Copilot "
        "or npm install -g @github/copilot"
    )
