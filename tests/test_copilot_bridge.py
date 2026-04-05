"""Tests for Copilot CLI ACP bridge."""

import json
import threading
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

from telegram_copilot_bridge.copilot_bridge import (
    ACPResponse,
    CopilotProcess,
    PromptResult,
    ACP_PROTOCOL_VERSION,
)


class TestACPResponse:
    def test_ok_when_no_error(self):
        r = ACPResponse(id=1, result={"foo": "bar"})
        assert r.ok is True

    def test_not_ok_when_error(self):
        r = ACPResponse(id=1, error={"code": -1, "message": "fail"})
        assert r.ok is False


class TestCopilotProcess:
    def _make_process(self):
        proc = CopilotProcess.__new__(CopilotProcess)
        proc._cmd = "copilot"
        proc._allowed_tools = ["read"]
        proc._proc = None
        proc._msg_id = 0
        proc._lock = threading.Lock()
        proc._pending = {}
        proc._on_notification = None
        proc._reader_thread = None
        proc._running = False
        return proc

    def test_alive_false_when_no_proc(self):
        proc = self._make_process()
        assert proc.alive is False

    def test_next_id_increments(self):
        proc = self._make_process()
        assert proc._next_id() == 1
        assert proc._next_id() == 2

    def test_request_raises_when_not_running(self):
        proc = self._make_process()
        with pytest.raises(RuntimeError, match="not running"):
            proc._request("test", {})

    def test_initialize_sends_correct_message(self):
        proc = self._make_process()
        proc._running = True
        mock_popen = MagicMock()
        mock_popen.poll.return_value = None
        proc._proc = mock_popen

        # Simulate response in a thread
        response = ACPResponse(
            id=1,
            result={
                "protocolVersion": 1,
                "agentCapabilities": {},
                "agentInfo": {"name": "Copilot"},
            },
        )

        def fake_request(method, params, timeout=30.0):
            assert method == "initialize"
            assert params["protocolVersion"] == ACP_PROTOCOL_VERSION
            return response

        proc._request = fake_request
        result = proc.initialize()
        assert result["agentInfo"]["name"] == "Copilot"

    def test_new_session_returns_session_id(self):
        proc = self._make_process()
        response = ACPResponse(
            id=2,
            result={"sessionId": "abc-123", "models": {}, "modes": {}},
        )
        proc._request = lambda method, params, timeout=30.0: response
        result = proc.new_session("/tmp/project")
        assert result["sessionId"] == "abc-123"

    def test_new_session_raises_on_error(self):
        proc = self._make_process()
        response = ACPResponse(id=2, error={"code": -1, "message": "fail"})
        proc._request = lambda method, params, timeout=30.0: response
        with pytest.raises(RuntimeError, match="session/new failed"):
            proc.new_session("/tmp/project")

    def test_prompt_collects_chunks(self):
        proc = self._make_process()
        proc._running = True
        mock_popen = MagicMock()
        mock_popen.poll.return_value = None
        proc._proc = mock_popen

        collected_chunks = []

        def fake_request(method, params, timeout=300.0):
            # Simulate notification handler being called
            handler = proc._on_notification
            if handler:
                handler({
                    "jsonrpc": "2.0",
                    "method": "session/update",
                    "params": {
                        "sessionId": "sess-1",
                        "update": {
                            "sessionUpdate": "agent_message_chunk",
                            "content": {"type": "text", "text": "Hello "},
                        },
                    },
                })
                handler({
                    "jsonrpc": "2.0",
                    "method": "session/update",
                    "params": {
                        "sessionId": "sess-1",
                        "update": {
                            "sessionUpdate": "agent_message_chunk",
                            "content": {"type": "text", "text": "World!"},
                        },
                    },
                })
            return ACPResponse(id=3, result={"stopReason": "end_turn"})

        proc._request = fake_request
        result = proc.prompt(
            "sess-1", "Say hello", on_chunk=collected_chunks.append
        )
        assert result.text == "Hello World!"
        assert result.last_turn_text == "Hello World!"
        assert result.stop_reason == "end_turn"
        assert collected_chunks == ["Hello ", "World!"]

    def test_prompt_last_turn_text_after_tool_call(self):
        """last_turn_text should contain only text after the last tool_call."""
        proc = self._make_process()
        proc._running = True
        mock_popen = MagicMock()
        mock_popen.poll.return_value = None
        proc._proc = mock_popen

        def fake_request(method, params, timeout=300.0):
            handler = proc._on_notification
            if handler:
                # First turn: planning text
                handler({
                    "jsonrpc": "2.0",
                    "method": "session/update",
                    "params": {
                        "sessionId": "sess-1",
                        "update": {
                            "sessionUpdate": "agent_message_chunk",
                            "content": {"type": "text", "text": "Let me read the file..."},
                        },
                    },
                })
                # Tool call boundary
                handler({
                    "jsonrpc": "2.0",
                    "method": "session/update",
                    "params": {
                        "sessionId": "sess-1",
                        "update": {
                            "sessionUpdate": "tool_call",
                            "toolCall": {"title": "Read file"},
                        },
                    },
                })
                # Final turn: actual answer
                handler({
                    "jsonrpc": "2.0",
                    "method": "session/update",
                    "params": {
                        "sessionId": "sess-1",
                        "update": {
                            "sessionUpdate": "agent_message_chunk",
                            "content": {"type": "text", "text": "Here is the answer."},
                        },
                    },
                })
            return ACPResponse(id=3, result={"stopReason": "end_turn"})

        proc._request = fake_request
        result = proc.prompt("sess-1", "Explain the code")
        assert result.text == "Let me read the file...Here is the answer."
        assert result.last_turn_text == "Here is the answer."

    def test_prompt_ignores_other_sessions(self):
        proc = self._make_process()
        proc._running = True

        def fake_request(method, params, timeout=300.0):
            handler = proc._on_notification
            if handler:
                # Notification for a different session
                handler({
                    "jsonrpc": "2.0",
                    "method": "session/update",
                    "params": {
                        "sessionId": "other-session",
                        "update": {
                            "sessionUpdate": "agent_message_chunk",
                            "content": {"type": "text", "text": "wrong"},
                        },
                    },
                })
            return ACPResponse(id=3, result={"stopReason": "end_turn"})

        proc._request = fake_request
        result = proc.prompt("sess-1", "test")
        assert result.text == ""

    def test_set_notification_handler(self):
        proc = self._make_process()
        handler = MagicMock()
        proc.set_notification_handler(handler)
        assert proc._on_notification is handler

    def test_set_permission_handler(self):
        proc = self._make_process()
        handler = MagicMock(return_value="allow_once")
        proc.set_permission_handler(handler)
        assert proc._on_permission_request is handler

    def test_list_sessions(self):
        proc = self._make_process()
        response = ACPResponse(
            id=5, result={"sessions": [{"id": "s1"}, {"id": "s2"}]}
        )
        proc._request = lambda method, params, timeout=10.0: response
        sessions = proc.list_sessions()
        assert len(sessions) == 2


class TestPermissionHandling:
    """Tests for ACP session/request_permission handling."""

    def _make_process(self):
        proc = CopilotProcess.__new__(CopilotProcess)
        proc._cmd = "copilot"
        proc._allowed_tools = ["read"]
        proc._autopilot = False
        proc._proc = None
        proc._msg_id = 0
        proc._lock = threading.Lock()
        proc._pending = {}
        proc._on_notification = None
        proc._on_permission_request = None
        proc._reader_thread = None
        proc._running = False
        return proc

    def test_handle_permission_auto_allows_without_handler(self):
        """Without a permission handler, defaults to allow_once."""
        proc = self._make_process()
        proc._running = True
        mock_popen = MagicMock()
        mock_popen.poll.return_value = None
        mock_popen.stdin = MagicMock()
        proc._proc = mock_popen

        proc._handle_permission_request(42, {
            "toolCall": {"title": "Run bash command"},
            "options": [
                {"optionId": "allow_once", "name": "Allow once"},
                {"optionId": "reject_once", "name": "Deny"},
            ],
        })

        # Should have written a response to stdin
        mock_popen.stdin.write.assert_called_once()
        written = mock_popen.stdin.write.call_args[0][0]
        response = json.loads(written.decode("utf-8"))
        assert response["id"] == 42
        assert response["result"]["optionId"] == "allow_once"

    def test_handle_permission_calls_handler(self):
        """When a handler is registered, it's called and its result is used."""
        proc = self._make_process()
        proc._running = True
        mock_popen = MagicMock()
        mock_popen.poll.return_value = None
        mock_popen.stdin = MagicMock()
        proc._proc = mock_popen

        handler = MagicMock(return_value="allow_always")
        proc.set_permission_handler(handler)

        params = {
            "toolCall": {"title": "Edit file"},
            "options": [
                {"optionId": "allow_once", "name": "Allow once"},
                {"optionId": "allow_always", "name": "Always allow"},
                {"optionId": "reject_once", "name": "Deny"},
            ],
        }
        proc._handle_permission_request(99, params)

        handler.assert_called_once_with(params)
        written = mock_popen.stdin.write.call_args[0][0]
        response = json.loads(written.decode("utf-8"))
        assert response["id"] == 99
        assert response["result"]["optionId"] == "allow_always"

    def test_handle_permission_handler_error_falls_back_to_allow(self):
        """If the handler raises, falls back to allow_once."""
        proc = self._make_process()
        proc._running = True
        mock_popen = MagicMock()
        mock_popen.stdin = MagicMock()
        proc._proc = mock_popen

        handler = MagicMock(side_effect=RuntimeError("callback error"))
        proc.set_permission_handler(handler)

        proc._handle_permission_request(10, {
            "toolCall": {"title": "dangerous op"},
            "options": [],
        })

        written = mock_popen.stdin.write.call_args[0][0]
        response = json.loads(written.decode("utf-8"))
        assert response["result"]["optionId"] == "allow_once"

    def test_handle_permission_sends_valid_jsonrpc(self):
        """Response must be valid JSON-RPC 2.0."""
        proc = self._make_process()
        proc._running = True
        mock_popen = MagicMock()
        mock_popen.stdin = MagicMock()
        proc._proc = mock_popen

        proc._handle_permission_request(7, {
            "toolCall": {"title": "test"},
            "options": [],
        })

        written = mock_popen.stdin.write.call_args[0][0]
        response = json.loads(written.decode("utf-8"))
        assert response["jsonrpc"] == "2.0"
        assert response["id"] == 7
        assert "result" in response

    def test_handle_permission_stdin_error_does_not_raise(self):
        """If writing to stdin fails, should not propagate the exception."""
        proc = self._make_process()
        proc._running = True
        mock_popen = MagicMock()
        mock_popen.stdin = MagicMock()
        mock_popen.stdin.write.side_effect = BrokenPipeError("pipe closed")
        proc._proc = mock_popen

        # Should not raise
        proc._handle_permission_request(1, {
            "toolCall": {"title": "test"},
            "options": [],
        })

    def test_read_loop_dispatches_permission_request(self):
        """_read_loop routes session/request_permission to the handler."""
        proc = self._make_process()
        proc._running = True

        handler = MagicMock(return_value="reject_once")
        proc.set_permission_handler(handler)

        # Prepare a mock subprocess with permission request + EOF
        permission_msg = json.dumps({
            "jsonrpc": "2.0",
            "id": 50,
            "method": "session/request_permission",
            "params": {
                "toolCall": {"title": "Run bash"},
                "options": [{"optionId": "allow_once", "name": "Allow"}],
            },
        })

        mock_popen = MagicMock()
        mock_popen.stdin = MagicMock()
        mock_popen.stdout = MagicMock()
        mock_popen.stdout.readline = MagicMock(
            side_effect=[
                (permission_msg + "\n").encode("utf-8"),
                b"",  # EOF — stops loop
            ]
        )
        proc._proc = mock_popen

        proc._read_loop()

        handler.assert_called_once()
        handler_params = handler.call_args[0][0]
        assert handler_params["toolCall"]["title"] == "Run bash"

        # Verify response was written
        written = mock_popen.stdin.write.call_args[0][0]
        response = json.loads(written.decode("utf-8"))
        assert response["id"] == 50
        assert response["result"]["optionId"] == "reject_once"

    def test_read_loop_permission_not_confused_with_pending(self):
        """Permission requests use server-generated IDs, not in _pending."""
        proc = self._make_process()
        proc._running = True

        # Register a pending request with a different id
        event = threading.Event()
        proc._pending[99] = (event, [])

        permission_msg = json.dumps({
            "jsonrpc": "2.0",
            "id": 50,
            "method": "session/request_permission",
            "params": {"toolCall": {"title": "test"}, "options": []},
        })

        mock_popen = MagicMock()
        mock_popen.stdin = MagicMock()
        mock_popen.stdout = MagicMock()
        mock_popen.stdout.readline = MagicMock(
            side_effect=[
                (permission_msg + "\n").encode("utf-8"),
                b"",
            ]
        )
        proc._proc = mock_popen

        proc._read_loop()

        # Permission response was sent (not routed to pending)
        written = mock_popen.stdin.write.call_args[0][0]
        response = json.loads(written.decode("utf-8"))
        assert response["id"] == 50
        # The pending[99] slot is untouched
        assert len(proc._pending[99][1]) == 0

    def test_start_autopilot_flags(self):
        """Autopilot mode adds --no-ask-user and --autopilot flags."""
        proc = CopilotProcess(copilot_cmd="copilot", autopilot=True)
        with patch("subprocess.Popen") as mock_popen:
            mock_popen.return_value = MagicMock()
            mock_popen.return_value.poll.return_value = None
            mock_popen.return_value.stdout = MagicMock()
            proc.start()
            cmd_args = mock_popen.call_args[0][0]
            assert "--no-ask-user" in cmd_args
            assert "--autopilot" in cmd_args
            proc.stop()

    def test_start_no_autopilot_flags(self):
        """Non-autopilot mode does not include --no-ask-user / --autopilot."""
        proc = CopilotProcess(copilot_cmd="copilot", autopilot=False)
        with patch("subprocess.Popen") as mock_popen:
            mock_popen.return_value = MagicMock()
            mock_popen.return_value.poll.return_value = None
            mock_popen.return_value.stdout = MagicMock()
            proc.start()
            cmd_args = mock_popen.call_args[0][0]
            assert "--no-ask-user" not in cmd_args
            assert "--autopilot" not in cmd_args
            proc.stop()
