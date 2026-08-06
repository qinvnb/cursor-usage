from __future__ import annotations

import time
import unittest

from cursor_usage_app.component_supervisor import ComponentSupervisor


class FakeProcess:
    def __init__(self) -> None:
        self.code: int | None = None
        self.terminated = False

    def poll(self) -> int | None:
        return self.code

    def terminate(self) -> None:
        self.terminated = True
        self.code = 0

    def wait(self, timeout: float | None = None) -> int:
        return int(self.code or 0)

    def kill(self) -> None:
        self.code = -9


class ComponentSupervisorTests(unittest.TestCase):
    def test_starts_and_stops_desired_component(self) -> None:
        created: list[FakeProcess] = []

        def spawn() -> FakeProcess:
            proc = FakeProcess()
            created.append(proc)
            return proc

        sup = ComponentSupervisor(
            "test",
            spawn,  # type: ignore[arg-type]
            backoff=(0.01,),
            cooldown_seconds=0.02,
        )
        try:
            sup.set_desired(True)
            deadline = time.time() + 1
            while time.time() < deadline and sup.process() is None:
                time.sleep(0.01)
            self.assertIsNotNone(sup.process())
            sup.set_desired(False)
            deadline = time.time() + 1
            while time.time() < deadline and sup.process() is not None:
                time.sleep(0.01)
            self.assertTrue(created[0].terminated)
        finally:
            sup.stop()

    def test_restarts_after_crash(self) -> None:
        created: list[FakeProcess] = []

        def spawn() -> FakeProcess:
            proc = FakeProcess()
            created.append(proc)
            return proc

        sup = ComponentSupervisor(
            "test",
            spawn,  # type: ignore[arg-type]
            backoff=(0.01,),
            cooldown_seconds=0.02,
            stable_seconds=10,
        )
        try:
            sup.set_desired(True)
            deadline = time.time() + 1
            while time.time() < deadline and not created:
                time.sleep(0.01)
            created[0].code = 1
            deadline = time.time() + 1
            while time.time() < deadline and len(created) < 2:
                time.sleep(0.01)
            self.assertGreaterEqual(len(created), 2)
        finally:
            sup.stop()


if __name__ == "__main__":
    unittest.main()
