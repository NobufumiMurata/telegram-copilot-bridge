"""Tests for config module."""

import json
import os
import tempfile

import pytest

from telegram_copilot_bridge.config import Config, load_config, load_dotenv


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


class TestLoadDotenv:
    def test_basic_key_value(self, tmp_path, monkeypatch):
        env_file = tmp_path / ".env"
        env_file.write_text("MY_VAR=hello\n", encoding="utf-8")
        monkeypatch.delenv("MY_VAR", raising=False)
        load_dotenv(env_file)
        assert os.environ["MY_VAR"] == "hello"

    def test_double_quoted_value(self, tmp_path, monkeypatch):
        env_file = tmp_path / ".env"
        env_file.write_text('MY_VAR="hello world"\n', encoding="utf-8")
        monkeypatch.delenv("MY_VAR", raising=False)
        load_dotenv(env_file)
        assert os.environ["MY_VAR"] == "hello world"

    def test_single_quoted_value(self, tmp_path, monkeypatch):
        env_file = tmp_path / ".env"
        env_file.write_text("MY_VAR='hello world'\n", encoding="utf-8")
        monkeypatch.delenv("MY_VAR", raising=False)
        load_dotenv(env_file)
        assert os.environ["MY_VAR"] == "hello world"

    def test_export_prefix_stripped(self, tmp_path, monkeypatch):
        env_file = tmp_path / ".env"
        env_file.write_text("export MY_VAR=exported\n", encoding="utf-8")
        monkeypatch.delenv("MY_VAR", raising=False)
        load_dotenv(env_file)
        assert os.environ["MY_VAR"] == "exported"

    def test_comments_and_blank_lines_ignored(self, tmp_path, monkeypatch):
        env_file = tmp_path / ".env"
        env_file.write_text("# comment\n\nMY_VAR=value\n", encoding="utf-8")
        monkeypatch.delenv("MY_VAR", raising=False)
        load_dotenv(env_file)
        assert os.environ["MY_VAR"] == "value"

    def test_env_var_takes_priority(self, tmp_path, monkeypatch):
        env_file = tmp_path / ".env"
        env_file.write_text("MY_VAR=from_file\n", encoding="utf-8")
        monkeypatch.setenv("MY_VAR", "from_env")
        load_dotenv(env_file)
        assert os.environ["MY_VAR"] == "from_env"

    def test_missing_file_is_silent(self, tmp_path):
        # Should not raise even if .env doesn't exist
        load_dotenv(tmp_path / "nonexistent.env")

    def test_telegram_env_file_env_var(self, tmp_path, monkeypatch):
        env_file = tmp_path / "custom.env"
        env_file.write_text("MY_VAR=custom\n", encoding="utf-8")
        monkeypatch.setenv("TELEGRAM_ENV_FILE", str(env_file))
        monkeypatch.delenv("MY_VAR", raising=False)
        load_dotenv()  # no explicit path — should use TELEGRAM_ENV_FILE
        assert os.environ["MY_VAR"] == "custom"


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
        # Prevent load_dotenv from picking up a real .env in CWD
        monkeypatch.setenv("TELEGRAM_ENV_FILE", str(tmp_path / "no.env"))
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

    def test_missing_all_raises(self, monkeypatch, tmp_path):
        monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
        monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
        monkeypatch.delenv("TELEGRAM_ALLOWED_USERS", raising=False)
        monkeypatch.setenv("TELEGRAM_ENV_FILE", str(tmp_path / "no.env"))
        with pytest.raises(ValueError):
            load_config()
