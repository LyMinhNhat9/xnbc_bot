import io
import json
import unittest
from datetime import UTC, datetime
from urllib.error import HTTPError

from src.send_poll import (
    ConfigurationError,
    ScheduleError,
    TelegramAPIError,
    build_poll_payload,
    handle_command,
    load_config,
    send_poll,
    should_send_now,
)


class FakeResponse:
    status = 200

    def __init__(self, body):
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def read(self):
        return self._body


class SendPollTests(unittest.TestCase):
    def test_build_poll_payload_has_exact_non_anonymous_single_choice_options(self):
        self.assertEqual(
            build_poll_payload("-1001234567890"),
            {
                "chat_id": "-1001234567890",
                "question": "Đá bóng",
                "options": ["Đi", "Không đi"],
                "type": "regular",
                "is_anonymous": False,
                "allows_multiple_answers": False,
                "allow_adding_options": False,
            },
        )

    def test_load_config_rejects_missing_required_values(self):
        with self.subTest("missing token"):
            with self.assertRaisesRegex(ConfigurationError, "TELEGRAM_BOT_TOKEN"):
                load_config({"TELEGRAM_CHAT_ID": "-1001234567890"})

        with self.subTest("missing chat id"):
            with self.assertRaisesRegex(ConfigurationError, "TELEGRAM_CHAT_ID"):
                load_config({"TELEGRAM_BOT_TOKEN": "secret"})

    def test_send_poll_posts_json_payload_and_returns_success_response(self):
        captured = {}

        def opener(request, timeout):
            captured["request"] = request
            captured["timeout"] = timeout
            return FakeResponse(
                json.dumps({"ok": True, "result": {"message_id": 42}}).encode()
            )

        result = send_poll("bot-token", "-1001234567890", opener=opener)

        self.assertEqual(result, {"ok": True, "result": {"message_id": 42}})
        self.assertEqual(captured["timeout"], 30)
        self.assertEqual(
            json.loads(captured["request"].data.decode("utf-8")),
            build_poll_payload("-1001234567890"),
        )
        self.assertEqual(
            captured["request"].full_url,
            "https://api.telegram.org/botbot-token/sendPoll",
        )

    def test_send_poll_raises_for_telegram_api_error(self):
        def opener(request, timeout):
            return FakeResponse(
                json.dumps({"ok": False, "error_code": 400, "description": "Bad Request"}).encode()
            )

        with self.assertRaisesRegex(TelegramAPIError, "Bad Request"):
            send_poll("bot-token", "-1001234567890", opener=opener)

    def test_send_poll_raises_for_http_error(self):
        def opener(request, timeout):
            raise HTTPError(
                request.full_url,
                500,
                "Internal Server Error",
                hdrs=None,
                fp=io.BytesIO(b"upstream failure"),
            )

        with self.assertRaisesRegex(TelegramAPIError, "HTTP 500"):
            send_poll("bot-token", "-1001234567890", opener=opener)

    def test_send_poll_raises_for_network_timeout(self):
        def opener(request, timeout):
            raise TimeoutError("timed out")

        with self.assertRaisesRegex(TelegramAPIError, "timed out"):
            send_poll("bot-token", "-1001234567890", opener=opener)

    def test_handle_command_updates_day_and_time(self):
        schedule, message = handle_command(
            "/set_schedule tue 19:30",
            {"weekday": 1, "time": "18:00", "timezone": "Asia/Ho_Chi_Minh"},
        )

        self.assertEqual(schedule["weekday"], 1)
        self.assertEqual(schedule["time"], "19:30")
        self.assertIn("Schedule updated", message)

    def test_handle_command_rejects_unknown(self):
        with self.assertRaises(ScheduleError):
            handle_command(
                "/abc",
                {"weekday": 1, "time": "18:00", "timezone": "Asia/Ho_Chi_Minh"},
            )

    def test_should_send_now_within_window(self):
        schedule = {"weekday": 1, "time": "18:00", "timezone": "Asia/Ho_Chi_Minh"}
        now_utc = datetime(2026, 7, 21, 11, 4, tzinfo=UTC)

        should_send, slot = should_send_now(schedule, now_utc=now_utc)

        self.assertTrue(should_send)
        self.assertEqual(slot, "2026-07-21-18:00")

    def test_should_not_send_on_wrong_day(self):
        schedule = {"weekday": 1, "time": "18:00", "timezone": "Asia/Ho_Chi_Minh"}
        now_utc = datetime(2026, 7, 22, 11, 2, tzinfo=UTC)

        should_send, slot = should_send_now(schedule, now_utc=now_utc)

        self.assertFalse(should_send)
        self.assertEqual(slot, "")


if __name__ == "__main__":
    unittest.main()
