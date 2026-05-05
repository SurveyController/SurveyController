from __future__ import annotations
import pytest
import errno
import software.network.browser.options as browser_options
import software.network.browser.startup as browser_startup
import software.network.browser.transient as browser_transient

class BrowserOptionsTests:

    def test_build_selector_handles_xpath_and_id(self) -> None:
        assert browser_options._build_selector('xpath', "//div[@id='q1']") == "xpath=//div[@id='q1']"
        assert browser_options._build_selector('id', 'div1') == '#div1'
        assert browser_options._build_selector('id', '#div2') == '#div2'
        assert browser_options._build_selector('css', '.question') == '.question'

    def test_build_context_args_extracts_proxy_credentials_and_viewport(self, patch_attrs) -> None:
        patch_attrs(
            (browser_options, 'normalize_proxy_address', lambda _value: 'http://user:pass@127.0.0.1:8888'),
            (browser_options, 'HEADLESS_WINDOW_SIZE', '1280,720'),
            (browser_options, 'get_proxy_source', lambda: 'pool'),
        )
        context_args = browser_options._build_context_args(headless=True, proxy_address='ignored', user_agent='UA-Test')
        assert context_args == {'proxy': {'server': 'http://127.0.0.1:8888', 'username': 'user', 'password': 'pass'}, 'user_agent': 'UA-Test', 'viewport': {'width': 1280, 'height': 720}}

    def test_build_context_args_uses_custom_proxy_auth_when_url_has_no_credentials(self, patch_attrs) -> None:
        patch_attrs(
            (browser_options, 'normalize_proxy_address', lambda _value: 'http://127.0.0.1:9999'),
            (browser_options, 'get_proxy_source', lambda: browser_options.PROXY_SOURCE_CUSTOM),
            (browser_options, 'get_proxy_auth', lambda: 'alice:secret'),
        )
        context_args = browser_options._build_context_args(headless=False, proxy_address='http://127.0.0.1:9999', user_agent=None)
        assert context_args == {'proxy': {'server': 'http://127.0.0.1:9999', 'username': 'alice', 'password': 'secret'}}

    def test_build_launch_args_for_edge_adds_channel_window_position_and_no_proxy(self) -> None:
        launch_args = browser_options._build_launch_args(browser_name='edge', headless=False, window_position=(10, 20), append_no_proxy=True)
        assert launch_args['channel'] == 'msedge'
        assert not launch_args['headless']
        assert '--disable-gpu' in launch_args['args']
        assert '--disable-extensions' in launch_args['args']
        assert '--disable-background-networking' in launch_args['args']
        assert '--window-position=10,20' in launch_args['args']
        assert '--no-proxy-server' in launch_args['args']

    def test_error_detectors_match_proxy_and_disconnect_messages(self) -> None:
        assert browser_options._is_proxy_tunnel_error(RuntimeError('net::ERR_PROXY_CONNECTION_FAILED'))
        assert browser_options._is_browser_disconnected_error(RuntimeError('Target page, context or browser has been closed'))
        assert not browser_options._is_proxy_tunnel_error(RuntimeError('plain error'))
        assert not browser_options._is_browser_disconnected_error(RuntimeError('plain error'))

class BrowserStartupTests:

    def test_is_playwright_startup_environment_error_detects_socket_block(self) -> None:
        exc = PermissionError(errno.EACCES, 'socket blocked by firewall')
        assert browser_startup.is_playwright_startup_environment_error(exc)

    def test_is_playwright_startup_environment_error_detects_winsock_breakage(self) -> None:
        exc = OSError('winsock provider failed')
        exc.winerror = 10106
        assert browser_startup.is_playwright_startup_environment_error(exc)

    def test_describe_playwright_startup_error_humanizes_asyncio_subprocess_issue(self) -> None:
        root = NotImplementedError('create_subprocess_exec is unavailable')
        exc = RuntimeError('wrapper')
        exc.__cause__ = root
        message = browser_startup.describe_playwright_startup_error(exc)
        assert 'Windows asyncio 子进程能力不可用' in message

    def test_describe_playwright_startup_error_humanizes_broken_asyncio_import(self) -> None:
        exc = NameError("name 'base_events' is not defined")
        message = browser_startup.describe_playwright_startup_error(exc)
        assert 'WinError 10106' in message

    def test_classify_playwright_startup_error_uses_shared_environment_kind(self) -> None:
        exc = NameError("name 'base_events' is not defined")
        info = browser_startup.classify_playwright_startup_error(exc)
        assert info.kind == browser_startup.BROWSER_STARTUP_ERROR_ENVIRONMENT
        assert info.is_environment_error

    def test_describe_playwright_startup_error_falls_back_to_exception_type_when_message_empty(self) -> None:
        message = browser_startup.describe_playwright_startup_error(RuntimeError())
        assert message == 'RuntimeError'

    def test_start_playwright_runtime_retries_known_environment_error_then_succeeds(self, patch_attrs) -> None:

        class _FakeSyncPlaywright:

            def __init__(self) -> None:
                self.start_calls = 0

            def __call__(self):
                return self

            def start(self):
                self.start_calls += 1
                if self.start_calls == 1:
                    exc = PermissionError(errno.EACCES, 'socket blocked')
                    exc.winerror = 10013
                    raise exc
                return 'pw-runtime'
        fake_sync = _FakeSyncPlaywright()
        sleep_calls: list[float] = []
        patch_attrs(
            (browser_startup, '_load_playwright_sync', lambda: (fake_sync, object())),
            (browser_startup.gc, 'collect', lambda: None),
            (browser_startup.time, 'sleep', lambda seconds: sleep_calls.append(seconds)),
        )
        runtime = browser_startup._start_playwright_runtime()
        assert runtime == 'pw-runtime'
        assert fake_sync.start_calls == 2
        assert sleep_calls == [0.35]

    def test_start_playwright_runtime_does_not_retry_unknown_error(self, patch_attrs) -> None:

        class _FakeSyncPlaywright:

            def __call__(self):
                return self

            def start(self):
                raise RuntimeError('boom')
        patch_attrs(
            (browser_startup, '_load_playwright_sync', lambda: (_FakeSyncPlaywright(), object())),
        )
        with pytest.raises(RuntimeError, match='boom'):
            browser_startup._start_playwright_runtime()

class BrowserDriverTests:

    def test_create_transient_driver_uses_normalized_proxy_path_without_name_error(self, patch_attrs) -> None:
        fake_page = object()

        class _FakeContext:

            def new_page(self):
                return fake_page

        class _FakeBrowser:
            process = None

            def new_context(self, **_kwargs):
                return _FakeContext()

        class _FakeChromium:

            def launch(self, **_kwargs):
                return _FakeBrowser()

        class _FakePlaywright:
            chromium = _FakeChromium()
        patch_attrs(
            (browser_transient, 'normalize_proxy_address', lambda value: value),
            (browser_transient, '_start_playwright_runtime', lambda: _FakePlaywright()),
            (browser_transient, '_build_launch_args', lambda **_kwargs: {'headless': True, 'args': []}),
            (browser_transient, '_build_context_args', lambda **_kwargs: {}),
        )
        driver, browser_name = browser_transient._create_transient_driver(headless=True, prefer_browsers=['edge'], proxy_address='http://127.0.0.1:8888', user_agent='UA-Test', window_position=None)
        assert browser_name == 'edge'
        assert driver.page is fake_page

    def test_create_transient_driver_stops_playwright_when_browser_launch_fails(self, patch_attrs) -> None:

        class _FakeChromium:
            def launch(self, **_kwargs):
                raise RuntimeError("launch failed")

        class _FakePlaywright:
            chromium = _FakeChromium()

            def __init__(self) -> None:
                self.stop_calls = 0

            def stop(self) -> None:
                self.stop_calls += 1

        fake_pw = _FakePlaywright()
        patch_attrs(
            (browser_transient, '_start_playwright_runtime', lambda: fake_pw),
            (browser_transient, '_build_launch_args', lambda **_kwargs: {'headless': True, 'args': []}),
            (browser_transient, 'is_playwright_startup_environment_error', lambda exc: False),
        )

        with pytest.raises(RuntimeError, match='无法启动任何浏览器'):
            browser_transient._create_transient_driver(
                headless=True,
                prefer_browsers=['edge'],
                proxy_address=None,
                user_agent=None,
                window_position=None,
            )

        assert fake_pw.stop_calls == 1

    def test_create_playwright_driver_restarts_manager_once_after_disconnect(self, patch_attrs) -> None:
        fake_context = object()
        fake_page = object()
        fake_browser = object()

        class _FakeManager:
            def __init__(self) -> None:
                self.restart_calls = 0
                self.calls = 0

            def new_context_session(self, **_kwargs):
                self.calls += 1
                if self.calls == 1:
                    raise RuntimeError('Target page, context or browser has been closed')
                return fake_context, fake_page, 'edge', fake_browser

            def restart_browser(self, **_kwargs) -> None:
                self.restart_calls += 1

        manager = _FakeManager()
        patch_attrs((browser_transient, '_is_browser_disconnected_error', lambda exc: 'closed' in str(exc).lower()))

        driver, browser_name = browser_transient.create_playwright_driver(
            manager=manager,
            persistent_browser=True,
            headless=True,
        )

        assert browser_name == 'edge'
        assert driver.page is fake_page
        assert manager.restart_calls == 1

    def test_create_playwright_driver_uses_transient_path_when_requested(self, patch_attrs) -> None:
        fake_driver = object()
        patch_attrs(
            (browser_transient, '_create_transient_driver', lambda **_kwargs: (fake_driver, 'edge')),
        )

        driver, browser_name = browser_transient.create_playwright_driver(
            transient_launch=True,
            persistent_browser=True,
        )

        assert driver is fake_driver
        assert browser_name == 'edge'
