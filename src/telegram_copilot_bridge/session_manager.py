"""Multi-session manager for Copilot CLI ACP processes."""

from __future__ import annotations

import html as html_mod
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
    def model(self) -> str | None:
        return self._model

    @model.setter
    def model(self, value: str | None) -> None:
        self._model = value

    @property
    def autopilot(self) -> bool:
        return self._autopilot

    @autopilot.setter
    def autopilot(self, value: bool) -> None:
        self._autopilot = value
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
    # External session discovery
    # ------------------------------------------------------------------

    def discover_sessions(self) -> list[dict[str, Any]]:
        """Discover all persisted Copilot CLI sessions.

        Spins up a temporary ACP process, calls ``session/list``, and
        returns the raw session metadata.  The caller's managed sessions
        are **not** affected.
        """
        proc = CopilotProcess(
            copilot_cmd=self._copilot_cmd,
            allowed_tools=self._allowed_tools,
            model=self._model,
            autopilot=self._autopilot,
        )
        try:
            proc.start()
            proc.initialize()
            sessions = proc.list_sessions()
        finally:
            proc.stop()

        # Filter out sessions already managed by this manager
        managed_ids = set(self._sessions)
        return [s for s in sessions if s.get("sessionId") not in managed_ids]

    def resume_session(self, session_id: str) -> Session:
        """Resume a previously persisted Copilot CLI session.

        *session_id* can be a prefix. The method discovers available
        sessions, finds the match, and runs ``session/load`` to reattach.

        Raises ``ValueError`` if the session is not found or ambiguous.
        """
        if session_id in self._sessions:
            raise ValueError(
                f"Session {session_id[:8]} is already active. Use /switch."
            )

        # Discover external sessions
        external = self.discover_sessions()
        matches = [
            s for s in external if s["sessionId"].startswith(session_id)
        ]
        if not matches:
            raise ValueError(
                f"No persisted session matching '{session_id}'. "
                "Use /history to see available sessions."
            )
        if len(matches) > 1:
            ids = ", ".join(m["sessionId"][:8] for m in matches)
            raise ValueError(
                f"Ambiguous prefix '{session_id}' matches: {ids}"
            )

        target = matches[0]
        target_id = target["sessionId"]
        cwd = target.get("cwd", "").replace("\\\\", "\\")

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
        result = proc.load_session(target_id, cwd)

        model = result.get("models", {}).get("currentModelId", "")
        mode_id = result.get("modes", {}).get("currentModeId", "")
        mode = mode_id.rsplit("#", 1)[-1] if "#" in mode_id else mode_id

        session = Session(id=target_id, cwd=cwd, model=model, mode=mode)
        self._sessions[target_id] = session
        self._processes[target_id] = proc
        self._active_session_id = target_id

        logger.info(
            "Resumed session %s (cwd=%s, model=%s)",
            target_id[:8], cwd, model,
        )
        return session

    def get_history_data(
        self, limit: int = 3
    ) -> tuple[str, list[dict[str, Any]]]:
        """Return an HTML report and raw session list of persisted sessions.

        *limit* controls how many sessions to return (most recent first).
        Returns ``(html_text, sessions_list)`` where *sessions_list* is the
        raw external session metadata (empty on error or no results).
        """
        try:
            external = self.discover_sessions()
        except Exception as e:
            return (
                f"❌ Failed to discover sessions:\n"
                f"<code>{html_mod.escape(str(e))}</code>",
                [],
            )

        if not external:
            return (
                "ℹ️ No persisted sessions found (or all are already active).",
                [],
            )

        # Sort by updatedAt descending (newest first)
        external.sort(key=lambda s: s.get("updatedAt", ""), reverse=True)
        total = len(external)
        shown = external[:limit]

        header = f"<b>📜 Session History (latest {len(shown)}/{total})</b>"
        lines = [header]
        for s in shown:
            sid = s.get("sessionId", "?")
            cwd = s.get("cwd", "?").replace("\\\\", "\\")
            title = s.get("title", "")
            updated = s.get("updatedAt", "")
            ts_label = updated[:16].replace("T", " ") if updated else "?"
            line = (
                f"  <code>{html_mod.escape(sid[:8])}</code> "
                f"| {html_mod.escape(cwd)} "
                f"| {html_mod.escape(title[:40])}"
                f"\n      {ts_label}"
            )
            lines.append(line)
        if total > limit:
            lines.append(
                f"\n📎 {total - limit} more — use"
                f" <code>/history {total}</code> to show all"
            )
        lines.append(
            "\n💡 Tap a session below to resume, or use"
            " <code>/resume &lt;id&gt;</code>"
        )
        return ("\n".join(lines), shown)

    def get_history_report(self) -> str:
        """Return an HTML report of all persisted Copilot CLI sessions."""
        text, _ = self.get_history_data()
        return text

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

    def get_last_response(self, session_id: str | None = None) -> str | None:
        """Return the last assistant response from a session.

        Reads the session's ``events.jsonl`` (Copilot CLI persisted log)
        and returns the most recent ``assistant.message`` content, or *None*
        if nothing is found.
        """
        import json as json_mod
        from pathlib import Path

        sid = session_id or self._active_session_id
        if not sid:
            return None

        home = Path.home()
        events_file = home / ".copilot" / "session-state" / sid / "events.jsonl"
        if not events_file.is_file():
            return None

        last_content: str | None = None
        try:
            with events_file.open(encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = json_mod.loads(line)
                    except json_mod.JSONDecodeError:
                        continue
                    if obj.get("type") == "assistant.message":
                        content = obj.get("data", {}).get("content", "")
                        if content:
                            last_content = content
        except Exception:
            logger.exception("Failed to read events.jsonl for session %s", sid[:8] if sid else "?")
            return None

        return last_content


def _find_copilot() -> str:
    """Locate the copilot CLI executable."""
    path = shutil.which("copilot")
    if path:
        return path
    raise FileNotFoundError(
        "copilot CLI not found. Install via: winget install GitHub.Copilot "
        "or npm install -g @github/copilot"
    )
