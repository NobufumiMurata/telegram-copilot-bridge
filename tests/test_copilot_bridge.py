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
        assert result.stop_reason == "end_turn"
        assert collected_chunks == ["Hello ", "World!"]

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

    def test_list_sessions(self):
        proc = self._make_process()
        response = ACPResponse(
            id=5, result={"sessions": [{"id": "s1"}, {"id": "s2"}]}
        )
        proc._request = lambda method, params, timeout=10.0: response
        sessions = proc.list_sessions()
        assert len(sessions) == 2
