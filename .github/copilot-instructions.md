# mcp-telegram-notify

Telegram Bot API を使って VS Code Copilot に通知・承認・対話ツールを提供する MCP サーバー。
公開リポジトリ — 機密情報は一切含まない。

## プロジェクト構造

- Python 3.12+, src layout
- MCP stdio transport (VS Code が起動・管理)
- Telegram Bot API は `requests` で直接呼び出し (追加ライブラリ不要)
- 認証情報は環境変数優先、フォールバックで JSON 設定ファイル

## ファイル構成

```text
src/mcp_telegram_notify/
  __init__.py
  __main__.py   ← python -m mcp_telegram_notify で起動
  server.py     ← MCP サーバー (FastMCP デコレータベース)
  telegram.py   ← Telegram Bot API クライアント (requests のみ)
  config.py     ← 設定管理 (環境変数 / JSON)
tests/
  test_config.py
  test_telegram.py
  test_server.py
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

| 環境変数 | 説明 | 必須 |
|---------|------|:---:|
| `TELEGRAM_BOT_TOKEN` | Bot API トークン | ✅ |
| `TELEGRAM_CHAT_ID` | 通知先チャット ID | ✅ |
| `TELEGRAM_ALLOWED_USERS` | カンマ区切りの許可ユーザー ID | 推奨 |
| `TELEGRAM_CONFIG_PATH` | JSON 設定ファイルパス (環境変数未設定時のフォールバック) | ❌ |

## 利用者側の MCP 登録例 (.vscode/mcp.json)

```json
{
  "servers": {
    "telegram-notify": {
      "command": "python",
      "args": ["-m", "mcp_telegram_notify"],
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

## 実装上の設計判断

- **FastMCP** デコレータベースで簡潔にツール定義 (`mcp.server.fastmcp.FastMCP`)
- Telegram API: `requests` で直接呼び出し。サードパーティラッパー不使用
- テスト: `pytest` + `unittest.mock` で Telegram API をモック
- long-polling: `getUpdates` API でユーザー応答を取得 (Webhook サーバー不要)
- `_client` はシングルトンパターン — MCP サーバーのライフサイクル内で 1 回だけ初期化
