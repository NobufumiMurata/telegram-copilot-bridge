# mcp-telegram-notify

A [Model Context Protocol (MCP)](https://modelcontextprotocol.io/) server that bridges VS Code Copilot with Telegram, enabling mobile notifications, approval workflows, and remote prompt input from your smartphone.

## Features

- **Notifications** — Send task completion reports to Telegram
- **Approval Flow** — Inline keyboard buttons for approve/reject decisions
- **Remote Prompt** — Receive next instructions from your phone via free-text response
- **File Sharing** — Send files (logs, JSON results) directly to Telegram

## Use Case: Copilot Autopilot + Mobile Control

```
VS Code Copilot (Autopilot mode, auto-approve ON)
  → Executes tasks automatically
  → Asks approval via Telegram before destructive ops
  → Reports completion to your phone
  → Waits for your next instruction via Telegram
  → Continues working
```

No need to be at your desk — control Copilot entirely from your smartphone.

## Installation

```bash
pip install mcp-telegram-notify
```

Or install from source:

```bash
git clone https://github.com/NobufumiMurata/mcp-telegram-notify.git
cd mcp-telegram-notify
pip install -e ".[dev]"
```

## Setup

### 1. Create a Telegram Bot

1. Open Telegram and message [@BotFather](https://t.me/BotFather)
2. Send `/newbot` and follow the prompts
3. Copy the bot token

### 2. Get Your Chat ID and User ID

Send any message to your bot, then:

```bash
curl "https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates"
```

From the response, note:
- `"chat": {"id": ...}` → your **Chat ID**
- `"from": {"id": ...}` → your **User ID** (for the allowlist)

### 3. Configure VS Code MCP

Add to your `.vscode/mcp.json`:

```json
{
  "servers": {
    "telegram-notify": {
      "command": "python",
      "args": ["-m", "mcp_telegram_notify"],
      "env": {
        "TELEGRAM_BOT_TOKEN": "<your-bot-token>",
        "TELEGRAM_CHAT_ID": "<your-chat-id>",
        "TELEGRAM_ALLOWED_USERS": "<your-user-id>"
      }
    }
  }
}
```

### Alternative: JSON Config File

Instead of environment variables, you can use a JSON config file:

```json
{
  "bot_token": "<your-bot-token>",
  "chat_id": "<your-chat-id>",
  "allowed_users": ["<your-user-id>"]
}
```

Then set `TELEGRAM_CONFIG_PATH` to point to the file:

```json
{
  "servers": {
    "telegram-notify": {
      "command": "python",
      "args": ["-m", "mcp_telegram_notify"],
      "env": {
        "TELEGRAM_CONFIG_PATH": "secrets/telegram-bot.json"
      }
    }
  }
}
```

## MCP Tools

| Tool | Description | Key Args |
|------|-------------|----------|
| `telegram_notify` | Send a text message (HTML) | `message` |
| `telegram_ask_approval` | Inline buttons + wait for selection | `question`, `options`, `timeout_minutes` |
| `telegram_wait_response` | Send prompt + wait for free-text reply | `prompt`, `timeout_minutes` |
| `telegram_send_file` | Send a file | `file_path`, `caption` |

### Example: Copilot Agent Instructions

Add to your `.github/agents/*.agent.md` to make Copilot use these tools automatically:

```markdown
## Notification Rules (Telegram MCP)

- Before destructive operations (VM stop/delete, resource deletion, network changes),
  use telegram_ask_approval to get explicit user approval
- After completing a task, use telegram_notify to send a summary report
- After sending the report, use telegram_wait_response to receive the next instruction
- Treat the received instruction as a new task and continue processing
```

## Security

- **User allowlist**: Only messages from `TELEGRAM_ALLOWED_USERS` are accepted. All other users are silently ignored.
- **Timeouts**: All waiting operations have configurable timeouts (default: 5 min for approval, 10 min for text). Returns `TIMEOUT` status on expiry.
- **No secrets in repo**: All credentials via environment variables or external config file.
- **Stale update draining**: Old Telegram updates are consumed before waiting, preventing stale responses from being accepted.

## Development

```bash
git clone https://github.com/NobufumiMurata/mcp-telegram-notify.git
cd mcp-telegram-notify
pip install -e ".[dev]"
pytest
```

## License

MIT
