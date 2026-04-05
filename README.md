# telegram-copilot-bridge

Control [GitHub Copilot CLI](https://docs.github.com/en/copilot/concepts/agents/about-copilot-cli) remotely from Telegram. Send prompts, manage sessions, and approve tool calls — all from your smartphone.

## Architecture

```
📱 Telegram
    ↕ (Bot API long-polling)
🐍 telegram-copilot-bridge
    ↕ (stdin/stdout NDJSON — ACP)
🤖 copilot --acp --stdio
```

## Features

- **Remote Prompting** — Send Copilot prompts from Telegram, receive results on your phone
- **Multi-Session** — Run multiple Copilot sessions in parallel, switch between them
- **Tool Approval** — Approve or deny Copilot's tool calls via inline buttons
- **Autopilot Mode** — Auto-approve all tool calls for hands-free operation
- **Session History** — Resume past Copilot sessions with one tap
- **Folder Picker** — `/new` shows inline buttons for project directories

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

**Prerequisites:** Install [Copilot CLI](https://docs.github.com/en/copilot/how-tos/set-up/install-copilot-cli) and authenticate:

```bash
winget install GitHub.Copilot   # or: npm install -g @github/copilot
copilot                         # then /login to authenticate
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

Copy the example file and fill in your values:

```bash
cp .env.example .env
```

```ini
# .env
TELEGRAM_BOT_TOKEN=1234567890:AAXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX
TELEGRAM_CHAT_ID=-100000000000
TELEGRAM_ALLOWED_USERS=123456789

# Default AI model
COPILOT_MODEL=claude-opus-4.6

# Root folder for /dirs and /new folder picker
COPILOT_DIRS_ROOT=/home/user/projects
```

The `.env` file is loaded automatically on startup (from the current directory).
Use `TELEGRAM_ENV_FILE=/path/to/.env` to point to a different location.
Environment variables set in the shell always take priority over `.env`.

## Usage

```bash
# Start (reads .env automatically)
python -m telegram_copilot_bridge

# With options
python -m telegram_copilot_bridge \
  --cwd /path/to/project \
  --model claude-opus-4.6 \
  --timeout 120 \
  -v
```

**CLI options:**

| Flag | Description | Default |
|------|-------------|---------|
| `--cwd <dir>` | Default working directory for sessions | current dir |
| `--model <name>` | AI model (e.g. `claude-opus-4.6`) | `claude-opus-4.6` |
| `--timeout <min>` | Auto-shutdown in minutes (0 = no timeout) | `0` |
| `--autopilot` | Auto-approve all tool calls | off (manual approval via Telegram) |
| `-v`, `--verbose` | Enable debug logging | off |

## Telegram Commands

| Command | Action |
|---------|--------|
| `/new [dir]` | Start a new Copilot session (shows folder picker if `COPILOT_DIRS_ROOT` is set) |
| `/history [n]` | List past CLI sessions (default: 3) |
| `/resume <id>` | Resume a past session |
| `/dirs [dir]` | Browse directories |
| `/model [name]` | Show/set AI model |
| `/mode` | Toggle autopilot/manual approval |
| `/list` | List active sessions |
| `/switch <id>` | Switch active session |
| `/status` | Session status |
| `/stop [id]` | Stop a session |
| `/done` | Stop all sessions & exit |
| `/help` | Show commands |
| *(any text)* | Send as prompt to active session |

## Environment Variables

All variables can be set in `.env` or in the shell. Shell values take priority.

**Telegram:**

| Variable | Description | Default |
|----------|-------------|---------|
| `TELEGRAM_BOT_TOKEN` | Bot API token | *(required)* |
| `TELEGRAM_CHAT_ID` | Target chat ID | *(required)* |
| `TELEGRAM_ALLOWED_USERS` | Comma-separated allowed user IDs | *(allow all)* |
| `TELEGRAM_ENV_FILE` | Path to the `.env` file | `.env` in CWD |
| `TELEGRAM_CONFIG_PATH` | JSON credential file (fallback) | — |

**Copilot:**

| Variable | Description | Default |
|----------|-------------|---------|
| `COPILOT_CLI_PATH` | Path to copilot executable | `copilot` (from PATH) |
| `COPILOT_MODEL` | Default AI model | `claude-opus-4.6` |
| `COPILOT_AUTOPILOT` | Auto-approve tool calls (`true`/`false`) | `false` |
| `COPILOT_DIRS_ROOT` | Root directory for `/dirs` and `/new` folder picker | (uses --cwd) |
| `COPILOT_ALLOWED_DIRS` | Comma-separated allowed working dirs | (any) |
| `COPILOT_ALLOWED_TOOLS` | Comma-separated tools to allow | `shell(git),read,write` |
| `COPILOT_PERMISSION_TIMEOUT_SECONDS` | Permission approval timeout (seconds) | `300` (5 min) |
| `HUB_LOCK_PORT` | TCP port for singleton lock | `47732` |

## Security

- **User allowlist**: Only messages from `TELEGRAM_ALLOWED_USERS` are accepted. All other users are silently ignored.
- **Timeouts**: Configurable auto-shutdown timeout (default: no timeout). Permission requests timeout after 5 minutes (configurable via `COPILOT_PERMISSION_TIMEOUT_SECONDS`).
- **No secrets in repo**: All credentials via `.env` file or environment variables.
- **Tool allowlist**: Uses `--allow-tool` (not `--allow-all-tools`) to restrict what Copilot CLI can do.
- **Directory restrictions**: Restrict which directories Copilot sessions can operate in via `COPILOT_ALLOWED_DIRS`.
- **Singleton lock**: Only one instance can run per machine (TCP port lock).

## Development

```bash
git clone https://github.com/NobufumiMurata/telegram-copilot-bridge.git
cd telegram-copilot-bridge
pip install -e ".[dev]"
pytest
```

## License

MIT
