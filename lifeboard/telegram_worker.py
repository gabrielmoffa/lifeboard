"""Telegram polling worker for remote Lifeboard prompts."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import subprocess
import threading
import traceback
import urllib.error
import urllib.parse
import urllib.request
from typing import Callable

import config as config_module
from config import get_api_key
from lifeboard.ai_interpreter import process_request

logger = logging.getLogger(__name__)


def _state_path() -> str:
    return os.path.join(config_module.CONFIG_DIR, "telegram_state.json")


def _read_state() -> dict:
    try:
        with open(_state_path()) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _write_state(state: dict):
    config_module.ensure_dirs()
    with open(_state_path(), "w") as f:
        json.dump(state, f, indent=2)


def _shell_env(name: str) -> str:
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
        return ""
    try:
        result = subprocess.run(
            ["zsh", "-lic", f'printf %s "${name}"'],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except Exception:
        return ""
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def get_token_from_env(name: str) -> str:
    return os.environ.get(name, "").strip() or _shell_env(name)


def _api_request(token: str, method: str, payload: dict, timeout: int = 35) -> dict:
    url = f"https://api.telegram.org/bot{token}/{method}"
    data = urllib.parse.urlencode(payload).encode()
    request = urllib.request.Request(url, data=data)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        data = json.loads(response.read().decode())
    if not data.get("ok", False):
        raise RuntimeError(data.get("description", f"Telegram {method} failed"))
    return data


def _message_from_update(update: dict) -> dict | None:
    return update.get("message") or update.get("channel_post")


def _message_text(message: dict) -> str:
    return (message.get("text") or message.get("caption") or "").strip()


class TelegramWorker:
    def __init__(
        self,
        app_config: dict,
        notify: Callable[[str, str], None] | None = None,
        process_prompt: Callable[[str], str | None] | None = None,
    ):
        self.config = app_config
        self.notify = notify or (lambda _title, _message: None)
        self.process_prompt = process_prompt
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        if not self.config.get("telegram_enabled", True):
            return
        if not self._token() or not self._group_id():
            return
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()

    def _token(self) -> str:
        env_name = self.config.get("telegram_bot_token_env", "MY_LIFEBOARD_BOT")
        return get_token_from_env(env_name)

    def _group_id(self) -> str:
        return str(self.config.get("telegram_group_id", "")).strip()

    def _run(self):
        token = self._token()
        group_id = self._group_id()
        state = _read_state()

        while not self._stop.is_set():
            payload = {
                "timeout": 30,
                "allowed_updates": json.dumps(["message", "channel_post"]),
            }
            if state.get("last_update_id") is not None:
                payload["offset"] = int(state["last_update_id"]) + 1

            try:
                response = _api_request(token, "getUpdates", payload, timeout=60)
                for update in response.get("result", []):
                    self._handle_update(token, group_id, update)
                    state["last_update_id"] = update["update_id"]
                    _write_state(state)
            except urllib.error.URLError as e:
                logger.warning(f"Telegram polling failed: {e}")
                self._stop.wait(10)
            except TimeoutError as e:
                logger.warning(f"Telegram polling timed out: {e}")
                self._stop.wait(10)
            except Exception:
                logger.error(traceback.format_exc())
                self._stop.wait(10)

    def _handle_update(self, token: str, group_id: str, update: dict):
        message = _message_from_update(update)
        if not message:
            return

        chat_id = str(message.get("chat", {}).get("id", ""))
        if chat_id != group_id:
            logger.info(f"Telegram update ignored from chat {chat_id}")
            return

        text = _message_text(message)
        if not text:
            return
        logger.info(f"Telegram prompt from chat {chat_id}: {text[:200]}")

        api_key = get_api_key(self.config)
        if not api_key:
            self._send_message(token, chat_id, "Lifeboard has no AI API key configured.")
            self.notify("Lifeboard Telegram", "No AI API key configured.")
            return

        try:
            if self.process_prompt:
                result = self.process_prompt(text)
            else:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    result = loop.run_until_complete(process_request(text, api_key))
                finally:
                    loop.close()
            if result:
                logger.info(f"Telegram prompt returned message: {result[:200]}")
                self._send_message(token, chat_id, result)
            else:
                logger.info("Telegram prompt completed with no message")
        except Exception as e:
            logger.error(traceback.format_exc())
            msg = str(e)[:500]
            self.notify("Lifeboard Telegram Error", msg[:200])
            self._send_message(token, chat_id, f"Lifeboard error: {msg}")

    def _send_message(self, token: str, chat_id: str, text: str):
        try:
            _api_request(
                token,
                "sendMessage",
                {"chat_id": chat_id, "text": text[:4096]},
                timeout=10,
            )
        except Exception:
            logger.warning("Failed to send Telegram message", exc_info=True)
