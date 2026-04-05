"""Tests for Telegram client."""

import json
from unittest.mock import MagicMock, patch, mock_open

import pytest

from telegram_copilot_bridge.telegram import TelegramClient


@pytest.fixture
def client():
    return TelegramClient(
        bot_token="test-token",
        chat_id="12345",
        allowed_users=["999"],
    )


class TestSendMessage:
    @patch("telegram_copilot_bridge.telegram.requests.post")
    def test_send_message(self, mock_post, client):
        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: {"ok": True, "result": {"message_id": 1}},
        )
        mock_post.return_value.raise_for_status = MagicMock()

        result = client.send_message("Hello")
        mock_post.assert_called_once()
        call_args = mock_post.call_args
        assert call_args[1]["data"]["text"] == "Hello"
        assert call_args[1]["data"]["chat_id"] == "12345"

    @patch("telegram_copilot_bridge.telegram.requests.post")
    def test_send_inline_keyboard(self, mock_post, client):
        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: {"ok": True, "result": {"message_id": 2}},
        )
        mock_post.return_value.raise_for_status = MagicMock()

        buttons = [[{"text": "Yes", "callback_data": "yes"}]]
        client.send_inline_keyboard("Approve?", buttons)
        call_data = mock_post.call_args[1]["data"]
        assert "reply_markup" in call_data
        markup = json.loads(call_data["reply_markup"])
        assert markup["inline_keyboard"][0][0]["text"] == "Yes"


class TestSendDocument:
    @patch("telegram_copilot_bridge.telegram.requests.post")
    def test_file_not_found(self, mock_post, client):
        with pytest.raises(FileNotFoundError):
            client.send_document("/nonexistent/file.txt")


class TestWaitForCallback:
    @patch("telegram_copilot_bridge.telegram.requests.post")
    def test_receives_allowed_callback(self, mock_post, client):
        # First call: drain (empty), Second call: callback update
        mock_post.return_value = MagicMock(
            status_code=200, raise_for_status=MagicMock()
        )
        drain_response = {"ok": True, "result": []}
        callback_response = {
            "ok": True,
            "result": [
                {
                    "update_id": 100,
                    "callback_query": {
                        "id": "cb1",
                        "from": {"id": 999},
                        "data": "yes",
                    },
                }
            ],
        }
        ack_response = {"ok": True, "result": True}
        mock_post.return_value.json = MagicMock(
            side_effect=[drain_response, callback_response, ack_response]
        )

        result = client.wait_for_callback(timeout_seconds=5)
        assert result == "yes"

    @patch("telegram_copilot_bridge.telegram.time.time")
    @patch("telegram_copilot_bridge.telegram.requests.post")
    def test_ignores_unauthorized_user(self, mock_post, mock_time, client):
        mock_post.return_value = MagicMock(
            status_code=200, raise_for_status=MagicMock()
        )
        drain_response = {"ok": True, "result": []}
        unauthorized_response = {
            "ok": True,
            "result": [
                {
                    "update_id": 101,
                    "callback_query": {
                        "id": "cb2",
                        "from": {"id": 888},  # not in allowed_users
                        "data": "yes",
                    },
                }
            ],
        }
        empty = {"ok": True, "result": []}
        mock_post.return_value.json = MagicMock(
            side_effect=[drain_response, unauthorized_response, empty]
        )
        # Simulate time: start=0, after drain=0, after unauth=1, then past deadline
        mock_time.side_effect = [0, 0, 0, 1, 100]

        result = client.wait_for_callback(timeout_seconds=2)
        assert result is None


class TestWaitForText:
    @patch("telegram_copilot_bridge.telegram.requests.post")
    def test_receives_allowed_text(self, mock_post, client):
        mock_post.return_value = MagicMock(
            status_code=200, raise_for_status=MagicMock()
        )
        drain_response = {"ok": True, "result": []}
        text_response = {
            "ok": True,
            "result": [
                {
                    "update_id": 200,
                    "message": {
                        "from": {"id": 999},
                        "text": "Check Sentinel rules",
                    },
                }
            ],
        }
        mock_post.return_value.json = MagicMock(
            side_effect=[drain_response, text_response]
        )

        result = client.wait_for_text(timeout_seconds=5)
        assert result == "Check Sentinel rules"

    @patch("telegram_copilot_bridge.telegram.requests.post")
    def test_timeout_returns_none(self, mock_post, client):
        mock_post.return_value = MagicMock(
            status_code=200, raise_for_status=MagicMock()
        )
        mock_post.return_value.json = MagicMock(
            return_value={"ok": True, "result": []}
        )

        result = client.wait_for_text(timeout_seconds=1)
        assert result is None


class TestIsAllowed:
    def test_empty_allowlist_allows_all(self):
        client = TelegramClient("tok", "123", allowed_users=[])
        assert client._is_allowed(888) is True

    def test_allowlist_blocks_unknown(self, client):
        assert client._is_allowed(888) is False

    def test_allowlist_allows_known(self, client):
        assert client._is_allowed(999) is True
        assert client._is_allowed("999") is True


class TestRouteResumeCallback:
    def test_resume_callback_routes_as_command(self, client):
        """A callback_query with 'resume:' prefix should be routed
        through the message_handler as '/resume <id>'."""
        handler = MagicMock(return_value=None)
        client._message_handler = handler
        client._listener_running = True

        # Patch answer_callback_query to avoid real API calls
        client.answer_callback_query = MagicMock()

        update = {
            "callback_query": {
                "id": "cb-resume",
                "from": {"id": 999},
                "data": "resume:ext-aaa-",
            }
        }
        client._route_update(update)

        client.answer_callback_query.assert_called_once_with(
            "cb-resume", text="Resuming…"
        )
        handler.assert_called_once_with("/resume ext-aaa-")

    def test_resume_callback_not_queued(self, client):
        """Resume callbacks should NOT go into the callback_queue."""
        handler = MagicMock(return_value=None)
        client._message_handler = handler
        client._listener_running = True
        client.answer_callback_query = MagicMock()

        update = {
            "callback_query": {
                "id": "cb-resume2",
                "from": {"id": 999},
                "data": "resume:abc",
            }
        }
        client._route_update(update)
        assert client._callback_queue.empty()

    def test_regular_callback_still_queued(self, client):
        """Non-resume callbacks should still go into the callback_queue."""
        client._listener_running = True
        client.answer_callback_query = MagicMock()

        update = {
            "callback_query": {
                "id": "cb-perm",
                "from": {"id": 999},
                "data": "allow_once",
            }
        }
        client._route_update(update)
        assert not client._callback_queue.empty()
        assert client._callback_queue.get_nowait() == "allow_once"
