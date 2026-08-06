from __future__ import annotations

import threading
import time
import unittest
import uuid

from cursor_usage_app.instance import SingleInstance, send_command, start_or_notify


def unique_app_id() -> str:
    return f"cursor-usage-test-{uuid.uuid4().hex}"


class SingleInstanceTests(unittest.TestCase):
    def test_only_one_owner_and_close_releases_ownership(self) -> None:
        app_id = unique_app_id()
        first = SingleInstance(app_id)
        second = SingleInstance(app_id)
        third = SingleInstance(app_id)
        try:
            self.assertTrue(first.acquire())
            self.assertFalse(second.acquire())
            first.close()
            self.assertTrue(third.acquire())
        finally:
            first.close()
            second.close()
            third.close()

    def test_listener_dispatches_all_supported_commands(self) -> None:
        app_id = unique_app_id()
        received: list[tuple[str, dict[str, object]]] = []
        event = threading.Event()

        def callback(command: str, payload: dict[str, object]) -> None:
            received.append((command, payload))
            if len(received) == 5:
                event.set()

        primary = SingleInstance(app_id)
        self.assertTrue(primary.start(callback))
        try:
            commands = ("show-main", "refresh", "hide-ball", "hide-dock", "quit")
            for index, command in enumerate(commands):
                self.assertTrue(
                    send_command(
                        command,
                        {"index": index},
                        app_id=app_id,
                        timeout=2.0,
                    )
                )
            self.assertTrue(event.wait(2.0))
            self.assertEqual([item[0] for item in received], list(commands))
            self.assertEqual(received[1][1], {"index": 1})
        finally:
            primary.close()

    def test_late_callback_registration(self) -> None:
        app_id = unique_app_id()
        primary = SingleInstance(app_id)
        called = threading.Event()
        self.assertTrue(primary.start())
        primary.register_callback(
            lambda command, payload: called.set()
            if command == "refresh" and payload == {"source": "test"}
            else None
        )
        try:
            self.assertTrue(
                send_command(
                    "refresh",
                    {"source": "test"},
                    app_id=app_id,
                    timeout=2.0,
                )
            )
            self.assertTrue(called.wait(1.0))
        finally:
            primary.close()

    def test_start_or_notify_sends_show_main(self) -> None:
        app_id = unique_app_id()
        shown = threading.Event()
        primary = start_or_notify(
            lambda command, payload: shown.set() if command == "show-main" else None,
            app_id=app_id,
        )
        self.assertIsNotNone(primary)
        try:
            secondary = start_or_notify(app_id=app_id)
            self.assertIsNone(secondary)
            self.assertTrue(shown.wait(2.0))
        finally:
            assert primary is not None
            primary.close()

    def test_validation_limits_and_missing_server_timeout(self) -> None:
        app_id = unique_app_id()
        client = SingleInstance(app_id, max_message_size=128, io_timeout=0.15)
        with self.assertRaises(ValueError):
            client.send("unknown")
        with self.assertRaises(ValueError):
            client.send("refresh", {"large": "x" * 256})

        started = time.monotonic()
        self.assertFalse(client.send("show-main", timeout=0.15, retries=2))
        self.assertLess(time.monotonic() - started, 1.0)
        client.close()

    def test_callback_failure_is_reported_without_stopping_listener(self) -> None:
        app_id = unique_app_id()
        fail = True

        def callback(command: str, payload: dict[str, object]) -> None:
            nonlocal fail
            if fail:
                fail = False
                raise RuntimeError("expected")

        primary = SingleInstance(app_id)
        self.assertTrue(primary.start(callback))
        try:
            self.assertFalse(send_command("refresh", app_id=app_id))
            self.assertTrue(send_command("refresh", app_id=app_id))
        finally:
            primary.close()


if __name__ == "__main__":
    unittest.main()
