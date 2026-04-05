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

    @patch("telegram_copilot_bridge.session_manager._find_copilot", return_value="copilot")
    @patch("telegram_copilot_bridge.session_manager.CopilotProcess")
    def test_discover_sessions(self, MockCP, mock_find):
        mock_proc = _mock_copilot_process()
        mock_proc.list_sessions.return_value = [
            {"sessionId": "ext-aaa", "cwd": "/tmp/a", "title": "Old session"},
            {"sessionId": "ext-bbb", "cwd": "/tmp/b", "title": "Another old"},
        ]
        MockCP.return_value = mock_proc

        mgr = SessionManager()
        external = mgr.discover_sessions()
        assert len(external) == 2
        assert external[0]["sessionId"] == "ext-aaa"
        # Temp process should be stopped
        mock_proc.stop.assert_called_once()

    @patch("telegram_copilot_bridge.session_manager._find_copilot", return_value="copilot")
    @patch("telegram_copilot_bridge.session_manager.CopilotProcess")
    def test_discover_sessions_excludes_managed(self, MockCP, mock_find):
        mock_proc = _mock_copilot_process()
        # First call creates a managed session
        MockCP.return_value = mock_proc

        mgr = SessionManager()
        mgr.create_session("/tmp/project")

        # For discover, return a list that includes the managed session
        discover_proc = _mock_copilot_process()
        discover_proc.list_sessions.return_value = [
            {"sessionId": "sess-aaa-111", "cwd": "/tmp/project", "title": "managed"},
            {"sessionId": "ext-new", "cwd": "/tmp/other", "title": "external"},
        ]
        MockCP.return_value = discover_proc

        external = mgr.discover_sessions()
        assert len(external) == 1
        assert external[0]["sessionId"] == "ext-new"

    @patch("telegram_copilot_bridge.session_manager._find_copilot", return_value="copilot")
    @patch("telegram_copilot_bridge.session_manager.CopilotProcess")
    def test_resume_session(self, MockCP, mock_find):
        # First call is for discover, second for the resume process
        discover_proc = _mock_copilot_process()
        discover_proc.list_sessions.return_value = [
            {"sessionId": "ext-aaa-111", "cwd": "/tmp/ext", "title": "Old"},
        ]
        resume_proc = _mock_copilot_process()
        resume_proc.load_session.return_value = {
            "models": {"currentModelId": "claude-opus-4.6"},
            "modes": {"currentModeId": "#agent"},
        }
        MockCP.side_effect = [discover_proc, resume_proc]

        mgr = SessionManager()
        session = mgr.resume_session("ext-aaa")

        assert session.id == "ext-aaa-111"
        assert session.cwd == "/tmp/ext"
        assert session.model == "claude-opus-4.6"
        assert mgr.active_session == session
        resume_proc.load_session.assert_called_once_with(
            "ext-aaa-111", "/tmp/ext"
        )

    @patch("telegram_copilot_bridge.session_manager._find_copilot", return_value="copilot")
    @patch("telegram_copilot_bridge.session_manager.CopilotProcess")
    def test_resume_session_not_found(self, MockCP, mock_find):
        discover_proc = _mock_copilot_process()
        discover_proc.list_sessions.return_value = []
        MockCP.return_value = discover_proc

        mgr = SessionManager()
        with pytest.raises(ValueError, match="No persisted session"):
            mgr.resume_session("nonexistent")

    @patch("telegram_copilot_bridge.session_manager._find_copilot", return_value="copilot")
    @patch("telegram_copilot_bridge.session_manager.CopilotProcess")
    def test_get_history_report(self, MockCP, mock_find):
        discover_proc = _mock_copilot_process()
        discover_proc.list_sessions.return_value = [
            {
                "sessionId": "ext-aaa",
                "cwd": "/tmp/a",
                "title": "Old session",
                "updatedAt": "2026-04-05T01:00:00.000Z",
            },
        ]
        MockCP.return_value = discover_proc

        mgr = SessionManager()
        report = mgr.get_history_report()
        assert "Session History" in report
        assert "ext-aaa" in report
        assert "/resume" in report

    @patch("telegram_copilot_bridge.session_manager._find_copilot", return_value="copilot")
    @patch("telegram_copilot_bridge.session_manager.CopilotProcess")
    def test_get_history_data(self, MockCP, mock_find):
        discover_proc = _mock_copilot_process()
        discover_proc.list_sessions.return_value = [
            {
                "sessionId": "ext-aaa",
                "cwd": "/tmp/a",
                "title": "Old session",
                "updatedAt": "2026-04-05T01:00:00.000Z",
            },
            {
                "sessionId": "ext-bbb",
                "cwd": "/tmp/b",
                "title": "Another",
                "updatedAt": "2026-04-04T12:00:00.000Z",
            },
        ]
        MockCP.return_value = discover_proc

        mgr = SessionManager()
        text, sessions = mgr.get_history_data()
        assert "Session History (2)" in text
        assert "ext-aaa" in text
        assert len(sessions) == 2
        assert sessions[0]["sessionId"] == "ext-aaa"

    @patch("telegram_copilot_bridge.session_manager._find_copilot", return_value="copilot")
    @patch("telegram_copilot_bridge.session_manager.CopilotProcess")
    def test_get_history_data_empty(self, MockCP, mock_find):
        discover_proc = _mock_copilot_process()
        discover_proc.list_sessions.return_value = []
        MockCP.return_value = discover_proc

        mgr = SessionManager()
        text, sessions = mgr.get_history_data()
        assert "No persisted sessions" in text
        assert sessions == []
