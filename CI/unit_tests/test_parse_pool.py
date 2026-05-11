from __future__ import annotations

import pytest

import software.network.browser.parse_pool as parse_pool


class _FakeDriver:
    def __init__(self, *, mark_cleanup_done_result: bool = True) -> None:
        self.mark_cleanup_done_result = mark_cleanup_done_result
        self.aclose_calls = 0

    def mark_cleanup_done(self) -> bool:
        return self.mark_cleanup_done_result

    async def aclose(self) -> None:
        self.aclose_calls += 1


class _FakeSession:
    def __init__(self, driver: _FakeDriver | None) -> None:
        self.driver = driver


class ParsePoolTests:
    @pytest.mark.asyncio
    async def test_get_parse_pool_builds_once_per_event_loop(self, patch_attrs) -> None:
        built_pools: list[object] = []

        def _build_pool():
            pool = object()
            built_pools.append(pool)
            return pool

        patch_attrs(
            (parse_pool, "_POOLS", {}),
            (parse_pool, "_build_parse_pool", _build_pool),
        )

        first = parse_pool._get_parse_pool()
        second = parse_pool._get_parse_pool()

        assert first is second
        assert built_pools == [first]

    def test_get_parse_pool_uses_cached_pool_for_same_loop_key(self, patch_attrs, monkeypatch) -> None:
        fake_loop = object()
        cached_pool = object()

        patch_attrs((parse_pool, "_POOLS", {id(fake_loop): cached_pool}))
        monkeypatch.setattr(parse_pool.asyncio, "get_running_loop", lambda: fake_loop)

        assert parse_pool._get_parse_pool() is cached_pool

    @pytest.mark.asyncio
    async def test_acquire_parse_browser_session_closes_driver_after_use(self, patch_attrs) -> None:
        driver = _FakeDriver()

        class _FakePool:
            async def open_session(self, **_kwargs):
                return _FakeSession(driver)

        patch_attrs((parse_pool, "_get_parse_pool", lambda: _FakePool()))

        async with parse_pool.acquire_parse_browser_session(proxy_address="http://1.1.1.1:80") as resolved_driver:
            assert resolved_driver is driver

        assert driver.aclose_calls == 1

    @pytest.mark.asyncio
    async def test_acquire_parse_browser_session_raises_when_open_session_fails(self, patch_attrs) -> None:
        class _FakePool:
            async def open_session(self, **_kwargs):
                raise RuntimeError("boom")

        patch_attrs((parse_pool, "_get_parse_pool", lambda: _FakePool()))

        with pytest.raises(RuntimeError, match="boom"):
            async with parse_pool.acquire_parse_browser_session():
                raise AssertionError("should not enter context")

    @pytest.mark.asyncio
    async def test_acquire_parse_browser_session_raises_when_session_has_no_driver(self, patch_attrs) -> None:
        class _FakePool:
            async def open_session(self, **_kwargs):
                return _FakeSession(None)

        patch_attrs((parse_pool, "_get_parse_pool", lambda: _FakePool()))

        with pytest.raises(RuntimeError, match="创建失败"):
            async with parse_pool.acquire_parse_browser_session():
                raise AssertionError("should not enter context")
