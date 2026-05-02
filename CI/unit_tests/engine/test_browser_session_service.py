from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from software.core.engine.browser_session_service import BrowserSessionService


class _FakeSemaphore:
    def __init__(self) -> None:
        self.acquired = 0
        self.released = 0

    def acquire(self) -> None:
        self.acquired += 1

    def release(self) -> None:
        self.released += 1


class _FakeState:
    def __init__(self) -> None:
        self.semaphore = _FakeSemaphore()
        self.released_threads: list[str] = []

    def get_browser_semaphore(self, _count: int) -> _FakeSemaphore:
        return self.semaphore

    def release_proxy_in_use(self, thread_name: str) -> None:
        self.released_threads.append(thread_name)


class _FakeDriver:
    def __init__(self) -> None:
        self.window_sizes: list[tuple[int, int]] = []
        self.cleanup_marked = False
        self.quit_calls = 0

    def set_window_size(self, width: int, height: int) -> None:
        self.window_sizes.append((width, height))

    def mark_cleanup_done(self) -> bool:
        if self.cleanup_marked:
            return False
        self.cleanup_marked = True
        return True

    def quit(self) -> None:
        self.quit_calls += 1


class _FakeGui:
    def __init__(self) -> None:
        self.active_drivers: list[_FakeDriver] = []


class _FakeBrowserOwner:
    def __init__(self, driver: _FakeDriver, browser_name: str = "edge") -> None:
        self.driver = driver
        self.browser_name = browser_name
        self.open_session_calls: list[dict[str, str]] = []

    def open_session(self, *, proxy_address=None, user_agent=None):
        self.open_session_calls.append(
            {
                "proxy_address": proxy_address,
                "user_agent": user_agent,
            }
        )
        return self.driver


class BrowserSessionServiceTests(unittest.TestCase):
    def _build_config(self, *, headless_mode: bool) -> SimpleNamespace:
        return SimpleNamespace(
            headless_mode=headless_mode,
            random_proxy_ip_enabled=False,
            num_threads=1,
        )

    def test_create_browser_keeps_headless_viewport(self) -> None:
        state = _FakeState()
        config = self._build_config(headless_mode=True)
        fake_driver = _FakeDriver()
        service = BrowserSessionService(config, state, gui_instance=None, thread_name="Worker-1")

        with patch("software.core.engine.browser_session_service._select_proxy_for_session", return_value=None), \
             patch("software.core.engine.browser_session_service._select_user_agent_for_session", return_value=("", "")), \
             patch("software.core.engine.browser_session_service.create_browser_manager", return_value=object()), \
             patch("software.core.engine.browser_session_service.create_playwright_driver", return_value=(fake_driver, "edge")):
            browser_name = service.create_browser(["edge"], 0, 0)

        self.assertEqual(browser_name, "edge")
        self.assertEqual(fake_driver.window_sizes, [])

    def test_create_browser_resizes_headed_window(self) -> None:
        state = _FakeState()
        config = self._build_config(headless_mode=False)
        fake_driver = _FakeDriver()
        service = BrowserSessionService(config, state, gui_instance=None, thread_name="Worker-1")

        with patch("software.core.engine.browser_session_service._select_proxy_for_session", return_value=None), \
             patch("software.core.engine.browser_session_service._select_user_agent_for_session", return_value=("", "")), \
             patch("software.core.engine.browser_session_service.create_browser_manager", return_value=object()), \
             patch("software.core.engine.browser_session_service.create_playwright_driver", return_value=(fake_driver, "edge")):
            browser_name = service.create_browser(["edge"], 0, 0)

        self.assertEqual(browser_name, "edge")
        self.assertEqual(fake_driver.window_sizes, [(550, 650)])

    def test_create_browser_keeps_same_proxy_for_headless_browser_and_submit(self) -> None:
        state = _FakeState()
        config = SimpleNamespace(
            headless_mode=True,
            random_proxy_ip_enabled=True,
            num_threads=1,
        )
        fake_driver = _FakeDriver()
        service = BrowserSessionService(config, state, gui_instance=None, thread_name="Worker-1")

        with patch("software.core.engine.browser_session_service._select_proxy_for_session", return_value="http://1.1.1.1:8000"), \
             patch("software.core.engine.browser_session_service.is_proxy_responsive", return_value=True), \
             patch("software.core.engine.browser_session_service._select_user_agent_for_session", return_value=("", "")), \
             patch("software.core.engine.browser_session_service.create_browser_manager", return_value=object()), \
             patch("software.core.engine.browser_session_service.create_playwright_driver", return_value=(fake_driver, "edge")) as create_driver_mock:
            browser_name = service.create_browser(["edge"], 0, 0)

        self.assertEqual(browser_name, "edge")
        self.assertEqual(create_driver_mock.call_args.kwargs["proxy_address"], "http://1.1.1.1:8000")
        self.assertEqual(getattr(fake_driver, "_submit_proxy_address", None), "http://1.1.1.1:8000")
        self.assertEqual(getattr(fake_driver, "_thread_name", None), "Worker-1")

    def test_dispose_without_driver_releases_proxy_and_semaphore(self) -> None:
        state = _FakeState()
        config = self._build_config(headless_mode=True)
        service = BrowserSessionService(config, state, gui_instance=None, thread_name="Worker-1")
        service.proxy_address = "127.0.0.1:8888"
        service.sem_acquired = True

        service.dispose()

        self.assertIsNone(service.proxy_address)
        self.assertFalse(service.sem_acquired)
        self.assertEqual(state.released_threads, ["Worker-1"])
        self.assertEqual(state.semaphore.released, 1)

    def test_dispose_unregisters_driver_and_releases_resources(self) -> None:
        state = _FakeState()
        config = self._build_config(headless_mode=True)
        gui = _FakeGui()
        fake_driver = _FakeDriver()
        gui.active_drivers.append(fake_driver)
        service = BrowserSessionService(config, state, gui_instance=gui, thread_name="Worker-1")
        service.driver = fake_driver
        service.proxy_address = "127.0.0.1:8888"
        service.sem_acquired = True

        service.dispose()

        self.assertIsNone(service.driver)
        self.assertEqual(fake_driver.quit_calls, 1)
        self.assertEqual(gui.active_drivers, [])
        self.assertEqual(state.released_threads, ["Worker-1"])
        self.assertEqual(state.semaphore.released, 1)

    def test_dispose_skips_already_cleaned_driver(self) -> None:
        state = _FakeState()
        config = self._build_config(headless_mode=True)
        fake_driver = _FakeDriver()
        fake_driver.cleanup_marked = True
        service = BrowserSessionService(config, state, gui_instance=None, thread_name="Worker-1")
        service.driver = fake_driver
        service.sem_acquired = True

        service.dispose()

        self.assertIsNone(service.driver)
        self.assertEqual(fake_driver.quit_calls, 0)
        self.assertEqual(state.semaphore.released, 1)

    def test_shutdown_closes_browser_manager_and_clears_reference(self) -> None:
        state = _FakeState()
        config = self._build_config(headless_mode=True)
        manager = object()
        service = BrowserSessionService(config, state, gui_instance=None, thread_name="Worker-1")
        service._browser_manager = manager

        with patch("software.core.engine.browser_session_service.shutdown_browser_manager") as shutdown_mock:
            service.shutdown()

        shutdown_mock.assert_called_once_with(manager)
        self.assertIsNone(service._browser_manager)

    def test_create_browser_returns_none_when_random_proxy_is_missing_and_paused(self) -> None:
        state = _FakeState()
        config = SimpleNamespace(
            headless_mode=True,
            random_proxy_ip_enabled=True,
            num_threads=1,
        )
        service = BrowserSessionService(config, state, gui_instance=None, thread_name="Worker-1")

        with patch("software.core.engine.browser_session_service._select_proxy_for_session", return_value=None), \
             patch("software.core.engine.browser_session_service._record_bad_proxy_and_maybe_pause", return_value=True):
            browser_name = service.create_browser(["edge"], 0, 0)

        self.assertIsNone(browser_name)
        self.assertEqual(state.semaphore.acquired, 0)

    def test_create_browser_discards_unresponsive_proxy(self) -> None:
        state = _FakeState()
        config = SimpleNamespace(
            headless_mode=True,
            random_proxy_ip_enabled=True,
            num_threads=1,
        )
        service = BrowserSessionService(config, state, gui_instance=None, thread_name="Worker-1")

        with patch("software.core.engine.browser_session_service._select_proxy_for_session", return_value="127.0.0.1:8888"), \
             patch("software.core.engine.browser_session_service.is_proxy_responsive", return_value=False), \
             patch("software.core.engine.browser_session_service._discard_unresponsive_proxy") as discard_mock, \
             patch("software.core.engine.browser_session_service._record_bad_proxy_and_maybe_pause") as record_bad_mock:
            browser_name = service.create_browser(["edge"], 0, 0)

        self.assertIsNone(browser_name)
        discard_mock.assert_called_once_with(state, "127.0.0.1:8888")
        record_bad_mock.assert_called_once()
        self.assertEqual(state.released_threads, ["Worker-1"])

    def test_create_browser_retries_next_proxy_when_runtime_wait_mode_hits_bad_proxy(self) -> None:
        state = _FakeState()
        config = SimpleNamespace(
            headless_mode=True,
            random_proxy_ip_enabled=True,
            num_threads=1,
        )
        fake_driver = _FakeDriver()
        service = BrowserSessionService(config, state, gui_instance=None, thread_name="Worker-1")

        with (
            patch(
                "software.core.engine.browser_session_service._select_proxy_for_session",
                side_effect=["http://1.1.1.1:8000", "http://2.2.2.2:8000"],
            ),
            patch(
                "software.core.engine.browser_session_service.is_proxy_responsive",
                side_effect=[False, True],
            ),
            patch("software.core.engine.browser_session_service._discard_unresponsive_proxy") as discard_mock,
            patch("software.core.engine.browser_session_service._select_user_agent_for_session", return_value=("", "")),
            patch("software.core.engine.browser_session_service.create_browser_manager", return_value=object()),
            patch("software.core.engine.browser_session_service.create_playwright_driver", return_value=(fake_driver, "edge")),
        ):
            browser_name = service.create_browser(["edge"], 0, 0, stop_signal=SimpleNamespace(is_set=lambda: False))

        self.assertEqual(browser_name, "edge")
        self.assertEqual(discard_mock.call_count, 1)
        self.assertEqual(state.released_threads, ["Worker-1"])
        self.assertEqual(getattr(fake_driver, "_session_proxy_address", None), "http://2.2.2.2:8000")

    def test_create_browser_releases_semaphore_when_driver_creation_fails(self) -> None:
        state = _FakeState()
        config = self._build_config(headless_mode=True)
        service = BrowserSessionService(config, state, gui_instance=None, thread_name="Worker-1")

        with patch("software.core.engine.browser_session_service._select_proxy_for_session", return_value=None), \
             patch("software.core.engine.browser_session_service._select_user_agent_for_session", return_value=("", "")), \
             patch("software.core.engine.browser_session_service.create_browser_manager", return_value=object()), \
             patch("software.core.engine.browser_session_service.create_playwright_driver", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                service.create_browser(["edge"], 0, 0)

        self.assertFalse(service.sem_acquired)
        self.assertEqual(state.semaphore.acquired, 1)
        self.assertEqual(state.semaphore.released, 1)
        self.assertEqual(state.released_threads, ["Worker-1"])
        self.assertIsNone(service.proxy_address)

    def test_create_browser_uses_browser_owner_open_session(self) -> None:
        state = _FakeState()
        config = self._build_config(headless_mode=True)
        fake_driver = _FakeDriver()
        owner = _FakeBrowserOwner(fake_driver, browser_name="edge")
        service = BrowserSessionService(
            config,
            state,
            gui_instance=None,
            thread_name="Worker-1",
            browser_owner=owner,
        )

        with patch("software.core.engine.browser_session_service._select_proxy_for_session", return_value=None), \
             patch("software.core.engine.browser_session_service._select_user_agent_for_session", return_value=("UA", "")):
            browser_name = service.create_browser(["edge"], 0, 0)

        self.assertEqual(browser_name, "edge")
        self.assertEqual(len(owner.open_session_calls), 1)
        self.assertEqual(owner.open_session_calls[0]["user_agent"], "UA")
        self.assertIs(service.driver, fake_driver)

    def test_shutdown_with_browser_owner_does_not_close_browser_manager(self) -> None:
        state = _FakeState()
        config = self._build_config(headless_mode=True)
        fake_driver = _FakeDriver()
        owner = _FakeBrowserOwner(fake_driver, browser_name="edge")
        service = BrowserSessionService(
            config,
            state,
            gui_instance=None,
            thread_name="Worker-1",
            browser_owner=owner,
        )
        service.driver = fake_driver

        with patch("software.core.engine.browser_session_service.shutdown_browser_manager") as shutdown_mock:
            service.shutdown()

        shutdown_mock.assert_not_called()
        self.assertEqual(fake_driver.quit_calls, 1)


if __name__ == "__main__":
    unittest.main()
