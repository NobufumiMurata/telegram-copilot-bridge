# telegram-copilot-bridge

Telegram Bot API を使って Copilot CLI をリモート制御するブリッジ。
Telegram からプロンプト送信、セッション管理、ツール承認を行う。
公開リポジトリ — 機密情報は一切含まない。

## プロジェクト構造

- Python 3.12+, src layout
- Telegram → Copilot CLI (ACP) ブリッジとして動作
- Telegram Bot API は `requests` で直接呼び出し (追加ライブラリ不要)
- 認証情報は `.env` ファイル優先、フォールバックで環境変数・JSON 設定ファイル

## ファイル構成

```text
src/telegram_copilot_bridge/
  __init__.py
  __main__.py          ← エントリポイント (argparse → hub.run_hub())
  hub.py               ← Hub メインロジック (Telegram polling → Copilot CLI)
  telegram.py          ← Telegram Bot API クライアント (バックグラウンドリスナー付き)
  config.py            ← 設定管理 (.env / 環境変数 / JSON)
  copilot_bridge.py    ← Copilot CLI ACP クライアント (NDJSON over stdio)
  session_manager.py   ← マルチセッション管理
  bot_commander.py     ← Telegram コマンドルーター
tests/
  test_config.py
  test_telegram.py
  test_copilot_bridge.py
  test_session_manager.py
  test_bot_commander.py
```

## セキュリティ要件

- `allowed_users` リストで送信元ユーザー ID を検証 (全受信メッセージ)
- タイムアウト設定で自動シャットダウン (デフォルト: タイムアウトなし)
- 権限リクエストは 2 分でタイムアウト
- long-polling のオフセット管理 (古い更新の無視、`_drain_updates` で待機前にクリア)
- シングルトンロック: TCP ポートバインドで多重起動を防止

## 設定

`.env` ファイルから自動読み込み。環境変数が優先。

| 環境変数 | 説明 | 必須 |
|---------|------|:---:|
| `TELEGRAM_BOT_TOKEN` | Bot API トークン | ✅ |
| `TELEGRAM_CHAT_ID` | 通知先チャット ID | ✅ |
| `TELEGRAM_ALLOWED_USERS` | カンマ区切りの許可ユーザー ID | 推奨 |
| `TELEGRAM_ENV_FILE` | `.env` ファイルパス (デフォルト: CWD の `.env`) | ❌ |
| `TELEGRAM_CONFIG_PATH` | JSON 設定ファイルパス (フォールバック) | ❌ |
| `COPILOT_MODEL` | デフォルト AI モデル | ❌ |
| `COPILOT_AUTOPILOT` | `true` で自動承認モード | ❌ |
| `COPILOT_DIRS_ROOT` | `/dirs` と `/new` のルートフォルダ | ❌ |
| `COPILOT_ALLOWED_DIRS` | カンマ区切りの許可ディレクトリ | ❌ |
| `COPILOT_ALLOWED_TOOLS` | カンマ区切りの許可ツール | ❌ |

## 起動方法

```bash
# .env ファイルを作成
cp .env.example .env

# 起動 (--hub フラグ不要、デフォルトで Hub モード)
python -m telegram_copilot_bridge

# オプション指定
python -m telegram_copilot_bridge --model claude-opus-4.6 --autopilot -v
```

## Telegram コマンド

| コマンド | 動作 |
|---------|------|
| `/new [dir]` | 新しい Copilot セッション (COPILOT_DIRS_ROOT 設定時はフォルダ選択ボタン表示) |
| `/history [n]` | 過去のセッション一覧 (デフォルト: 3件) |
| `/resume <id>` | 過去のセッションを再開 |
| `/dirs [dir]` | ディレクトリ閲覧 |
| `/model [name]` | AI モデルの表示/変更 |
| `/mode` | autopilot/manual 切替 |
| `/list` | アクティブセッション一覧 |
| `/switch <id>` | セッション切替 |
| `/status` | セッション状態 |
| `/stop [id]` | セッション停止 |
| `/done` | 全停止・終了 |
| `/help` | ヘルプ表示 |
| (テキスト) | アクティブセッションにプロンプト送信 |

## 実装上の設計判断

- Telegram API: `requests` で直接呼び出し。サードパーティラッパー不使用
- テスト: `pytest` + `unittest.mock` で Telegram API をモック
- long-polling: `getUpdates` API でユーザー応答を取得 (Webhook サーバー不要)
- `__main__.py`: argparse で `--cwd` / `--timeout` / `--model` / `--autopilot` / `-v` を処理
- Copilot CLI ACP: `copilot --acp --stdio` を subprocess.Popen で起動、NDJSON (1行1JSON) で通信
- ACP メソッド: `initialize` → `session/new` → `session/prompt` (ストリーム応答は `session/update` 通知)
- バックグラウンドリスナー: Telegram ポーリングをデーモンスレッドで実行、メッセージハンドラーまたはキューで配信
- `.env` ファイル: stdlib のみで実装 (python-dotenv 不要)、`load_dotenv()` で自動読み込み
- **権限リクエスト**: Copilot CLI がツール使用許可を求める `session/request_permission` を
  Telegram インラインボタン (Allow once / Always allow / Deny) で中継。`--autopilot` 時はスキップ。
