"""Manage and send scheduled football polls in a Telegram group."""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from argparse import ArgumentParser
from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


TELEGRAM_API_BASE_URL = "https://api.telegram.org/bot{token}/{method}"
REQUEST_TIMEOUT_SECONDS = 30
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DOTENV_PATH = PROJECT_ROOT / ".env"
DATA_DIR = PROJECT_ROOT / "data"
SCHEDULE_PATH = DATA_DIR / "schedule.json"
STATE_PATH = DATA_DIR / "state.json"

DEFAULT_SCHEDULE = {
    "weekday": 1,  # Tuesday, Monday=0
    "time": "18:00",
    "timezone": "Asia/Ho_Chi_Minh",
}

SUPPORTED_COMMANDS = (
    "/set_schedule <thu> <HH:MM>",
    "/set_day <thu>",
    "/set_time <HH:MM>",
    "/set_timezone <IANA timezone>",
    "/status",
    "/help",
)

WEEKDAY_ALIASES = {
    "mon": 0,
    "monday": 0,
    "2": 0,
    "tue": 1,
    "tuesday": 1,
    "3": 1,
    "wed": 2,
    "wednesday": 2,
    "4": 2,
    "thu": 3,
    "thursday": 3,
    "5": 3,
    "fri": 4,
    "friday": 4,
    "6": 4,
    "sat": 5,
    "saturday": 5,
    "7": 5,
    "sun": 6,
    "sunday": 6,
    "cn": 6,
    "chunhat": 6,
    "chu_nhat": 6,
    "chunhat.": 6,
    "8": 6,
}

WEEKDAY_LABELS = {
    0: "Monday",
    1: "Tuesday",
    2: "Wednesday",
    3: "Thursday",
    4: "Friday",
    5: "Saturday",
    6: "Sunday",
}


class ConfigurationError(ValueError):
    """Raised when required environment configuration is missing."""


class TelegramAPIError(RuntimeError):
    """Raised when the Telegram request cannot create a poll."""


class ScheduleError(ValueError):
    """Raised when schedule input is malformed."""


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


def _ensure_data_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def _read_json_file(path: Path, fallback: dict[str, Any]) -> dict[str, Any]:
    if not path.is_file():
        return dict(fallback)
    try:
        with path.open(encoding="utf-8") as file:
            data = json.load(file)
    except (OSError, json.JSONDecodeError):
        return dict(fallback)
    return data if isinstance(data, dict) else dict(fallback)


def _write_json_file(path: Path, data: dict[str, Any]) -> None:
    _ensure_data_dir()
    with path.open("w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=2)
        file.write("\n")


def _parse_weekday(value: str) -> int:
    normalized = value.strip().lower().replace(" ", "")
    if normalized not in WEEKDAY_ALIASES:
        raise ScheduleError(f"Invalid weekday: {value}")
    return WEEKDAY_ALIASES[normalized]


def _parse_time(value: str) -> tuple[int, int]:
    raw = value.strip()
    hour_text, sep, minute_text = raw.partition(":")
    if not sep or not hour_text.isdigit() or not minute_text.isdigit():
        raise ScheduleError(f"Invalid time format: {value}")
    hour = int(hour_text)
    minute = int(minute_text)
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ScheduleError(f"Invalid time value: {value}")
    return hour, minute


def _normalize_timezone(value: str) -> str:
    timezone = value.strip()
    if not timezone:
        raise ScheduleError("Timezone cannot be empty")
    try:
        ZoneInfo(timezone)
    except ZoneInfoNotFoundError as exc:
        raise ScheduleError(f"Unknown timezone: {value}") from exc
    return timezone


def _normalize_schedule(raw_schedule: Mapping[str, Any]) -> dict[str, Any]:
    weekday = int(raw_schedule.get("weekday", DEFAULT_SCHEDULE["weekday"]))
    if weekday not in WEEKDAY_LABELS:
        raise ScheduleError("weekday must be an integer from 0 to 6")
    hour, minute = _parse_time(str(raw_schedule.get("time", DEFAULT_SCHEDULE["time"])))
    timezone = _normalize_timezone(
        str(raw_schedule.get("timezone", DEFAULT_SCHEDULE["timezone"]))
    )
    return {
        "weekday": weekday,
        "time": f"{hour:02d}:{minute:02d}",
        "timezone": timezone,
    }


def load_schedule() -> dict[str, Any]:
    return _normalize_schedule(_read_json_file(SCHEDULE_PATH, DEFAULT_SCHEDULE))


def save_schedule(schedule: Mapping[str, Any]) -> dict[str, Any]:
    normalized = _normalize_schedule(schedule)
    _write_json_file(SCHEDULE_PATH, normalized)
    return normalized


def load_state() -> dict[str, Any]:
    state = _read_json_file(
        STATE_PATH,
        {"last_update_id": 0, "last_sent_slot": ""},
    )
    return {
        "last_update_id": int(state.get("last_update_id", 0)),
        "last_sent_slot": str(state.get("last_sent_slot", "")),
    }


def save_state(state: Mapping[str, Any]) -> dict[str, Any]:
    normalized = {
        "last_update_id": int(state.get("last_update_id", 0)),
        "last_sent_slot": str(state.get("last_sent_slot", "")),
    }
    _write_json_file(STATE_PATH, normalized)
    return normalized


def _call_telegram_api(
    token: str,
    method: str,
    payload: Mapping[str, Any],
    opener: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """Call a Telegram Bot API method and return its successful response."""
    request = urllib.request.Request(
        TELEGRAM_API_BASE_URL.format(token=token, method=method),
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
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


def send_poll(
    token: str,
    chat_id: str,
    opener: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """Send the configured poll and return Telegram's successful response."""
    return _call_telegram_api(token, "sendPoll", build_poll_payload(chat_id), opener=opener)


def send_message(
    token: str,
    chat_id: str,
    text: str,
    opener: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    return _call_telegram_api(
        token,
        "sendMessage",
        {"chat_id": chat_id, "text": text},
        opener=opener,
    )


def get_updates(
    token: str,
    offset: int,
    opener: Callable[..., Any] | None = None,
) -> list[dict[str, Any]]:
    response = _call_telegram_api(
        token,
        "getUpdates",
        {"offset": offset, "timeout": 0, "allowed_updates": ["message"]},
        opener=opener,
    )
    result = response.get("result")
    return result if isinstance(result, list) else []


def _weekday_label(weekday: int) -> str:
    return WEEKDAY_LABELS.get(weekday, f"weekday={weekday}")


def format_schedule(schedule: Mapping[str, Any]) -> str:
    return (
        "Current schedule:\n"
        f"- Day: {_weekday_label(int(schedule['weekday']))}\n"
        f"- Time: {schedule['time']}\n"
        f"- Timezone: {schedule['timezone']}"
    )


def _extract_message_text(update: Mapping[str, Any]) -> str:
    message = update.get("message")
    if not isinstance(message, Mapping):
        return ""
    text = message.get("text")
    return text.strip() if isinstance(text, str) else ""


def _extract_chat_id(update: Mapping[str, Any]) -> str:
    message = update.get("message")
    if not isinstance(message, Mapping):
        return ""
    chat = message.get("chat")
    if not isinstance(chat, Mapping):
        return ""
    chat_id = chat.get("id")
    return str(chat_id).strip() if chat_id is not None else ""


def _parse_set_schedule(text: str) -> tuple[int, str]:
    _, _, argument_string = text.partition(" ")
    parts = [part for part in argument_string.split() if part]
    if len(parts) != 2:
        raise ScheduleError("Usage: /set_schedule <thu> <HH:MM>")
    weekday = _parse_weekday(parts[0])
    hour, minute = _parse_time(parts[1])
    return weekday, f"{hour:02d}:{minute:02d}"


def handle_command(text: str, current_schedule: Mapping[str, Any]) -> tuple[dict[str, Any], str]:
    schedule = dict(current_schedule)
    command, _, arguments = text.partition(" ")
    command = command.strip().lower()
    args = arguments.strip()

    if command == "/set_schedule":
        weekday, time_value = _parse_set_schedule(text)
        schedule["weekday"] = weekday
        schedule["time"] = time_value
        return schedule, "Schedule updated.\n" + format_schedule(schedule)

    if command == "/set_day":
        if not args:
            raise ScheduleError("Usage: /set_day <thu>")
        schedule["weekday"] = _parse_weekday(args)
        return schedule, "Day updated.\n" + format_schedule(schedule)

    if command == "/set_time":
        if not args:
            raise ScheduleError("Usage: /set_time <HH:MM>")
        hour, minute = _parse_time(args)
        schedule["time"] = f"{hour:02d}:{minute:02d}"
        return schedule, "Time updated.\n" + format_schedule(schedule)

    if command == "/set_timezone":
        if not args:
            raise ScheduleError("Usage: /set_timezone <IANA timezone>")
        schedule["timezone"] = _normalize_timezone(args)
        return schedule, "Timezone updated.\n" + format_schedule(schedule)

    if command == "/status":
        return schedule, format_schedule(schedule)

    if command == "/help":
        return schedule, "Supported commands:\n- " + "\n- ".join(SUPPORTED_COMMANDS)

    raise ScheduleError(
        f"Unknown command: {command}\nSupported commands:\n- "
        + "\n- ".join(SUPPORTED_COMMANDS)
    )


def process_updates(
    token: str,
    configured_chat_id: str,
    schedule: Mapping[str, Any],
    state: Mapping[str, Any],
    opener: Callable[..., Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    new_schedule = dict(schedule)
    new_state = dict(state)
    updates = get_updates(token, int(state["last_update_id"]) + 1, opener=opener)

    for update in updates:
        update_id = update.get("update_id")
        if isinstance(update_id, int):
            new_state["last_update_id"] = max(int(new_state["last_update_id"]), update_id)

        chat_id = _extract_chat_id(update)
        if chat_id != configured_chat_id:
            continue

        text = _extract_message_text(update)
        if not text.startswith("/"):
            continue

        try:
            candidate_schedule, reply_text = handle_command(text, new_schedule)
            new_schedule = _normalize_schedule(candidate_schedule)
            send_message(token, configured_chat_id, reply_text, opener=opener)
        except ScheduleError as exc:
            send_message(token, configured_chat_id, f"Error: {exc}", opener=opener)

    return new_schedule, new_state


def should_send_now(
    schedule: Mapping[str, Any],
    now_utc: datetime | None = None,
) -> tuple[bool, str]:
    now = datetime.now(UTC) if now_utc is None else now_utc.astimezone(UTC)
    timezone = ZoneInfo(str(schedule["timezone"]))
    local_now = now.astimezone(timezone)
    if local_now.weekday() != int(schedule["weekday"]):
        return False, ""

    hour, minute = _parse_time(str(schedule["time"]))
    scheduled_time = local_now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    window_end = scheduled_time + timedelta(minutes=9)
    if not (scheduled_time <= local_now <= window_end):
        return False, ""

    return True, scheduled_time.strftime("%Y-%m-%d-%H:%M")


def run_scheduler_cycle(
    environ: Mapping[str, str] | None = None,
    opener: Callable[..., Any] | None = None,
) -> int:
    if environ is None:
        load_dotenv()

    token, chat_id = load_config(environ)
    schedule = load_schedule()
    state = load_state()

    updated_schedule, updated_state = process_updates(
        token, chat_id, schedule, state, opener=opener
    )
    if updated_schedule != schedule:
        save_schedule(updated_schedule)
    should_send, send_slot = should_send_now(updated_schedule)
    if should_send and updated_state["last_sent_slot"] != send_slot:
        send_poll(token, chat_id, opener=opener)
        updated_state["last_sent_slot"] = send_slot
        print(f"Football poll sent for slot {send_slot}.")
    else:
        print("No poll sent in this scheduler cycle.")

    save_state(updated_state)
    return 0


def main(
    environ: Mapping[str, str] | None = None,
    opener: Callable[..., Any] | None = None,
    argv: list[str] | None = None,
) -> int:
    """Run one poll send or one scheduler cycle."""
    parser = ArgumentParser(description="Send Telegram football poll")
    parser.add_argument(
        "--mode",
        choices=("once", "scheduler"),
        default="once",
        help="once: send poll immediately, scheduler: process commands and schedule",
    )
    args = parser.parse_args(argv)
    try:
        if args.mode == "scheduler":
            return run_scheduler_cycle(environ=environ, opener=opener)

        if environ is None:
            load_dotenv()
        token, chat_id = load_config(environ)
        send_poll(token, chat_id, opener=opener)
    except (ConfigurationError, TelegramAPIError, ScheduleError) as exc:
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
