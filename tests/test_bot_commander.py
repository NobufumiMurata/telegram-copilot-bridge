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
