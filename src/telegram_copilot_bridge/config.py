"""Configuration management for telegram-copilot-bridge.

Priority: environment variables > .env file > JSON config file.
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


def load_dotenv(env_file: str | Path | None = None) -> None:
    """Load a .env file into ``os.environ``, skipping already-set variables.

    Supported syntax::

        KEY=value
        KEY="value with spaces"
        KEY='value'
        export KEY=value   # shell-style (export keyword is stripped)
        # comment lines are ignored

    Args:
        env_file: Path to the .env file.  If *None*, checks ``TELEGRAM_ENV_FILE``
                  env var, then falls back to ``.env`` in the current directory.
    """
    if env_file is None:
        explicit = os.environ.get("TELEGRAM_ENV_FILE", "")
        env_file = Path(explicit) if explicit else Path(".env")

    env_path = Path(env_file)
    if not env_path.is_file():
        return

    with env_path.open(encoding="utf-8") as fh:
        for raw_line in fh:
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            # Strip leading "export " (shell syntax)
            if line.startswith("export "):
                line = line[len("export "):].lstrip()
            if "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip()
            # Strip surrounding quotes
            if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
                value = value[1:-1]
            # Env vars already set in the environment take priority
            if key and key not in os.environ:
                os.environ[key] = value


def load_config(config_path: str | None = None) -> Config:
    """Load configuration from environment variables, falling back to JSON file.

    Reads ``.env`` automatically before checking ``os.environ``.
    """
    load_dotenv()
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    allowed_users_str = os.environ.get("TELEGRAM_ALLOWED_USERS", "")
    allowed_users = [u.strip() for u in allowed_users_str.split(",") if u.strip()]

    # Fall back to JSON config file if env vars are not set
    if not bot_token:
        json_path = config_path or os.environ.get("TELEGRAM_CONFIG_PATH", "")
        if json_path:
            path = Path(json_path)
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
