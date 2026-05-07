from __future__ import annotations
import threading
import time
import software.core.engine.preloaded_session_pool as pool_module
from software.core.engine.preloaded_session_pool import PreloadedBrowserSessionPool
from software.core.task import ExecutionConfig, ExecutionState

class _FakeBrowserSessionService:
    instances: list['_FakeBrowserSessionService'] = []

    def __init__(self, *_args, **_kwargs):
        self.driver = object()
        self.shutdown_called = 0
        self.create_browser_calls: list[tuple[list[str], int, int, bool]] = []
        _FakeBrowserSessionService.instances.append(self)

    def create_browser(self, preferred_browsers, window_x_pos: int, window_y_pos: int, *, acquire_browser_semaphore: bool=True):
        self.create_browser_calls.append((list(preferred_browsers or []), int(window_x_pos), int(window_y_pos), bool(acquire_browser_semaphore)))
        return 'edge'

    def shutdown(self) -> None:
        self.shutdown_called += 1

class PreloadedSessionPoolTests:

    def setup_method(self, _method) -> None:
        _FakeBrowserSessionService.instances = []

    def test_warm_async_builds_ready_session_and_acquire_returns_preloaded_lease(self, patch_attrs) -> None:
        config = ExecutionConfig(url='https://example.com/form')
        state = ExecutionState(config=config)
        loaded_drivers: list[object] = []

        def _page_loader(driver, _config) -> None:
            loaded_drivers.append(driver)
        patch_attrs(
            (pool_module, 'BrowserSessionService', _FakeBrowserSessionService),
        )
        pool = PreloadedBrowserSessionPool(config=config, state=state, gui_instance=None, thread_name='Slot-1', browser_owner_pool=object(), page_loader=_page_loader)
        stop_signal = threading.Event()
        pool.warm_async(['edge'], 0, 0)
        lease = pool.acquire(stop_signal, wait=True)
        assert lease.preloaded
        assert lease.browser_name == 'edge'
        assert lease.session is not None
        assert len(loaded_drivers) == 1
        assert loaded_drivers[0] is lease.session.driver
        assert lease.session.create_browser_calls == [(['edge'], 0, 0, False)]

    def test_shutdown_closes_unused_ready_session(self, patch_attrs) -> None:
        config = ExecutionConfig(url='https://example.com/form')
        state = ExecutionState(config=config)
        patch_attrs(
            (pool_module, 'BrowserSessionService', _FakeBrowserSessionService),
        )
        pool = PreloadedBrowserSessionPool(config=config, state=state, gui_instance=None, thread_name='Slot-1', browser_owner_pool=object(), page_loader=lambda *_args, **_kwargs: None)
        stop_signal = threading.Event()
        pool.warm_async(['edge'], 0, 0)
        deadline = time.time() + 2.0
        while time.time() < deadline:
            lease = pool.acquire(stop_signal, wait=False)
            if lease.preloaded:
                pool.shutdown()
                assert lease.session.shutdown_called == 0
                return
            time.sleep(0.02)
        raise AssertionError('预热 session 未在预期时间内完成')

    def test_shutdown_disposes_ready_session_when_not_consumed(self, patch_attrs) -> None:
        config = ExecutionConfig(url='https://example.com/form')
        state = ExecutionState(config=config)
        patch_attrs(
            (pool_module, 'BrowserSessionService', _FakeBrowserSessionService),
        )
        pool = PreloadedBrowserSessionPool(config=config, state=state, gui_instance=None, thread_name='Slot-1', browser_owner_pool=object(), page_loader=lambda *_args, **_kwargs: None)
        pool.warm_async(['edge'], 0, 0)
        deadline = time.time() + 2.0
        while time.time() < deadline:
            if pool._ready_session is not None:
                ready_session = pool._ready_session
                pool.shutdown()
                assert ready_session.shutdown_called == 1
                return
            time.sleep(0.02)
        raise AssertionError('预热 session 未在预期时间内进入 ready 状态')
