from __future__ import annotations

import asyncio
import sys
from types import SimpleNamespace
from types import ModuleType

import pytest

import software.network.browser.async_owner_pool as async_owner_pool
from software.network.browser.startup import BrowserStartupRuntimeError
from software.network.browser.async_owner_pool import (
    AsyncBrowserOwner,
    AsyncBrowserOwnerPool,
    AsyncBrowserSession,
    BrowserPoolConfig,
    _OwnerBusyError,
)


class _FakePlaywright:
    def __init__(self, browser) -> None:
        self.chromium = SimpleNamespace(launch=self._launch)
        self._browser = browser
        self.stop_calls = 0
        self.launch_calls: list[dict[str, object]] = []

    async def _launch(self, **kwargs):
        self.launch_calls.append(kwargs)
        if isinstance(self._browser, Exception):
            raise self._browser
        return self._browser

    async def stop(self) -> None:
        self.stop_calls += 1


class _FakeAsyncPlaywrightFactory:
    def __init__(self, playwrights) -> None:
        self._playwrights = list(playwrights)

    def __call__(self):
        factory = self

        class _Starter:
            async def start(_self):
                return factory._playwrights.pop(0)

        return _Starter()


def _install_fake_async_playwright(monkeypatch, *playwrights) -> None:
    module = ModuleType("playwright.async_api")
    module.async_playwright = _FakeAsyncPlaywrightFactory(playwrights)
    monkeypatch.setitem(sys.modules, "playwright.async_api", module)


class _FakeRoute:
    def __init__(self) -> None:
        self.actions: list[str] = []
        self.fail_continue = False
        self.fail_fallback = False

    async def abort(self):
        self.actions.append("abort")

    async def continue_(self):
        self.actions.append("continue")
        if self.fail_continue:
            raise RuntimeError("continue boom")

    async def fallback(self):
        self.actions.append("fallback")
        if self.fail_fallback:
            raise RuntimeError("fallback boom")


class _FakeContext:
    def __init__(self, *, fail_route: bool = False, fail_new_page: bool = False) -> None:
        self.fail_route = fail_route
        self.fail_new_page = fail_new_page
        self.close_calls = 0
        self.route_calls: list[tuple[str, object]] = []

    async def route(self, pattern: str, handler) -> None:
        self.route_calls.append((pattern, handler))
        if self.fail_route:
            raise RuntimeError("route boom")

    async def new_page(self):
        if self.fail_new_page:
            raise RuntimeError("page boom")
        return SimpleNamespace()

    async def close(self) -> None:
        self.close_calls += 1


class _FakeBrowser:
    def __init__(self, *, context: _FakeContext | None = None, context_error: Exception | None = None, close_error: Exception | None = None) -> None:
        self.process = SimpleNamespace(pid=4321)
        self._context = context or _FakeContext()
        self._context_error = context_error
        self._close_error = close_error
        self.close_calls = 0
        self.new_context_calls: list[dict[str, object]] = []

    async def new_context(self, **kwargs):
        self.new_context_calls.append(kwargs)
        if self._context_error is not None:
            raise self._context_error
        return self._context

    async def close(self) -> None:
        self.close_calls += 1
        if self._close_error is not None:
            raise self._close_error


class AsyncBrowserOwnerLargeTests:
    @pytest.mark.asyncio
    async def test_async_browser_session_close_delegates_to_driver(self) -> None:
        calls: list[str] = []
        driver = SimpleNamespace(aclose=lambda: asyncio.sleep(0, result=calls.append("closed")))
        session = AsyncBrowserSession(driver=driver, owner_id=1, browser_name="edge")

        await session.close()

        assert calls == ["closed"]

    @pytest.mark.asyncio
    async def test_shutdown_browser_swallows_browser_and_playwright_close_errors(self, monkeypatch) -> None:
        owner = AsyncBrowserOwner(owner_id=1, prefer_browsers=["edge"])
        browser = _FakeBrowser(close_error=RuntimeError("browser close boom"))
        playwright = SimpleNamespace(stop=lambda: (_ for _ in ()).throw(RuntimeError("pw stop boom")))
        suppressed: list[str] = []
        monkeypatch.setattr(async_owner_pool, "log_suppressed_exception", lambda where, exc, **_kwargs: suppressed.append(f"{where}:{exc}"))

        await owner._shutdown_browser(browser, playwright)

        assert owner.browser_name == ""
        assert len(suppressed) == 2

    @pytest.mark.asyncio
    async def test_launch_browser_falls_back_and_stops_failed_playwright(self, monkeypatch) -> None:
        owner = AsyncBrowserOwner(owner_id=2, prefer_browsers=["edge", "chrome"], headless=True, window_position=(10, 20))
        failed_playwright = _FakePlaywright(browser=RuntimeError("launch edge failed"))
        success_browser = _FakeBrowser()
        success_playwright = _FakePlaywright(browser=success_browser)
        monkeypatch.setattr(async_owner_pool, "_build_launch_args", lambda **_kwargs: {"headless": True})
        monkeypatch.setattr(async_owner_pool, "_format_exception_chain", lambda exc: f"chain:{exc}")
        monkeypatch.setattr(async_owner_pool, "is_playwright_startup_environment_error", lambda exc: False)
        _install_fake_async_playwright(monkeypatch, failed_playwright, success_playwright)

        browser, browser_name, playwright, browser_pid = await owner._launch_browser()

        assert browser is success_browser
        assert browser_name == "chrome"
        assert playwright is success_playwright
        assert failed_playwright.stop_calls == 1
        assert browser_pid == 4321

    @pytest.mark.asyncio
    async def test_launch_browser_raises_friendly_error_on_environment_failure(self, monkeypatch) -> None:
        owner = AsyncBrowserOwner(owner_id=3, prefer_browsers=["edge"])
        failed_playwright = _FakePlaywright(browser=RuntimeError("env broken"))
        monkeypatch.setattr(async_owner_pool, "_build_launch_args", lambda **_kwargs: {})
        monkeypatch.setattr(async_owner_pool, "_format_exception_chain", lambda exc: str(exc))
        monkeypatch.setattr(async_owner_pool, "is_playwright_startup_environment_error", lambda exc: True)
        monkeypatch.setattr(async_owner_pool, "classify_playwright_startup_error", lambda exc: SimpleNamespace(message=f"friendly:{exc}"))
        _install_fake_async_playwright(monkeypatch, failed_playwright)

        with pytest.raises(BrowserStartupRuntimeError, match="friendly:env broken"):
            await owner._launch_browser()

        assert failed_playwright.stop_calls == 1

    @pytest.mark.asyncio
    async def test_launch_browser_raises_startup_error_on_driver_disconnect(self, monkeypatch) -> None:
        owner = AsyncBrowserOwner(owner_id=33, prefer_browsers=["edge"])
        monkeypatch.setattr(async_owner_pool, "_build_launch_args", lambda **_kwargs: {})
        monkeypatch.setattr(
            async_owner_pool,
            "_start_playwright_async_runtime",
            lambda: asyncio.sleep(0, result=(_ for _ in ()).throw(RuntimeError("Connection closed while reading from the driver"))),
        )
        monkeypatch.setattr(async_owner_pool, "classify_playwright_startup_error", lambda exc: SimpleNamespace(message=f"friendly:{exc}"))

        with pytest.raises(BrowserStartupRuntimeError, match="Connection closed while reading from the driver"):
            await owner._launch_browser()

    @pytest.mark.asyncio
    async def test_ensure_browser_launches_new_browser(self, monkeypatch) -> None:
        owner = AsyncBrowserOwner(owner_id=4, prefer_browsers=["edge"])
        launched_browser = _FakeBrowser()
        launched_playwright = object()
        launch_calls: list[str] = []
        monkeypatch.setattr(
            owner,
            "_launch_browser",
            lambda: asyncio.sleep(0, result=launch_calls.append("launch") or (launched_browser, "chrome", launched_playwright, 4321)),
        )

        browser, browser_name, playwright, browser_pid = await owner._ensure_browser()
        browser2, browser_name2, playwright2, browser_pid2 = await owner._ensure_browser()
        assert browser is launched_browser
        assert browser_name == "chrome"
        assert playwright is launched_playwright
        assert browser_pid == 4321
        assert browser2 is launched_browser
        assert browser_name2 == "chrome"
        assert playwright2 is launched_playwright
        assert browser_pid2 == 4321
        assert launch_calls == ["launch"]

    @pytest.mark.asyncio
    async def test_ensure_browser_rejects_closed_owner(self) -> None:
        owner = AsyncBrowserOwner(owner_id=5, prefer_browsers=["edge"])
        owner._closed = True

        with pytest.raises(RuntimeError, match="已关闭"):
            await owner._ensure_browser()

    @pytest.mark.asyncio
    async def test_open_session_builds_driver_and_release_callback(self, monkeypatch) -> None:
        owner = AsyncBrowserOwner(owner_id=6, prefer_browsers=["edge"])
        context = _FakeContext()
        browser = _FakeBrowser(context=context)
        monkeypatch.setattr(owner, "_ensure_browser", lambda: asyncio.sleep(0, result=(browser, "edge", object(), 4321)))
        monkeypatch.setattr(async_owner_pool, "_build_context_args", lambda **kwargs: {"proxy_address": kwargs["proxy_address"], "user_agent": kwargs["user_agent"]})
        captured: dict[str, object] = {}

        def _fake_driver(**kwargs):
            captured.update(kwargs)
            return SimpleNamespace(aclose=lambda: asyncio.sleep(0))

        monkeypatch.setattr(async_owner_pool, "PlaywrightAsyncDriver", _fake_driver)
        session = await owner.open_session(proxy_address="http://1.1.1.1:80", user_agent="UA")

        assert isinstance(session, AsyncBrowserSession)
        assert session.owner_id == 6
        assert session.browser_name == "edge"
        assert browser.new_context_calls == [{"proxy_address": "http://1.1.1.1:80", "user_agent": "UA"}]
        assert context.route_calls[0][0] == "**/*"
        assert owner.active_contexts == 1
        assert captured["browser_pid"] == 4321
        assert "browser_close_callback" not in captured

        captured["release_callback"]()
        assert owner.active_contexts == 0

    @pytest.mark.asyncio
    async def test_open_session_closes_context_and_marks_broken_on_disconnect(self, monkeypatch) -> None:
        owner = AsyncBrowserOwner(owner_id=7, prefer_browsers=["edge"])
        context = _FakeContext(fail_new_page=True)
        browser = _FakeBrowser(context=context)
        monkeypatch.setattr(owner, "_ensure_browser", lambda: asyncio.sleep(0, result=(browser, "edge", object(), 4321)))
        monkeypatch.setattr(async_owner_pool, "_build_context_args", lambda **kwargs: kwargs)
        monkeypatch.setattr(async_owner_pool, "_is_browser_disconnected_error", lambda exc: "page boom" in str(exc))

        with pytest.raises(RuntimeError, match="page boom"):
            await owner.open_session(proxy_address=None, user_agent=None)

        assert context.close_calls == 1
        assert owner.active_contexts == 0
        assert owner._broken is True

    @pytest.mark.asyncio
    async def test_ensure_ready_starts_browser_without_context(self, monkeypatch) -> None:
        owner = AsyncBrowserOwner(owner_id=77, prefer_browsers=["edge"])
        browser = _FakeBrowser()
        playwright = SimpleNamespace(stop=lambda: asyncio.sleep(0))
        monkeypatch.setattr(owner, "_ensure_browser", lambda: asyncio.sleep(0, result=(browser, "edge", playwright, 4321)))

        browser_name = await owner.ensure_ready()

        assert browser_name == "edge"
        assert browser.new_context_calls == []

    @pytest.mark.asyncio
    async def test_wait_until_available_blocks_until_release(self) -> None:
        owner = AsyncBrowserOwner(owner_id=78, prefer_browsers=["edge"], max_contexts=1)
        await owner._acquire_slot(wait=True)
        waiter = asyncio.create_task(owner.wait_until_available())
        await asyncio.sleep(0.01)
        assert not waiter.done()

        owner._release_slot()

        await asyncio.wait_for(waiter, timeout=1.0)

    @pytest.mark.asyncio
    async def test_release_slot_ignores_over_release(self) -> None:
        owner = AsyncBrowserOwner(owner_id=8, prefer_browsers=["edge"])

        owner._release_slot()

        assert owner.active_contexts == 0

    @pytest.mark.asyncio
    async def test_shutdown_marks_closed_and_delegates(self, monkeypatch) -> None:
        owner = AsyncBrowserOwner(owner_id=9, prefer_browsers=["edge"])
        shutdown_calls: list[str] = []
        monkeypatch.setattr(owner, "_shutdown_browser", lambda: asyncio.sleep(0, result=shutdown_calls.append("shutdown")))

        await owner.shutdown()

        assert owner._closed is True
        assert shutdown_calls == ["shutdown"]


class AsyncBrowserOwnerPoolLargeTests:
    @pytest.mark.asyncio
    async def test_route_runtime_resource_uses_continue_when_fallback_missing_and_swallows_errors(self) -> None:
        route = _FakeRoute()
        route.fallback = None
        request = SimpleNamespace(resource_type="xhr", url="https://example.com/api")

        await async_owner_pool._route_runtime_resource(route, request)
        assert route.actions == ["continue"]

        noisy_route = _FakeRoute()
        noisy_route.fail_fallback = True
        noisy_request = SimpleNamespace(resource_type="script", url="https://example.com/app.js")
        await async_owner_pool._route_runtime_resource(noisy_route, noisy_request)
        assert noisy_route.actions == ["fallback", "fallback"]

    @pytest.mark.asyncio
    async def test_owner_pool_open_session_closed_and_non_disconnect_paths(self, monkeypatch) -> None:
        pool = AsyncBrowserOwnerPool(
            config=BrowserPoolConfig(owner_count=2, contexts_per_owner=1, logical_concurrency=2),
            headless=True,
        )
        pool._closed = True
        with pytest.raises(RuntimeError, match="已关闭"):
            await pool.open_session(proxy_address=None, user_agent=None)

        pool = AsyncBrowserOwnerPool(
            config=BrowserPoolConfig(owner_count=2, contexts_per_owner=1, logical_concurrency=2),
            headless=True,
        )
        first_owner, second_owner = pool.owners
        monkeypatch.setattr(first_owner, "open_session", lambda **_kwargs: asyncio.sleep(0, result=(_ for _ in ()).throw(RuntimeError("first boom"))))
        monkeypatch.setattr(second_owner, "open_session", lambda **_kwargs: asyncio.sleep(0, result=AsyncBrowserSession(driver=SimpleNamespace(aclose=lambda: asyncio.sleep(0)), owner_id=2, browser_name="edge")))
        monkeypatch.setattr(async_owner_pool, "_is_browser_disconnected_error", lambda exc: False)

        with pytest.raises(RuntimeError, match="first boom"):
            await pool.open_session(proxy_address=None, user_agent=None)

    @pytest.mark.asyncio
    async def test_owner_pool_open_session_retries_and_shutdown_gathers_owners(self, monkeypatch) -> None:
        pool = AsyncBrowserOwnerPool(
            config=BrowserPoolConfig(owner_count=2, contexts_per_owner=1, logical_concurrency=2),
            headless=False,
            window_positions=[(1, 2)],
        )
        first_owner, second_owner = pool.owners
        monkeypatch.setattr(first_owner, "open_session", lambda **_kwargs: asyncio.sleep(0, result=(_ for _ in ()).throw(RuntimeError("disconnect first"))))
        monkeypatch.setattr(
            second_owner,
            "open_session",
            lambda **_kwargs: asyncio.sleep(
                0,
                result=AsyncBrowserSession(driver=SimpleNamespace(aclose=lambda: asyncio.sleep(0)), owner_id=second_owner.owner_id, browser_name="edge"),
            ),
        )
        monkeypatch.setattr(async_owner_pool, "_is_browser_disconnected_error", lambda exc: "disconnect" in str(exc))

        session = await pool.open_session(proxy_address="http://2.2.2.2:90", user_agent="UA")
        assert session.owner_id == second_owner.owner_id
        assert pool.owners[0]._window_position == (1, 2)
        assert pool.owners[1]._window_position is None

        shutdown_calls: list[int] = []
        monkeypatch.setattr(first_owner, "shutdown", lambda: asyncio.sleep(0, result=shutdown_calls.append(first_owner.owner_id)))
        monkeypatch.setattr(second_owner, "shutdown", lambda: asyncio.sleep(0, result=shutdown_calls.append(second_owner.owner_id)))

        await pool.shutdown()

        assert pool._closed is True
        assert shutdown_calls == [1, 2]

    @pytest.mark.asyncio
    async def test_owner_pool_waits_on_owner_signal_instead_of_spin_sleep(self, monkeypatch) -> None:
        pool = AsyncBrowserOwnerPool(
            config=BrowserPoolConfig(owner_count=2, contexts_per_owner=1, logical_concurrency=2),
            headless=True,
        )
        first_owner, second_owner = pool.owners
        wait_calls: list[int] = []
        release_gate = asyncio.Event()

        async def _busy_open_session(**_kwargs):
            raise _OwnerBusyError("busy")

        async def _wait_available(owner_id: int) -> None:
            wait_calls.append(owner_id)
            await release_gate.wait()

        monkeypatch.setattr(first_owner, "open_session", _busy_open_session)
        monkeypatch.setattr(second_owner, "open_session", _busy_open_session)
        monkeypatch.setattr(first_owner, "wait_until_available", lambda: _wait_available(first_owner.owner_id))
        monkeypatch.setattr(second_owner, "wait_until_available", lambda: _wait_available(second_owner.owner_id))

        async def _close_pool() -> None:
            while len(wait_calls) < 2:
                await asyncio.sleep(0)
            pool._closed = True
            release_gate.set()

        stopper = asyncio.create_task(_close_pool())
        with pytest.raises(RuntimeError, match="已关闭|没有可用 owner"):
            await asyncio.wait_for(pool.open_session(proxy_address=None, user_agent=None), timeout=2.0)
        await stopper
        assert wait_calls == [first_owner.owner_id, second_owner.owner_id]

    @pytest.mark.asyncio
    async def test_owner_pool_open_session_uses_next_idle_owner_before_waiting(self, monkeypatch) -> None:
        pool = AsyncBrowserOwnerPool(
            config=BrowserPoolConfig(owner_count=2, contexts_per_owner=1, logical_concurrency=2),
            headless=True,
        )
        first_owner, second_owner = pool.owners
        calls: list[tuple[int, bool]] = []

        async def _first_open_session(**kwargs):
            calls.append((first_owner.owner_id, kwargs["wait"]))
            raise _OwnerBusyError("busy")

        async def _second_open_session(**kwargs):
            calls.append((second_owner.owner_id, kwargs["wait"]))
            return AsyncBrowserSession(
                driver=SimpleNamespace(aclose=lambda: asyncio.sleep(0)),
                owner_id=second_owner.owner_id,
                browser_name="edge",
            )

        monkeypatch.setattr(first_owner, "open_session", _first_open_session)
        monkeypatch.setattr(second_owner, "open_session", _second_open_session)

        session = await pool.open_session(proxy_address=None, user_agent=None)

        assert session.owner_id == second_owner.owner_id
        assert calls == [(first_owner.owner_id, False), (second_owner.owner_id, False)]

    @pytest.mark.asyncio
    async def test_owner_pool_ensure_ready_retries_disconnected_owner(self, monkeypatch) -> None:
        pool = AsyncBrowserOwnerPool(
            config=BrowserPoolConfig(owner_count=2, contexts_per_owner=1, logical_concurrency=2),
            headless=True,
        )
        first_owner, second_owner = pool.owners
        monkeypatch.setattr(first_owner, "ensure_ready", lambda: asyncio.sleep(0, result=(_ for _ in ()).throw(RuntimeError("disconnect first"))))
        monkeypatch.setattr(second_owner, "ensure_ready", lambda: asyncio.sleep(0, result="edge"))
        monkeypatch.setattr(async_owner_pool, "_is_browser_disconnected_error", lambda exc: "disconnect" in str(exc))

        assert await pool.ensure_ready() == "edge"
