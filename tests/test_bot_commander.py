"""Tests for BotCommander Telegram command router."""

import time
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

from telegram_copilot_bridge.bot_commander import BotCommander
from telegram_copilot_bridge.session_manager import Session


def _make_commander():
    mgr = MagicMock()
    tg = MagicMock()
    return BotCommander(session_mgr=mgr, telegram=tg, default_cwd="/tmp"), mgr, tg


def _wait_prompt_done(cmd, timeout=2.0):
    """Wait for the background prompt worker to finish."""
    deadline = time.time() + timeout
    while cmd._prompt_in_progress and time.time() < deadline:
        time.sleep(0.05)


class TestHandleCommands:
    def test_help_command(self):
        cmd, mgr, tg = _make_commander()
        result = cmd.handle("/help")
        assert result is None
        tg.send_message.assert_called_once()
        msg = tg.send_message.call_args[0][0]
        assert "/new" in msg
        assert "/done" in msg

    def test_new_command_default_cwd(self):
        cmd, mgr, tg = _make_commander()
        session = Session(id="abc-123", cwd="/tmp", model="claude", mode="agent")
        mgr.create_session.return_value = session

        result = cmd.handle("/new")
        assert result is None
        mgr.create_session.assert_called_once_with("/tmp")
        msg = tg.send_message.call_args[0][0]
        assert "abc-123" in msg

    def test_new_command_with_cwd(self):
        cmd, mgr, tg = _make_commander()
        session = Session(id="abc-123", cwd="/project", model="m", mode="a")
        mgr.create_session.return_value = session

        cmd.handle("/new /project")
        mgr.create_session.assert_called_once_with("/project")

    def test_new_command_error(self):
        cmd, mgr, tg = _make_commander()
        mgr.create_session.side_effect = FileNotFoundError("copilot not found")

        cmd.handle("/new")
        msg = tg.send_message.call_args[0][0]
        assert "copilot not found" in msg

    def test_list_command(self):
        cmd, mgr, tg = _make_commander()
        mgr.get_list_report.return_value = "📋 Sessions (1)"

        cmd.handle("/list")
        tg.send_message.assert_called_once()

    def test_switch_command(self):
        cmd, mgr, tg = _make_commander()
        session = Session(id="abc-123", cwd="/tmp", model="m", mode="a")
        mgr.switch_session.return_value = session

        cmd.handle("/switch abc")
        mgr.switch_session.assert_called_once_with("abc")
        msg = tg.send_message.call_args[0][0]
        assert "abc-123" in msg

    def test_switch_command_no_arg(self):
        cmd, mgr, tg = _make_commander()
        cmd.handle("/switch")
        msg = tg.send_message.call_args[0][0]
        assert "Usage" in msg

    def test_status_command(self):
        cmd, mgr, tg = _make_commander()
        mgr.get_status.return_value = "🤖 Session status"

        cmd.handle("/status")
        tg.send_message.assert_called_once()

    def test_stop_command(self):
        cmd, mgr, tg = _make_commander()
        cmd.handle("/stop")
        mgr.stop_session.assert_called_once_with(None)
        msg = tg.send_message.call_args[0][0]
        assert "stopped" in msg.lower()

    def test_stop_command_with_id(self):
        cmd, mgr, tg = _make_commander()
        cmd.handle("/stop abc-123")
        mgr.stop_session.assert_called_once_with("abc-123")

    def test_done_command(self):
        cmd, mgr, tg = _make_commander()
        result = cmd.handle("/done")
        assert result == "SESSION_END"
        mgr.stop_all.assert_called_once()

    def test_unknown_command(self):
        cmd, mgr, tg = _make_commander()
        cmd.handle("/foobar")
        msg = tg.send_message.call_args[0][0]
        assert "Unknown" in msg


class TestHistoryResume:
    def test_history_command(self):
        cmd, mgr, tg = _make_commander()
        sessions = [
            {"sessionId": "ext-aaa-111", "cwd": "/tmp/a", "title": "Old session"},
            {"sessionId": "ext-bbb-222", "cwd": "/tmp/b", "title": "Another"},
        ]
        mgr.get_history_data.return_value = ("📜 Session History (2)", sessions)

        cmd.handle("/history")
        mgr.get_history_data.assert_called_once_with(limit=3)
        tg.send_message.assert_called_once()
        tg.send_inline_keyboard.assert_called_once()
        text_arg = tg.send_inline_keyboard.call_args[0][0]
        buttons_arg = tg.send_inline_keyboard.call_args[0][1]
        assert "Session History" in text_arg
        assert len(buttons_arg) == 2
        assert buttons_arg[0][0]["callback_data"] == "resume:ext-aaa-"
        assert buttons_arg[1][0]["callback_data"] == "resume:ext-bbb-"

    def test_history_command_with_limit(self):
        cmd, mgr, tg = _make_commander()
        mgr.get_history_data.return_value = ("📜 Session History", [
            {"sessionId": "ext-aaa-111", "cwd": "/tmp/a", "title": "S1"},
        ])

        cmd.handle("/history 10")
        mgr.get_history_data.assert_called_once_with(limit=10)

    def test_history_command_no_sessions(self):
        cmd, mgr, tg = _make_commander()
        mgr.get_history_data.return_value = ("ℹ️ No persisted sessions found.", [])

        cmd.handle("/history")
        assert tg.send_message.call_count == 2  # "Discovering…" + no-sessions msg
        tg.send_inline_keyboard.assert_not_called()

    def test_resume_command(self):
        cmd, mgr, tg = _make_commander()
        session = Session(id="ext-aaa-111", cwd="/tmp/ext", model="opus", mode="agent")
        mgr.resume_session.return_value = session

        cmd.handle("/resume ext-aaa")
        mgr.resume_session.assert_called_once_with("ext-aaa")
        last_msg = tg.send_message.call_args_list[-1][0][0]
        assert "Resumed" in last_msg
        assert "ext-aaa" in last_msg

    def test_resume_no_arg(self):
        cmd, mgr, tg = _make_commander()
        cmd.handle("/resume")
        msg = tg.send_message.call_args[0][0]
        assert "Usage" in msg

    def test_resume_not_found(self):
        cmd, mgr, tg = _make_commander()
        mgr.resume_session.side_effect = ValueError("No persisted session matching 'xxx'")

        cmd.handle("/resume xxx")
        last_msg = tg.send_message.call_args_list[-1][0][0]
        assert "No persisted session" in last_msg

    def test_help_includes_history_resume(self):
        cmd, mgr, tg = _make_commander()
        cmd.handle("/help")
        msg = tg.send_message.call_args[0][0]
        assert "/history" in msg
        assert "/resume" in msg


class TestHandlePrompt:
    def test_prompt_no_session(self):
        cmd, mgr, tg = _make_commander()
        type(mgr).active_session = PropertyMock(return_value=None)

        cmd.handle("Fix the bug")
        msg = tg.send_message.call_args[0][0]
        assert "No active session" in msg

    def test_prompt_success(self):
        cmd, mgr, tg = _make_commander()
        session = Session(id="abc", cwd="/tmp", model="m", mode="a")
        type(mgr).active_session = PropertyMock(return_value=session)
        mgr.send_prompt.return_value = MagicMock(text="Done! Fixed the bug.")

        cmd.handle("Fix the bug")
        _wait_prompt_done(cmd)
        # Should have sent "Processing…" first, then the result
        assert tg.send_message.call_count == 2
        last_msg = tg.send_message.call_args_list[-1][0][0]
        assert "Fixed the bug" in last_msg

    def test_prompt_timeout(self):
        cmd, mgr, tg = _make_commander()
        session = Session(id="abc", cwd="/tmp", model="m", mode="a")
        type(mgr).active_session = PropertyMock(return_value=session)
        mgr.send_prompt.side_effect = TimeoutError("timed out")

        cmd.handle("Fix the bug")
        _wait_prompt_done(cmd)
        last_msg = tg.send_message.call_args_list[-1][0][0]
        assert "timed out" in last_msg.lower()

    def test_prompt_error(self):
        cmd, mgr, tg = _make_commander()
        session = Session(id="abc", cwd="/tmp", model="m", mode="a")
        type(mgr).active_session = PropertyMock(return_value=session)
        mgr.send_prompt.side_effect = RuntimeError("process died")

        cmd.handle("Fix the bug")
        _wait_prompt_done(cmd)
        last_msg = tg.send_message.call_args_list[-1][0][0]
        assert "process died" in last_msg


class TestLongMessage:
    def test_short_message_not_split(self):
        cmd, mgr, tg = _make_commander()
        cmd._send_long_message("short text")
        tg.send_message.assert_called_once_with("short text")

    def test_long_message_split(self):
        cmd, mgr, tg = _make_commander()
        # Create a message that's over 4000 chars
        long_text = "\n".join(f"Line {i}: {'x' * 50}" for i in range(100))
        assert len(long_text) > 4000

        cmd._send_long_message(long_text)
        assert tg.send_message.call_count > 1
        # Each chunk should have a part indicator
        first_msg = tg.send_message.call_args_list[0][0][0]
        assert "[1/" in first_msg


class TestHandleEmpty:
    def test_empty_text(self):
        cmd, mgr, tg = _make_commander()
        result = cmd.handle("")
        assert result is None
        tg.send_message.assert_not_called()

    def test_whitespace_text(self):
        cmd, mgr, tg = _make_commander()
        result = cmd.handle("   ")
        assert result is None
