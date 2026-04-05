# telegram-copilot-bridge

A [Model Context Protocol (MCP)](https://modelcontextprotocol.io/) server that bridges VS Code Copilot with Telegram, enabling mobile notifications, approval workflows, and remote prompt input from your smartphone.

## Features

- **Notifications** — Send task completion reports to Telegram
- **Approval Flow** — Inline keyboard buttons for approve/reject decisions
- **Remote Prompt** — Receive next instructions from your phone via free-text response
- **File Sharing** — Send files (logs, JSON results) directly to Telegram
- **Copilot Remote Control** — Full remote control of Copilot CLI from Telegram via ACP (Agent Client Protocol)

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
pip install telegram-copilot-bridge
```

Or install from source:

```bash
git clone https://github.com/NobufumiMurata/telegram-copilot-bridge.git
cd telegram-copilot-bridge
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

### 3. Configure

#### Option A — `.env` file (recommended for hub/standalone mode)

Copy the example file and edit it:

```bash
cp .env.example .env
```

```ini
# .env
TELEGRAM_BOT_TOKEN=1234567890:AAXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX
TELEGRAM_CHAT_ID=-100000000000
TELEGRAM_ALLOWED_USERS=123456789

# Hub mode: separate Bot to avoid 409 Conflict with MCP server
TELEGRAM_HUB_BOT_TOKEN=0987654321:BBXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX

# Root folder shown in /dirs and /new folder picker
COPILOT_DIRS_ROOT=/home/user/projects
```

The `.env` file is loaded automatically on startup (from the current directory).
Use `TELEGRAM_ENV_FILE=/path/to/.env` to point to a different location.
Environment variables set in the shell always take priority over `.env`.

#### Option B — VS Code `mcp.json` (recommended for MCP server mode)

Add to your `.vscode/mcp.json`:

```json
{
  "servers": {
    "telegram-copilot-bridge": {
      "command": "python",
      "args": ["-m", "telegram_copilot_bridge"],
      "env": {
        "TELEGRAM_BOT_TOKEN": "<your-bot-token>",
        "TELEGRAM_CHAT_ID": "<your-chat-id>",
        "TELEGRAM_ALLOWED_USERS": "<your-user-id>"
      }
    }
  }
}
```

#### Option C — JSON config file

```json
{
  "bot_token": "<your-bot-token>",
  "chat_id": "<your-chat-id>",
  "allowed_users": ["<your-user-id>"]
}
```

Set `TELEGRAM_CONFIG_PATH` (or add to `.env`) to point to the file:

```ini
TELEGRAM_CONFIG_PATH=secrets/telegram-bot.json
```

## MCP Tools

| Tool | Description | Key Args |
|------|-------------|----------|
| `telegram_notify` | Send a text message (HTML) | `message` |
| `telegram_ask_approval` | Inline buttons + wait for selection | `question`, `options`, `timeout_minutes` |
| `telegram_wait_response` | Send prompt + wait for free-text reply | `prompt`, `timeout_minutes` |
| `telegram_send_file` | Send a file | `file_path`, `caption` |
| `telegram_copilot_hub` | Copilot remote control via Telegram | `default_cwd`, `timeout_minutes` |

### Copilot Remote Control Hub

`telegram_copilot_hub` connects Telegram to [GitHub Copilot CLI](https://docs.github.com/en/copilot/concepts/agents/about-copilot-cli) via the ACP (Agent Client Protocol). You can start Copilot sessions, send prompts, and manage multiple sessions — all from your phone.

```
📱 Telegram
    ↕ (Bot API long-polling)
🐍 telegram-copilot-bridge
    ↕ (stdin/stdout NDJSON)
🤖 copilot --acp --stdio
```

**Telegram commands (in hub mode):**

| Command | Action |
|---------|--------|
| `/new [dir]` | Start a new Copilot session |
| `/list` | List active sessions |
| `/switch <id>` | Switch active session |
| `/status` | Session status |
| `/stop [id]` | Stop a session |
| `/done` | Stop all sessions & exit hub |
| `/help` | Show commands |
| *(any text)* | Send as prompt to active session |

**Prerequisites:** Install [Copilot CLI](https://docs.github.com/en/copilot/how-tos/set-up/install-copilot-cli) and authenticate:

```bash
winget install GitHub.Copilot   # or: npm install -g @github/copilot
copilot                         # then /login to authenticate
```

**Environment variables (all modes):**

| Variable | Description | Default |
|----------|-------------|---------|
| `TELEGRAM_ENV_FILE` | Path to the `.env` file | `.env` in CWD |
| `TELEGRAM_BOT_TOKEN` | Bot token (MCP server) | *(required)* |
| `TELEGRAM_CHAT_ID` | Target chat ID | *(required)* |
| `TELEGRAM_ALLOWED_USERS` | Comma-separated allowed user IDs | *(allow all)* |
| `TELEGRAM_HUB_BOT_TOKEN` | Bot token for hub mode (separate from MCP) | fallback to `TELEGRAM_BOT_TOKEN` |
| `TELEGRAM_HUB_CHAT_ID` | Chat ID for hub mode | fallback to `TELEGRAM_CHAT_ID` |
| `TELEGRAM_CONFIG_PATH` | JSON credential file (MCP server only) | — |

**Copilot hub variables:**

| Variable | Description | Default |
|----------|-------------|---------|
| `COPILOT_CLI_PATH` | Path to copilot executable | `copilot` (from PATH) |
| `COPILOT_MODEL` | Default AI model | Copilot default |
| `COPILOT_AUTOPILOT` | Auto-approve tool calls (`true`/`false`) | `false` |
| `COPILOT_DIRS_ROOT` | Root directory for `/dirs` and `/new` folder picker | (uses --cwd) |
| `COPILOT_ALLOWED_DIRS` | Comma-separated allowed working dirs | (any) |
| `COPILOT_ALLOWED_TOOLS` | Comma-separated tools to allow | `shell(git),read,write` |
| `HUB_LOCK_PORT` | TCP port for Hub singleton lock | `47732` |

## Standalone Hub Mode

You can run the Copilot remote-control hub **without MCP**, directly from the command line. This is useful when you want to control Copilot CLI from Telegram without going through VS Code.

```bash
# Copy and edit the .env file
cp .env.example .env
# (fill in TELEGRAM_HUB_BOT_TOKEN, TELEGRAM_CHAT_ID, etc.)

# Start hub mode
python -m telegram_copilot_bridge --hub

# With options
python -m telegram_copilot_bridge --hub \
  --cwd /path/to/project \
  --model claude-opus-4.6 \
  --timeout 120 \
  -v
```

> **Note:** Hub mode uses `TELEGRAM_HUB_BOT_TOKEN` if set, otherwise falls back to `TELEGRAM_BOT_TOKEN`. If you run both MCP and Hub simultaneously, use separate Bot tokens to avoid `409 Conflict` errors from concurrent `getUpdates` calls.

**CLI options:**

| Flag | Description | Default |
|------|-------------|---------|
| `--hub` | Enable standalone hub mode | *(MCP mode)* |
| `--cwd <dir>` | Default working directory for sessions | current dir |
| `--model <name>` | AI model (e.g. `claude-opus-4.6`) | Copilot default |
| `--timeout <min>` | Hub timeout in minutes (0 = no timeout) | `60` |
| `--autopilot` | Auto-approve all tool calls | off (manual approval via Telegram) |
| `-v`, `--verbose` | Enable debug logging | off |

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
- **Timeouts**: All waiting operations have configurable timeouts (default: 5 min for approval, 10 min for text, 60 min for hub). Returns `TIMEOUT` status on expiry.
- **No secrets in repo**: All credentials via environment variables or external config file.
- **Stale update draining**: Old Telegram updates are consumed before waiting, preventing stale responses from being accepted.
- **Copilot tool allowlist**: Hub mode uses `--allow-tool` (not `--allow-all-tools`) to restrict what Copilot CLI can do. Configure via `COPILOT_ALLOWED_TOOLS`.
- **Directory restrictions**: Optionally restrict which directories Copilot sessions can operate in via `COPILOT_ALLOWED_DIRS`.

## Development

```bash
git clone https://github.com/NobufumiMurata/telegram-copilot-bridge.git
cd telegram-copilot-bridge
pip install -e ".[dev]"
pytest
```

## License

MIT
