"""Configuration management for telegram-copilot-bridge.

Priority: environment variables > JSON config file.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Config:
    bot_token: str
    chat_id: str
    allowed_users: list[str] = field(default_factory=list)

    def validate(self) -> None:
        if not self.bot_token:
            raise ValueError("TELEGRAM_BOT_TOKEN is required")
        if not self.chat_id:
            raise ValueError("TELEGRAM_CHAT_ID is required")


def load_config(config_path: str | None = None) -> Config:
    """Load configuration from environment variables, falling back to JSON file."""
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    allowed_users_str = os.environ.get("TELEGRAM_ALLOWED_USERS", "")
    allowed_users = [u.strip() for u in allowed_users_str.split(",") if u.strip()]

    # Fall back to JSON config file if env vars are not set
    if not bot_token and config_path:
        path = Path(config_path)
        if path.is_file():
            data = json.loads(path.read_text(encoding="utf-8"))
            bot_token = bot_token or data.get("bot_token", "")
            chat_id = chat_id or data.get("chat_id", "")
            if not allowed_users:
                allowed_users = data.get("allowed_users", [])

    config = Config(
        bot_token=bot_token,
        chat_id=chat_id,
        allowed_users=allowed_users,
    )
    config.validate()
    return config
