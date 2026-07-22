"""Create the weekly football poll in a Telegram group."""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any


TELEGRAM_API_BASE_URL = "https://api.telegram.org/bot{token}/sendPoll"
REQUEST_TIMEOUT_SECONDS = 30
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DOTENV_PATH = PROJECT_ROOT / ".env"


class ConfigurationError(ValueError):
    """Raised when required environment configuration is missing."""


class TelegramAPIError(RuntimeError):
    """Raised when the Telegram request cannot create a poll."""


def build_poll_payload(chat_id: str) -> dict[str, Any]:
    """Return the exact poll payload required by the weekly football vote."""
    return {
        "chat_id": chat_id,
        "question": "Đá bóng",
        "options": ["Đi", "Không đi"],
        "type": "regular",
        "is_anonymous": False,
        "allows_multiple_answers": False,
        "allow_adding_options": False,
    }


def load_dotenv(path: str | os.PathLike[str] | None = None) -> None:
    """Load KEY=VALUE pairs from a .env file when variables are not already set."""
    dotenv_path = DEFAULT_DOTENV_PATH if path is None else Path(path)
    if not dotenv_path.is_file():
        return

    with dotenv_path.open(encoding="utf-8") as env_file:
        for line in env_file:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            key, separator, value = line.partition("=")
            if not separator:
                continue
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value


def load_config(environ: Mapping[str, str] | None = None) -> tuple[str, str]:
    """Load and validate the Telegram token and target chat ID."""
    values = os.environ if environ is None else environ
    token = values.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = values.get("TELEGRAM_CHAT_ID", "").strip()

    missing = [
        name
        for name, value in (
            ("TELEGRAM_BOT_TOKEN", token),
            ("TELEGRAM_CHAT_ID", chat_id),
        )
        if not value
    ]
    if missing:
        raise ConfigurationError(
            "Missing required environment variable(s): " + ", ".join(missing)
        )

    return token, chat_id


def _decode_response(raw_body: bytes) -> dict[str, Any]:
    try:
        response = json.loads(raw_body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TelegramAPIError("Telegram returned an invalid JSON response") from exc

    if not isinstance(response, dict):
        raise TelegramAPIError("Telegram returned an unexpected response")
    return response


def _http_error_detail(error: urllib.error.HTTPError) -> str:
    try:
        body = error.read().decode("utf-8", errors="replace").strip()
    except OSError:
        body = ""
    return f"HTTP {error.code}" + (f": {body}" if body else "")


def send_poll(
    token: str,
    chat_id: str,
    opener: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """Send the configured poll and return Telegram's successful response."""
    request = urllib.request.Request(
        TELEGRAM_API_BASE_URL.format(token=token),
        data=json.dumps(build_poll_payload(chat_id), ensure_ascii=False).encode("utf-8"),
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    open_url = urllib.request.urlopen if opener is None else opener
    try:
        with open_url(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            status = getattr(response, "status", 200)
            raw_body = response.read()
    except urllib.error.HTTPError as exc:
        raise TelegramAPIError(_http_error_detail(exc)) from exc
    except (TimeoutError, urllib.error.URLError, OSError) as exc:
        raise TelegramAPIError(f"Telegram request failed: {exc}") from exc

    if not 200 <= status < 300:
        raise TelegramAPIError(f"HTTP {status}")

    response = _decode_response(raw_body)
    if response.get("ok") is not True:
        description = response.get("description", "unknown Telegram API error")
        raise TelegramAPIError(f"Telegram API error: {description}")

    return response


def main(
    environ: Mapping[str, str] | None = None,
    opener: Callable[..., Any] | None = None,
) -> int:
    """Send the poll and return a process exit code."""
    if environ is None:
        load_dotenv()

    try:
        token, chat_id = load_config(environ)
        send_poll(token, chat_id, opener=opener)
    except (ConfigurationError, TelegramAPIError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        if isinstance(exc, TelegramAPIError) and "HTTP 404" in str(exc):
            print(
                "Hint: HTTP 404 thường do TELEGRAM_BOT_TOKEN sai. "
                "Kiểm tra lại token từ BotFather trong file .env.",
                file=sys.stderr,
            )
        return 1

    print("Football poll sent successfully.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
