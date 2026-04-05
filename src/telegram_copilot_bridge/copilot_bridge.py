"""Copilot CLI ACP (Agent Client Protocol) bridge.

Manages a ``copilot --acp`` subprocess and communicates via NDJSON over stdio.

Confirmed ACP methods (Copilot CLI v0.0.422, ACP protocol v1):
    initialize           → agentCapabilities, agentInfo
    session/new          → sessionId, models, modes
    session/prompt       → streaming session/update notifications + stopReason
    session/list         → sessions
    session/load         → reload a previous session

Notifications (server → client):
    session/update       → agent_message_chunk, tool_call, permission_request, etc.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable

logger = logging.getLogger(__name__)

# Default tools to allow without interactive approval
DEFAULT_ALLOWED_TOOLS = ["shell", "read", "write"]

ACP_PROTOCOL_VERSION = 1


@dataclass
class ACPResponse:
    """Parsed ACP JSON-RPC response."""

    id: int | None
    result: dict[str, Any] | None = None
    error: dict[str, Any] | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


@dataclass
class PromptResult:
    """Aggregated result of a session/prompt call."""

    text: str
    stop_reason: str
    raw_chunks: list[dict[str, Any]] = field(default_factory=list)


class CopilotProcess:
    """Manages a single ``copilot --acp`` subprocess.

    Thread-safe: all public methods can be called from any thread.
    """

    def __init__(
        self,
        copilot_cmd: str = "copilot",
        allowed_tools: list[str] | None = None,
        model: str | None = None,
        autopilot: bool = False,
    ) -> None:
        self._cmd = copilot_cmd
        self._allowed_tools = allowed_tools or list(DEFAULT_ALLOWED_TOOLS)
        self._model = model
        self._autopilot = autopilot
        self._proc: subprocess.Popen | None = None
        self._msg_id = 0
        self._lock = threading.Lock()

        # Response routing: msg_id → threading.Event + response slot
        self._pending: dict[int, tuple[threading.Event, list[ACPResponse]]] = {}
        # Notification callback
        self._on_notification: Callable[[dict[str, Any]], None] | None = None
        # Permission request callback: receives params, returns optionId
        self._on_permission_request: Callable[[dict[str, Any]], str] | None = None
        # Reader thread
        self._reader_thread: threading.Thread | None = None
        self._running = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Spawn the copilot --acp subprocess."""
        if self._proc is not None:
            return

        cmd = [self._cmd, "--acp"]
        if self._autopilot:
            cmd.append("--no-ask-user")
        for tool in self._allowed_tools:
            cmd.extend(["--allow-tool", tool])
        if self._model:
            cmd.extend(["--model", self._model])
        if self._autopilot:
            cmd.append("--autopilot")

        # Use unbuffered binary mode to avoid pipe buffering deadlocks.
        # On Windows, PIPE with text mode can cause the subprocess to
        # block-buffer stdout when it detects a pipe (not a terminal).
        env = os.environ.copy()
        env["NO_COLOR"] = "1"  # Disable ANSI escapes from CLI

        self._proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            bufsize=0,
            env=env,
        )
        self._running = True
        self._reader_thread = threading.Thread(
            target=self._read_loop, daemon=True, name="acp-reader"
        )
        self._reader_thread.start()
        logger.info("Copilot ACP process started (PID %s)", self._proc.pid)

    def stop(self) -> None:
        """Terminate the subprocess gracefully."""
        self._running = False
        if self._proc is not None:
            try:
                if self._proc.stdin:
                    self._proc.stdin.close()
                self._proc.terminate()
                self._proc.wait(timeout=5)
            except Exception:
                self._proc.kill()
            finally:
                self._proc = None
        # Wake up any pending waiters
        for event, _ in self._pending.values():
            event.set()
        self._pending.clear()
        logger.info("Copilot ACP process stopped")

    @property
    def alive(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def set_notification_handler(
        self, handler: Callable[[dict[str, Any]], None]
    ) -> None:
        """Register a callback for ACP notifications (no ``id`` field)."""
        self._on_notification = handler

    def set_permission_handler(
        self, handler: Callable[[dict[str, Any]], str]
    ) -> None:
        """Register a callback for ACP permission requests.

        The handler receives the ``params`` dict and must return an optionId
        (e.g. ``"allow_once"``, ``"allow_always"``, ``"reject_once"``).
        """
        self._on_permission_request = handler

    # ------------------------------------------------------------------
    # NDJSON I/O
    # ------------------------------------------------------------------

    def _stderr_loop(self) -> None:
        """Drain subprocess stderr to prevent pipe buffer deadlock."""
        assert self._proc and self._proc.stderr
        while self._running:
            try:
                line = self._proc.stderr.readline()
            except Exception:
                break
            if not line:
                break
            logger.debug("ACP ERR: %s", line.strip()[:300])

    def _next_id(self) -> int:
        with self._lock:
            self._msg_id += 1
            return self._msg_id

    def _send(self, method: str, params: dict[str, Any], msg_id: int) -> None:
        msg = json.dumps(
            {"jsonrpc": "2.0", "method": method, "params": params, "id": msg_id}
        )
        assert self._proc and self._proc.stdin
        self._proc.stdin.write((msg + "\n").encode("utf-8"))
        self._proc.stdin.flush()
        logger.debug("ACP >>> %s", msg[:300])

    def _read_loop(self) -> None:
        """Background thread: read NDJSON lines and dispatch."""
        assert self._proc and self._proc.stdout
        while self._running:
            try:
                raw = self._proc.stdout.readline()
            except Exception:
                break
            if not raw:
                break
            try:
                line = raw.decode("utf-8", errors="replace").strip()
            except Exception:
                continue
            if not line:
                continue
            logger.debug("ACP <<< %s", line[:300])
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                logger.warning("ACP: non-JSON line: %s", line[:200])
                continue

            msg_id = msg.get("id")
            method = msg.get("method")

            if msg_id is not None and msg_id in self._pending:
                # Response to a request we sent
                event, slot = self._pending[msg_id]
                slot.append(
                    ACPResponse(
                        id=msg_id,
                        result=msg.get("result"),
                        error=msg.get("error"),
                    )
                )
                event.set()
            elif method == "session/request_permission" and msg_id is not None:
                # Server-initiated request: permission approval needed
                self._handle_permission_request(msg_id, msg.get("params", {}))
            elif method is not None and msg_id is None:
                # Server-initiated notification (no response needed)
                if self._on_notification:
                    try:
                        self._on_notification(msg)
                    except Exception:
                        logger.exception("Notification handler error")
            elif method is not None and msg_id is not None:
                # Other server-initiated requests — not yet handled
                logger.warning("ACP: unhandled server request: %s (id=%s)", method, msg_id)
            else:
                logger.debug("ACP: unrouted message id=%s", msg_id)

    def _handle_permission_request(
        self, msg_id: int, params: dict[str, Any]
    ) -> None:
        """Handle a session/request_permission from the ACP server."""
        options = params.get("options", [])
        tool_call = params.get("toolCall", {})
        title = tool_call.get("title", "unknown action")

        option_id = "allow_once"  # default fallback

        if self._on_permission_request:
            try:
                option_id = self._on_permission_request(params)
            except Exception:
                logger.exception("Permission handler error, auto-allowing")
                option_id = "allow_once"
        else:
            # No handler registered — auto-allow
            logger.info(
                "Auto-allowing permission (no handler): %s", title
            )

        # Send response
        resp = json.dumps({
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {"optionId": option_id},
        })
        try:
            assert self._proc and self._proc.stdin
            self._proc.stdin.write((resp + "\n").encode("utf-8"))
            self._proc.stdin.flush()
            logger.debug("ACP >>> permission response: %s", resp[:200])
        except Exception:
            logger.exception("Failed to send permission response")

    # ------------------------------------------------------------------
    # Request helpers
    # ------------------------------------------------------------------

    def _request(
        self, method: str, params: dict[str, Any], timeout: float = 30.0
    ) -> ACPResponse:
        """Send a JSON-RPC request and wait for the response."""
        if not self.alive:
            raise RuntimeError("Copilot ACP process is not running")

        msg_id = self._next_id()
        event = threading.Event()
        slot: list[ACPResponse] = []
        self._pending[msg_id] = (event, slot)
        try:
            self._send(method, params, msg_id)
            if not event.wait(timeout=timeout):
                raise TimeoutError(
                    f"ACP request {method} (id={msg_id}) timed out after {timeout}s"
                )
            return slot[0]
        finally:
            self._pending.pop(msg_id, None)

    # ------------------------------------------------------------------
    # ACP protocol methods
    # ------------------------------------------------------------------

    def initialize(self) -> dict[str, Any]:
        """Send ACP initialize handshake. Returns agentCapabilities."""
        resp = self._request(
            "initialize",
            {"protocolVersion": ACP_PROTOCOL_VERSION, "clientCapabilities": {}},
        )
        if not resp.ok:
            raise RuntimeError(f"ACP initialize failed: {resp.error}")
        return resp.result or {}

    def new_session(
        self,
        cwd: str,
        mcp_servers: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Create a new Copilot session. Returns sessionId, models, modes."""
        resp = self._request(
            "session/new",
            {"cwd": cwd, "mcpServers": mcp_servers or []},
            timeout=30.0,
        )
        if not resp.ok:
            raise RuntimeError(f"ACP session/new failed: {resp.error}")
        return resp.result or {}

    def prompt(
        self,
        session_id: str,
        text: str,
        timeout: float = 300.0,
        on_chunk: Callable[[str], None] | None = None,
    ) -> PromptResult:
        """Send a prompt and collect the streamed response.

        ``on_chunk`` is called with each text fragment as it arrives.
        The full text is also returned in the :class:`PromptResult`.
        """
        chunks: list[str] = []
        raw_chunks: list[dict[str, Any]] = []

        def _handle_notification(msg: dict[str, Any]) -> None:
            params = msg.get("params", {})
            if params.get("sessionId") != session_id:
                return
            update = params.get("update", {})
            if update.get("sessionUpdate") == "agent_message_chunk":
                content = update.get("content", {})
                if content.get("type") == "text":
                    text_chunk = content["text"]
                    chunks.append(text_chunk)
                    raw_chunks.append(update)
                    if on_chunk:
                        on_chunk(text_chunk)

        prev_handler = self._on_notification
        self._on_notification = _handle_notification
        try:
            resp = self._request(
                "session/prompt",
                {
                    "sessionId": session_id,
                    "prompt": [{"type": "text", "text": text}],
                },
                timeout=timeout,
            )
        finally:
            self._on_notification = prev_handler

        if not resp.ok:
            raise RuntimeError(f"ACP session/prompt failed: {resp.error}")

        result = resp.result or {}
        return PromptResult(
            text="".join(chunks),
            stop_reason=result.get("stopReason", "unknown"),
            raw_chunks=raw_chunks,
        )

    def list_sessions(self) -> list[dict[str, Any]]:
        """List available sessions (if supported)."""
        resp = self._request("session/list", {}, timeout=10.0)
        if not resp.ok:
            raise RuntimeError(f"ACP session/list failed: {resp.error}")
        return (resp.result or {}).get("sessions", [])

    def load_session(
        self,
        session_id: str,
        cwd: str,
        mcp_servers: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Reload a previous session.

        Args:
            session_id: The session ID to reload.
            cwd: Working directory (required by ACP).
            mcp_servers: Optional MCP server configurations.
        """
        resp = self._request(
            "session/load",
            {
                "sessionId": session_id,
                "cwd": cwd,
                "mcpServers": mcp_servers or [],
            },
            timeout=15.0,
        )
        if not resp.ok:
            raise RuntimeError(f"ACP session/load failed: {resp.error}")
        return resp.result or {}
