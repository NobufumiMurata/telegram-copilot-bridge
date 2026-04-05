"""Tests for MCP server tools."""

from unittest.mock import MagicMock, patch

import pytest

# Import the module to trigger FastMCP initialization once
import telegram_copilot_bridge.server as srv


class TestTelegramNotify:
    def test_notify_sends_message(self):
        mock_client = MagicMock()
        with patch.object(srv, "_client", mock_client):
            result = srv.telegram_notify("Test notification")
            mock_client.send_message.assert_called_once_with("Test notification")
            assert "sent" in result.lower()


class TestTelegramAskApproval:
    def test_approval_returns_selection(self):
        mock_client = MagicMock()
        mock_client.wait_for_callback.return_value = "Approve"
        with patch.object(srv, "_client", mock_client):
            result = srv.telegram_ask_approval("Delete VM?", ["Approve", "Reject"])
            assert "Approve" in result
            mock_client.send_inline_keyboard.assert_called_once()

    def test_approval_timeout(self):
        mock_client = MagicMock()
        mock_client.wait_for_callback.return_value = None
        with patch.object(srv, "_client", mock_client):
            result = srv.telegram_ask_approval("Delete VM?", timeout_minutes=1)
            assert "TIMEOUT" in result


class TestTelegramWaitResponse:
    def test_wait_returns_text(self):
        mock_client = MagicMock()
        mock_client.wait_for_text.return_value = "Check Sentinel"
        with patch.object(srv, "_client", mock_client):
            result = srv.telegram_wait_response("What next?")
            assert result == "Check Sentinel"
            mock_client.send_message.assert_called_once_with("What next?")

    def test_wait_timeout(self):
        mock_client = MagicMock()
        mock_client.wait_for_text.return_value = None
        with patch.object(srv, "_client", mock_client):
            result = srv.telegram_wait_response("What next?", timeout_minutes=1)
            assert "TIMEOUT" in result


class TestTelegramSendFile:
    def test_send_file(self):
        mock_client = MagicMock()
        with patch.object(srv, "_client", mock_client):
            result = srv.telegram_send_file("/tmp/report.json", caption="Results")
            mock_client.send_document.assert_called_once_with("/tmp/report.json", caption="Results")
            assert "sent" in result.lower()
