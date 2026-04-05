# telegram-copilot-bridge

Telegram Bot API を使って VS Code Copilot に通知・承認・対話ツールを提供する MCP サーバー。
スタンドアロン Hub モードでは MCP を介さず Telegram → Copilot CLI (ACP) ブリッジとしても動作する。
公開リポジトリ — 機密情報は一切含まない。

## プロジェクト構造

- Python 3.12+, src layout
- 2 つの起動モード:
  - **MCP モード** (デフォルト): MCP stdio transport で VS Code が起動・管理
  - **Hub モード** (`--hub`): スタンドアロンで Telegram → Copilot CLI (ACP) ブリッジ
- Telegram Bot API は `requests` で直接呼び出し (追加ライブラリ不要)
- 認証情報は環境変数優先、フォールバックで JSON 設定ファイル

## ファイル構成

```text
src/telegram_copilot_bridge/
  __init__.py
  __main__.py          ← エントリポイント (MCP / --hub モード切替)
  server.py            ← MCP サーバー (FastMCP デコレータベース)
  hub.py               ← スタンドアロン Hub ロジック (MCP 非依存)
  telegram.py          ← Telegram Bot API クライアント (バックグラウンドリスナー付き)
  config.py            ← 設定管理 (環境変数 / JSON)
  copilot_bridge.py    ← Copilot CLI ACP クライアント (NDJSON over stdio)
  session_manager.py   ← マルチセッション管理
  bot_commander.py     ← Telegram コマンドルーター
tests/
  test_config.py
  test_telegram.py
  test_server.py
  test_copilot_bridge.py
  test_session_manager.py
  test_bot_commander.py
```

## MCP ツール定義

| ツール名 | 説明 | 主要引数 |
|---------|------|---------|
| `telegram_notify` | メッセージ送信 (HTML) | `message: str` |
| `telegram_ask_approval` | インラインボタン承認 + 応答待ち | `question: str, options: list[str], timeout_minutes: int = 5` |
| `telegram_wait_response` | フリーテキスト応答待ち | `prompt: str, timeout_minutes: int = 10` |
| `telegram_send_file` | ファイル送信 | `file_path: str, caption: str = ""` |

## セキュリティ要件

- `allowed_users` リストで送信元ユーザー ID を検証 (全受信メッセージ)
- タイムアウト設定で無限待ちを防止 (デフォルト: ask_approval=5分, wait_response=10分)
- long-polling のオフセット管理 (古い更新の無視、`_drain_updates` で待機前にクリア)

## 設定 (環境変数)

### MCP サーバー用 (Bot A: 通知・承認)

| 環境変数 | 説明 | 必須 |
|---------|------|:---:|
| `TELEGRAM_BOT_TOKEN` | Bot API トークン | ✅ |
| `TELEGRAM_CHAT_ID` | 通知先チャット ID | ✅ |
| `TELEGRAM_ALLOWED_USERS` | カンマ区切りの許可ユーザー ID | 推奨 |
| `TELEGRAM_CONFIG_PATH` | JSON 設定ファイルパス (フォールバック) | ❌ |

### Hub モード用 (Bot B: Copilot リモート制御)

| 環境変数 | 説明 | 必須 |
|---------|------|:---:|
| `TELEGRAM_HUB_BOT_TOKEN` | Hub 専用 Bot トークン | ✅ |
| `TELEGRAM_HUB_CHAT_ID` | Hub 用チャット ID (未設定時は TELEGRAM_CHAT_ID) | ❌ |
| `TELEGRAM_ALLOWED_USERS` | 共通: 許可ユーザー ID | 推奨 |

**重要**: MCP Bot と Hub Bot は別の Bot Token を使うこと。同じ Token で同時に
`getUpdates` を呼ぶと 409 Conflict が発生する。

## 利用者側の MCP 登録例 (.vscode/mcp.json)

```json
{
  "servers": {
    "telegram-copilot-bridge": {
      "command": "python",
      "args": ["-m", "telegram_copilot_bridge"],
      "env": {
        "TELEGRAM_BOT_TOKEN": "...",
        "TELEGRAM_CHAT_ID": "...",
        "TELEGRAM_ALLOWED_USERS": "123456789"
      }
    }
  }
}
```

## Autopilot モード統合

このサーバーは VS Code Copilot の Autopilot (自動承認) モードとの併用を想定:

1. VS Code 側の承認は自動化 (autoApprove)
2. 破壊的操作の承認ゲートとして `telegram_ask_approval` を使用
3. タスク完了時に `telegram_notify` でレポート送信
4. `telegram_wait_response` で次のプロンプトをスマホから受信 → Copilot が継続

## Copilot リモート制御 (ACP)

Copilot CLI を Telegram からリモート制御する。2 つの起動方法がある:

### A. スタンドアロン Hub モード (MCP 不要)

```bash
# 環境変数をセットして直接起動
export TELEGRAM_BOT_TOKEN="..."
export TELEGRAM_CHAT_ID="..."
export TELEGRAM_ALLOWED_USERS="123456789"
python -m telegram_copilot_bridge --hub [--cwd /path/to/work] [--timeout 60] [-v]

# モデル指定 + Autopilot モード
python -m telegram_copilot_bridge --hub --model claude-opus-4.6 --autopilot

# 手動承認モード (デフォルト): ツール呼び出し時に Telegram インラインボタンで承認
python -m telegram_copilot_bridge --hub --model claude-opus-4.6
```

MCP サーバーを経由せず、直接 Telegram polling → Copilot CLI (ACP) のルーティングを行う。

### B. MCP ツール経由

`telegram_copilot_hub` MCP ツールを Copilot Chat から呼び出す。内部で同じ `hub.py` の `run_hub()` に委譲。

### 共通仕様

- Copilot CLI (`copilot --acp --stdio`) を subprocess で起動
- ACP (Agent Client Protocol) v1 で NDJSON over stdio 通信
- 複数セッションの同時管理が可能
- Telegram コマンド: /new, /list, /switch, /status, /stop, /done
- ツール許可: `--allow-tool` ホワイトリスト方式 (--allow-all-tools 禁止)
- 作業ディレクトリ制限: `COPILOT_ALLOWED_DIRS` で設定可能
- `/dirs` ルートフォルダ: `COPILOT_DIRS_ROOT` で設定。`/new` 引数なし時にフォルダ選択ボタンを表示
- **権限リクエスト**: Copilot CLI がツール使用許可を求める `session/request_permission` を
  Telegram インラインボタン (Allow once / Always allow / Deny) で中継。`--autopilot` 時はスキップ。

## 実装上の設計判断

- **FastMCP** デコレータベースで簡潔にツール定義 (`mcp.server.fastmcp.FastMCP`)
- Telegram API: `requests` で直接呼び出し。サードパーティラッパー不使用
- テスト: `pytest` + `unittest.mock` で Telegram API をモック
- long-polling: `getUpdates` API でユーザー応答を取得 (Webhook サーバー不要)
- `_client` はシングルトンパターン — MCP サーバーのライフサイクル内で 1 回だけ初期化
- Hub ロジック (`hub.py`): MCP に依存しない独立モジュール。MCP ツールとスタンドアロン CLI の両方から呼び出される
- `__main__.py`: argparse で `--hub` / `--cwd` / `--timeout` / `-v` を処理。デフォルトは MCP モード
- Copilot CLI ACP: `copilot --acp --stdio` を subprocess.Popen で起動、NDJSON (1行1JSON) で通信
- ACP メソッド: `initialize` → `session/new` → `session/prompt` (ストリーム応答は `session/update` 通知)
- バックグラウンドリスナー: Telegram ポーリングをデーモンスレッドで実行、メッセージハンドラーまたはキューで配信
