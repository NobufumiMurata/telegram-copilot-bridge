"""Tests for session manager."""

from unittest.mock import MagicMock, patch

import pytest

from telegram_copilot_bridge.session_manager import SessionManager, Session, SessionState


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
        assert "Idle" in status

    @patch("telegram_copilot_bridge.session_manager._find_copilot", return_value="copilot")
    @patch("telegram_copilot_bridge.session_manager.CopilotProcess")
    def test_send_prompt_sets_state(self, MockCP, mock_find):
        """send_prompt transitions state: idle → processing → idle."""
        mock_proc = _mock_copilot_process()
        MockCP.return_value = mock_proc

        mgr = SessionManager()
        session = mgr.create_session("/tmp/project")
        assert session.state == SessionState.IDLE

        # Track state during prompt
        states_during: list[str] = []

        def capture_state(*args, **kwargs):
            states_during.append(session.state)
            return mock_proc.prompt.return_value

        mock_proc.prompt.side_effect = capture_state

        mgr.send_prompt("Hello")
        assert SessionState.PROCESSING in states_during
        assert session.state == SessionState.IDLE

    @patch("telegram_copilot_bridge.session_manager._find_copilot", return_value="copilot")
    @patch("telegram_copilot_bridge.session_manager.CopilotProcess")
    def test_send_prompt_resets_state_on_error(self, MockCP, mock_find):
        """State returns to idle even if prompt raises."""
        mock_proc = _mock_copilot_process()
        mock_proc.prompt.side_effect = RuntimeError("boom")
        MockCP.return_value = mock_proc

        mgr = SessionManager()
        session = mgr.create_session("/tmp/project")
        with pytest.raises(RuntimeError):
            mgr.send_prompt("Hello")
        assert session.state == SessionState.IDLE

    @patch("telegram_copilot_bridge.session_manager._find_copilot", return_value="copilot")
    @patch("telegram_copilot_bridge.session_manager.CopilotProcess")
    def test_set_session_state(self, MockCP, mock_find):
        mock_proc = _mock_copilot_process()
        MockCP.return_value = mock_proc

        mgr = SessionManager()
        session = mgr.create_session("/tmp/project")
        assert session.state == SessionState.IDLE

        mgr.set_session_state(SessionState.PERMISSION_PENDING)
        assert session.state == SessionState.PERMISSION_PENDING

        mgr.set_session_state(SessionState.IDLE)
        assert session.state == SessionState.IDLE

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
                "updatedAt": "2026-04-04T12:00:00.000Z",
            },
            {
                "sessionId": "ext-bbb",
                "cwd": "/tmp/b",
                "title": "Another",
                "updatedAt": "2026-04-05T01:00:00.000Z",
            },
        ]
        MockCP.return_value = discover_proc

        mgr = SessionManager()
        text, sessions = mgr.get_history_data()
        # Default limit=3, both returned; sorted newest first
        assert "latest 2/2" in text
        assert len(sessions) == 2
        assert sessions[0]["sessionId"] == "ext-bbb"  # newer
        assert sessions[1]["sessionId"] == "ext-aaa"

    @patch("telegram_copilot_bridge.session_manager._find_copilot", return_value="copilot")
    @patch("telegram_copilot_bridge.session_manager.CopilotProcess")
    def test_get_history_data_with_limit(self, MockCP, mock_find):
        discover_proc = _mock_copilot_process()
        discover_proc.list_sessions.return_value = [
            {"sessionId": "s1", "cwd": "/a", "title": "A", "updatedAt": "2026-04-01T00:00:00Z"},
            {"sessionId": "s2", "cwd": "/b", "title": "B", "updatedAt": "2026-04-03T00:00:00Z"},
            {"sessionId": "s3", "cwd": "/c", "title": "C", "updatedAt": "2026-04-02T00:00:00Z"},
        ]
        MockCP.return_value = discover_proc

        mgr = SessionManager()
        text, sessions = mgr.get_history_data(limit=2)
        assert len(sessions) == 2
        assert sessions[0]["sessionId"] == "s2"  # newest
        assert sessions[1]["sessionId"] == "s3"
        assert "1 more" in text

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

    def test_get_last_response_from_events(self, tmp_path):
        """get_last_response reads the last assistant.message from events.jsonl."""
        import json as json_mod

        session_id = "test-session-123"
        session_dir = tmp_path / ".copilot" / "session-state" / session_id
        session_dir.mkdir(parents=True)
        events_file = session_dir / "events.jsonl"
        events_file.write_text(
            json_mod.dumps({"type": "user.message", "data": {"content": "Hello"}}) + "\n"
            + json_mod.dumps({"type": "assistant.message", "data": {"content": "First response"}}) + "\n"
            + json_mod.dumps({"type": "assistant.turn_end", "data": {}}) + "\n"
            + json_mod.dumps({"type": "assistant.message", "data": {"content": "Second response"}}) + "\n",
            encoding="utf-8",
        )

        mgr = SessionManager()
        mgr._active_session_id = session_id

        with patch("pathlib.Path.home", return_value=tmp_path):
            result = mgr.get_last_response()
        assert result == "Second response"

    def test_get_last_response_no_events(self):
        """get_last_response returns None when no events.jsonl exists."""
        mgr = SessionManager()
        mgr._active_session_id = "nonexistent-session"
        result = mgr.get_last_response()
        assert result is None

    def test_get_last_response_no_session(self):
        """get_last_response returns None when no active session."""
        mgr = SessionManager()
        result = mgr.get_last_response()
        assert result is None

    @patch("telegram_copilot_bridge.session_manager._find_copilot", return_value="copilot")
    @patch("telegram_copilot_bridge.session_manager.CopilotProcess")
    def test_permission_handler_passed_to_process(self, MockCP, mock_find):
        """Permission handler is registered on new CopilotProcess instances."""
        mock_proc = _mock_copilot_process()
        MockCP.return_value = mock_proc

        handler = lambda params: "allow_once"
        mgr = SessionManager(permission_handler=handler)
        mgr.create_session("/tmp/project")

        mock_proc.set_permission_handler.assert_called_once_with(handler)

    @patch("telegram_copilot_bridge.session_manager._find_copilot", return_value="copilot")
    @patch("telegram_copilot_bridge.session_manager.CopilotProcess")
    def test_no_permission_handler_when_none(self, MockCP, mock_find):
        """No handler is set when permission_handler is None."""
        mock_proc = _mock_copilot_process()
        MockCP.return_value = mock_proc

        mgr = SessionManager(permission_handler=None)
        mgr.create_session("/tmp/project")

        mock_proc.set_permission_handler.assert_not_called()

    @patch("telegram_copilot_bridge.session_manager._find_copilot", return_value="copilot")
    @patch("telegram_copilot_bridge.session_manager.CopilotProcess")
    def test_autopilot_flag_passed_to_process(self, MockCP, mock_find):
        """Autopilot flag is forwarded to CopilotProcess."""
        mock_proc = _mock_copilot_process()
        MockCP.return_value = mock_proc

        mgr = SessionManager(autopilot=True)
        mgr.create_session("/tmp/project")

        MockCP.assert_called_once_with(
            copilot_cmd="copilot",
            allowed_tools=None,
            model=None,
            autopilot=True,
        )

    @patch("telegram_copilot_bridge.session_manager._find_copilot", return_value="copilot")
    @patch("telegram_copilot_bridge.session_manager.CopilotProcess")
    def test_permission_handler_on_resume(self, MockCP, mock_find):
        """Permission handler is registered on resumed session processes."""
        discover_proc = _mock_copilot_process()
        discover_proc.list_sessions.return_value = [
            {"sessionId": "ext-aaa-111", "cwd": "/tmp/ext", "title": "Old"},
        ]
        resume_proc = _mock_copilot_process()
        resume_proc.load_session.return_value = {
            "models": {"currentModelId": "opus"},
            "modes": {"currentModeId": "#agent"},
        }
        MockCP.side_effect = [discover_proc, resume_proc]

        handler = lambda params: "reject_once"
        mgr = SessionManager(permission_handler=handler)
        mgr.resume_session("ext-aaa")

        resume_proc.set_permission_handler.assert_called_once_with(handler)

    @patch("telegram_copilot_bridge.session_manager._find_copilot", return_value="copilot")
    @patch("telegram_copilot_bridge.session_manager.CopilotProcess")
    def test_autopilot_toggle(self, MockCP, mock_find):
        """Autopilot property can be toggled."""
        mgr = SessionManager(autopilot=False)
        assert mgr.autopilot is False

        mgr.autopilot = True
        assert mgr.autopilot is True
