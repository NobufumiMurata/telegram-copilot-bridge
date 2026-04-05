"""Tests for session manager."""

from unittest.mock import MagicMock, patch

import pytest

from telegram_copilot_bridge.session_manager import SessionManager, Session


def _mock_copilot_process():
    """Create a mock CopilotProcess that returns predictable results."""
    mock = MagicMock()
    mock.alive = True
    mock.initialize.return_value = {"agentCapabilities": {}}
    mock.new_session.return_value = {
        "sessionId": "sess-aaa-111",
        "models": {"currentModelId": "claude-sonnet-4.6"},
        "modes": {
            "currentModeId": "https://agentclientprotocol.com/protocol/session-modes#agent"
        },
    }
    mock.prompt.return_value = MagicMock(
        text="Hello!", stop_reason="end_turn", raw_chunks=[]
    )
    return mock


class TestSessionManager:
    @patch("telegram_copilot_bridge.session_manager._find_copilot", return_value="copilot")
    @patch("telegram_copilot_bridge.session_manager.CopilotProcess")
    def test_create_session(self, MockCP, mock_find):
        mock_proc = _mock_copilot_process()
        MockCP.return_value = mock_proc

        mgr = SessionManager()
        session = mgr.create_session("/tmp/project")

        assert session.id == "sess-aaa-111"
        assert session.cwd == "/tmp/project"
        assert session.model == "claude-sonnet-4.6"
        assert session.mode == "agent"
        assert mgr.active_session == session
        mock_proc.start.assert_called_once()
        mock_proc.initialize.assert_called_once()

    @patch("telegram_copilot_bridge.session_manager._find_copilot", return_value="copilot")
    @patch("telegram_copilot_bridge.session_manager.CopilotProcess")
    def test_stop_session(self, MockCP, mock_find):
        mock_proc = _mock_copilot_process()
        MockCP.return_value = mock_proc

        mgr = SessionManager()
        mgr.create_session("/tmp/project")
        mgr.stop_session()

        assert mgr.active_session is None
        mock_proc.stop.assert_called_once()

    @patch("telegram_copilot_bridge.session_manager._find_copilot", return_value="copilot")
    @patch("telegram_copilot_bridge.session_manager.CopilotProcess")
    def test_switch_session(self, MockCP, mock_find):
        proc1 = _mock_copilot_process()
        proc1.new_session.return_value = {
            "sessionId": "sess-111",
            "models": {"currentModelId": "m1"},
            "modes": {"currentModeId": "#agent"},
        }
        proc2 = _mock_copilot_process()
        proc2.new_session.return_value = {
            "sessionId": "sess-222",
            "models": {"currentModelId": "m2"},
            "modes": {"currentModeId": "#agent"},
        }
        MockCP.side_effect = [proc1, proc2]

        mgr = SessionManager()
        mgr.create_session("/tmp/a")
        mgr.create_session("/tmp/b")

        assert mgr.active_session.id == "sess-222"
        mgr.switch_session("sess-111")
        assert mgr.active_session.id == "sess-111"

    @patch("telegram_copilot_bridge.session_manager._find_copilot", return_value="copilot")
    @patch("telegram_copilot_bridge.session_manager.CopilotProcess")
    def test_switch_session_prefix(self, MockCP, mock_find):
        mock_proc = _mock_copilot_process()
        MockCP.return_value = mock_proc

        mgr = SessionManager()
        mgr.create_session("/tmp/project")
        session = mgr.switch_session("sess-aaa")
        assert session.id == "sess-aaa-111"

    @patch("telegram_copilot_bridge.session_manager._find_copilot", return_value="copilot")
    @patch("telegram_copilot_bridge.session_manager.CopilotProcess")
    def test_switch_session_not_found(self, MockCP, mock_find):
        mgr = SessionManager()
        with pytest.raises(ValueError, match="not found"):
            mgr.switch_session("nonexistent")

    @patch("telegram_copilot_bridge.session_manager._find_copilot", return_value="copilot")
    @patch("telegram_copilot_bridge.session_manager.CopilotProcess")
    def test_list_sessions(self, MockCP, mock_find):
        mock_proc = _mock_copilot_process()
        MockCP.return_value = mock_proc

        mgr = SessionManager()
        mgr.create_session("/tmp/project")
        sessions = mgr.list_sessions()
        assert len(sessions) == 1
        assert sessions[0].id == "sess-aaa-111"

    @patch("telegram_copilot_bridge.session_manager._find_copilot", return_value="copilot")
    @patch("telegram_copilot_bridge.session_manager.CopilotProcess")
    def test_send_prompt(self, MockCP, mock_find):
        mock_proc = _mock_copilot_process()
        MockCP.return_value = mock_proc

        mgr = SessionManager()
        mgr.create_session("/tmp/project")
        result = mgr.send_prompt("Hello")
        assert result.text == "Hello!"

    def test_send_prompt_no_session(self):
        mgr = SessionManager.__new__(SessionManager)
        mgr._sessions = {}
        mgr._processes = {}
        mgr._active_session_id = None
        with pytest.raises(ValueError, match="No active session"):
            mgr.send_prompt("test")

    @patch("telegram_copilot_bridge.session_manager._find_copilot", return_value="copilot")
    @patch("telegram_copilot_bridge.session_manager.CopilotProcess")
    def test_allowed_dirs_rejects(self, MockCP, mock_find):
        mgr = SessionManager(allowed_dirs=["/safe/dir"])
        with pytest.raises(ValueError, match="not allowed"):
            mgr.create_session("/dangerous/dir")

    @patch("telegram_copilot_bridge.session_manager._find_copilot", return_value="copilot")
    @patch("telegram_copilot_bridge.session_manager.CopilotProcess")
    def test_allowed_dirs_accepts(self, MockCP, mock_find):
        mock_proc = _mock_copilot_process()
        MockCP.return_value = mock_proc

        mgr = SessionManager(allowed_dirs=["/safe/dir"])
        session = mgr.create_session("/safe/dir/project")
        assert session.id == "sess-aaa-111"

    @patch("telegram_copilot_bridge.session_manager._find_copilot", return_value="copilot")
    @patch("telegram_copilot_bridge.session_manager.CopilotProcess")
    def test_get_status(self, MockCP, mock_find):
        mock_proc = _mock_copilot_process()
        MockCP.return_value = mock_proc

        mgr = SessionManager()
        mgr.create_session("/tmp/project")
        status = mgr.get_status()
        assert "sess-aaa" in status
        assert "claude-sonnet" in status

    @patch("telegram_copilot_bridge.session_manager._find_copilot", return_value="copilot")
    @patch("telegram_copilot_bridge.session_manager.CopilotProcess")
    def test_stop_all(self, MockCP, mock_find):
        proc1 = _mock_copilot_process()
        proc1.new_session.return_value = {
            "sessionId": "s1",
            "models": {"currentModelId": "m"},
            "modes": {"currentModeId": "#a"},
        }
        proc2 = _mock_copilot_process()
        proc2.new_session.return_value = {
            "sessionId": "s2",
            "models": {"currentModelId": "m"},
            "modes": {"currentModeId": "#a"},
        }
        MockCP.side_effect = [proc1, proc2]

        mgr = SessionManager()
        mgr.create_session("/a")
        mgr.create_session("/b")
        mgr.stop_all()

        assert len(mgr.list_sessions()) == 0
        assert mgr.active_session is None
