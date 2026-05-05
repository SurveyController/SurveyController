from __future__ import annotations

from contextlib import nullcontext
from types import SimpleNamespace

import pytest

import software.network.browser.parse_pool as parse_pool


class _FakeLease:
    def __init__(self, owner) -> None:
        self.owner = owner
        self.release_calls = 0

    def release(self) -> None:
        self.release_calls += 1


class _FakeDriver:
    def __init__(self, *, mark_cleanup_done_result: bool = True) -> None:
        self.mark_cleanup_done_result = mark_cleanup_done_result
        self.quit_calls = 0

    def mark_cleanup_done(self) -> bool:
        return self.mark_cleanup_done_result

    def quit(self) -> None:
        self.quit_calls += 1


class ParsePoolTests:
    def test_get_parse_pool_builds_once_and_reuses_cached_pool(self, patch_attrs) -> None:
        built_pools: list[object] = []

        def _build_pool():
            pool = object()
            built_pools.append(pool)
            return pool

        patch_attrs(
            (parse_pool, "_POOL", None),
            (parse_pool, "_build_parse_pool", _build_pool),
        )

        first = parse_pool._get_parse_pool()
        second = parse_pool._get_parse_pool()

        assert first is second
        assert built_pools == [first]

    def test_acquire_parse_browser_session_quits_driver_after_use(self, patch_attrs) -> None:
        driver = _FakeDriver()
        owner = SimpleNamespace(open_session=lambda **_kwargs: driver)
        lease = _FakeLease(owner)
        pool = SimpleNamespace(acquire_owner_lease=lambda **_kwargs: lease)
        patch_attrs((parse_pool, "_get_parse_pool", lambda: pool))

        with parse_pool.acquire_parse_browser_session(proxy_address="http://1.1.1.1:80") as resolved_driver:
            assert resolved_driver is driver

        assert driver.quit_calls == 1
        assert lease.release_calls == 0

    def test_acquire_parse_browser_session_releases_lease_when_open_session_fails(self, patch_attrs) -> None:
        owner = SimpleNamespace(open_session=lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("boom")))
        lease = _FakeLease(owner)
        pool = SimpleNamespace(acquire_owner_lease=lambda **_kwargs: lease)
        patch_attrs((parse_pool, "_get_parse_pool", lambda: pool))

        with pytest.raises(RuntimeError, match="boom"):
            with parse_pool.acquire_parse_browser_session():
                raise AssertionError("should not enter context")

        assert lease.release_calls == 1

    def test_acquire_parse_browser_session_raises_when_pool_unavailable(self, patch_attrs) -> None:
        pool = SimpleNamespace(acquire_owner_lease=lambda **_kwargs: None)
        patch_attrs((parse_pool, "_get_parse_pool", lambda: pool))

        with pytest.raises(RuntimeError, match="当前不可用"):
            with parse_pool.acquire_parse_browser_session():
                raise AssertionError("should not enter context")

