"""Tests for config module."""

import json
import os
import tempfile

import pytest

from telegram_copilot_bridge.config import Config, load_config


class TestConfig:
    def test_validate_missing_token(self):
        cfg = Config(bot_token="", chat_id="123")
        with pytest.raises(ValueError, match="TELEGRAM_BOT_TOKEN"):
            cfg.validate()

    def test_validate_missing_chat_id(self):
        cfg = Config(bot_token="tok", chat_id="")
        with pytest.raises(ValueError, match="TELEGRAM_CHAT_ID"):
            cfg.validate()

    def test_validate_ok(self):
        cfg = Config(bot_token="tok", chat_id="123")
        cfg.validate()  # should not raise


class TestLoadConfig:
    def test_from_env(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "env-token")
        monkeypatch.setenv("TELEGRAM_CHAT_ID", "env-chat")
        monkeypatch.setenv("TELEGRAM_ALLOWED_USERS", "111,222")
        cfg = load_config()
        assert cfg.bot_token == "env-token"
        assert cfg.chat_id == "env-chat"
        assert cfg.allowed_users == ["111", "222"]

    def test_from_json_fallback(self, monkeypatch, tmp_path):
        monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
        monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
        monkeypatch.delenv("TELEGRAM_ALLOWED_USERS", raising=False)
        config_file = tmp_path / "config.json"
        config_file.write_text(
            json.dumps(
                {
                    "bot_token": "json-token",
                    "chat_id": "json-chat",
                    "allowed_users": ["333"],
                }
            ),
            encoding="utf-8",
        )
        cfg = load_config(config_path=str(config_file))
        assert cfg.bot_token == "json-token"
        assert cfg.chat_id == "json-chat"
        assert cfg.allowed_users == ["333"]

    def test_env_takes_priority(self, monkeypatch, tmp_path):
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "env-token")
        monkeypatch.setenv("TELEGRAM_CHAT_ID", "env-chat")
        monkeypatch.setenv("TELEGRAM_ALLOWED_USERS", "")
        config_file = tmp_path / "config.json"
        config_file.write_text(
            json.dumps({"bot_token": "json-token", "chat_id": "json-chat"}),
            encoding="utf-8",
        )
        cfg = load_config(config_path=str(config_file))
        assert cfg.bot_token == "env-token"

    def test_missing_all_raises(self, monkeypatch):
        monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
        monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
        monkeypatch.delenv("TELEGRAM_ALLOWED_USERS", raising=False)
        with pytest.raises(ValueError):
            load_config()
