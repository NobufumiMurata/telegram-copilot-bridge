"""Telegram Bot API client using requests (no additional libraries needed)."""

from __future__ import annotations

import json
import logging
import queue
import threading
import time
from pathlib import Path
from typing import Any, Callable

import requests

logger = logging.getLogger(__name__)

API_BASE = "https://api.telegram.org/bot{token}"


class TelegramClient:
    """Lightweight Telegram Bot API client with long-polling support."""

    def __init__(
        self,
        bot_token: str,
        chat_id: str,
        allowed_users: list[str] | None = None,
        request_timeout: int = 30,
    ) -> None:
        self._token = bot_token
        self._chat_id = chat_id
        self._allowed_users = set(allowed_users or [])
        self._base = API_BASE.format(token=bot_token)
        self._timeout = request_timeout
        self._update_offset: int | None = None
        # Background listener state
        self._listener_running = False
        self._listener_thread: threading.Thread | None = None
        self._text_queue: queue.Queue[str] = queue.Queue()
        self._callback_queue: queue.Queue[str] = queue.Queue()
        self._message_handler: Callable[[str], str | None] | None = None

    # ------------------------------------------------------------------
    # Low-level API helpers
    # ------------------------------------------------------------------

    def _call(
        self, method: str, data: dict[str, Any] | None = None, files: dict | None = None
    ) -> dict[str, Any]:
        url = f"{self._base}/{method}"
        resp = requests.post(url, data=data, files=files, timeout=self._timeout)
        resp.raise_for_status()
        result = resp.json()
        if not result.get("ok"):
            raise RuntimeError(f"Telegram API error: {result.get('description', result)}")
        return result.get("result", {})

    # ------------------------------------------------------------------
    # Send methods
    # ------------------------------------------------------------------

    def send_message(self, text: str, parse_mode: str = "HTML") -> dict[str, Any]:
        """Send a text message to the configured chat."""
        return self._call(
            "sendMessage",
            {"chat_id": self._chat_id, "text": text, "parse_mode": parse_mode},
        )

    def send_document(self, file_path: str, caption: str = "") -> dict[str, Any]:
        """Send a file to the configured chat."""
        p = Path(file_path)
        if not p.is_file():
            raise FileNotFoundError(f"File not found: {file_path}")
        with p.open("rb") as f:
            data = {"chat_id": self._chat_id}
            if caption:
                data["caption"] = caption
            return self._call("sendDocument", data=data, files={"document": (p.name, f)})

    def send_inline_keyboard(
        self, text: str, buttons: list[list[dict[str, str]]]
    ) -> dict[str, Any]:
        """Send a message with an inline keyboard.

        buttons example: [[{"text": "Yes", "callback_data": "yes"},
                           {"text": "No",  "callback_data": "no"}]]
        """
        keyboard = json.dumps({"inline_keyboard": buttons})
        return self._call(
            "sendMessage",
            {
                "chat_id": self._chat_id,
                "text": text,
                "reply_markup": keyboard,
                "parse_mode": "HTML",
            },
        )

    def answer_callback_query(self, callback_query_id: str, text: str = "") -> dict[str, Any]:
        """Acknowledge an inline keyboard button press."""
        data: dict[str, Any] = {"callback_query_id": callback_query_id}
        if text:
            data["text"] = text
        return self._call("answerCallbackQuery", data)

    # ------------------------------------------------------------------
    # Receive methods (long-polling)
    # ------------------------------------------------------------------

    def get_updates(self, timeout: int = 30) -> list[dict[str, Any]]:
        """Fetch new updates via long-polling."""
        params: dict[str, Any] = {"timeout": timeout, "allowed_updates": '["message","callback_query"]'}
        if self._update_offset is not None:
            params["offset"] = self._update_offset
        result = self._call("getUpdates", params)
        if result:
            self._update_offset = max(u["update_id"] for u in result) + 1
        return result

    def _is_allowed(self, user_id: str | int) -> bool:
        if not self._allowed_users:
            return True
        return str(user_id) in self._allowed_users

    def wait_for_callback(self, timeout_seconds: int = 300) -> str | None:
        """Wait for an inline keyboard callback from an allowed user.

        Returns the callback_data string, or None on timeout.
        """
        if self._listener_running:
            try:
                return self._callback_queue.get(timeout=timeout_seconds)
            except queue.Empty:
                return None

        deadline = time.time() + timeout_seconds
        # Drain stale updates before waiting
        self._drain_updates()
        while time.time() < deadline:
            remaining = max(1, int(deadline - time.time()))
            poll_time = min(remaining, 30)
            updates = self.get_updates(timeout=poll_time)
            for upd in updates:
                cb = upd.get("callback_query")
                if cb:
                    user_id = cb.get("from", {}).get("id", "")
                    if not self._is_allowed(user_id):
                        logger.warning("Ignoring callback from unauthorized user %s", user_id)
                        continue
                    self.answer_callback_query(cb["id"], text=cb["data"])
                    return cb["data"]
        return None

    def wait_for_text(self, timeout_seconds: int = 600) -> str | None:
        """Wait for a text message from an allowed user.

        Returns the message text, or None on timeout.
        """
        if self._listener_running:
            try:
                return self._text_queue.get(timeout=timeout_seconds)
            except queue.Empty:
                return None

        deadline = time.time() + timeout_seconds
        # Drain stale updates before waiting
        self._drain_updates()
        while time.time() < deadline:
            remaining = max(1, int(deadline - time.time()))
            poll_time = min(remaining, 30)
            updates = self.get_updates(timeout=poll_time)
            for upd in updates:
                msg = upd.get("message")
                if msg and msg.get("text"):
                    user_id = msg.get("from", {}).get("id", "")
                    if not self._is_allowed(user_id):
                        logger.warning("Ignoring message from unauthorized user %s", user_id)
                        continue
                    return msg["text"]
        return None

    def _drain_updates(self) -> None:
        """Consume any pending updates so we only react to new ones."""
        try:
            self.get_updates(timeout=0)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Background listener
    # ------------------------------------------------------------------

    @property
    def listener_active(self) -> bool:
        return self._listener_running

    def start_listener(
        self,
        message_handler: Callable[[str], str | None] | None = None,
    ) -> None:
        """Start background polling.

        When *message_handler* is provided, every allowed text message is
        passed to it instead of being queued.  If the handler returns
        ``"SESSION_END"``, the listener stops.
        """
        if self._listener_running:
            return
        self._message_handler = message_handler
        self._drain_updates()
        self._listener_running = True
        self._listener_thread = threading.Thread(
            target=self._listener_loop, daemon=True, name="tg-listener"
        )
        self._listener_thread.start()
        logger.info("Telegram background listener started")

    def stop_listener(self) -> None:
        if not self._listener_running:
            return
        self._listener_running = False
        if self._listener_thread:
            self._listener_thread.join(timeout=35)
            self._listener_thread = None
        self._message_handler = None
        # Drain queues
        for q in (self._text_queue, self._callback_queue):
            while not q.empty():
                try:
                    q.get_nowait()
                except queue.Empty:
                    break
        logger.info("Telegram background listener stopped")

    def _listener_loop(self) -> None:
        while self._listener_running:
            try:
                updates = self.get_updates(timeout=10)
                for upd in updates:
                    self._route_update(upd)
            except Exception:
                logger.exception("Error in Telegram listener")
                if self._listener_running:
                    time.sleep(2)

    def _route_update(self, update: dict[str, Any]) -> None:
        # Callback queries → queue
        cb = update.get("callback_query")
        if cb:
            user_id = cb.get("from", {}).get("id", "")
            if not self._is_allowed(user_id):
                return
            self.answer_callback_query(cb["id"], text=cb["data"])
            self._callback_queue.put(cb["data"])
            return

        # Text messages
        msg = update.get("message")
        if not msg or not msg.get("text"):
            return
        user_id = msg.get("from", {}).get("id", "")
        if not self._is_allowed(user_id):
            return

        text: str = msg["text"]

        if self._message_handler:
            result = self._message_handler(text)
            if result == "SESSION_END":
                self._listener_running = False
        else:
            self._text_queue.put(text)
