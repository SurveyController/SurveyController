from __future__ import annotations

import pytest

import software.core.modes.timed_mode as timed_mode


class _TimedDriver:
    def __init__(self, *, body_text: str = "", ready_result: object = False, script_error: Exception | None = None) -> None:
        self.body_text = body_text
        self.ready_result = ready_result
        self.script_error = script_error
        self.get_calls: list[str] = []
        self.refresh_calls = 0

    async def execute_script(self, script: str):
        if self.script_error is not None:
            raise self.script_error
        if "document.body && document.body.innerText" in script and "hasQuestionBlock" not in script:
            return self.body_text
        return self.ready_result

    async def get(self, url: str) -> None:
        self.get_calls.append(url)

    async def refresh(self) -> None:
        self.refresh_calls += 1


class _StopSignal:
    def __init__(self, *, is_set: bool = False, wait_returns: list[bool] | None = None) -> None:
        self._is_set = is_set
        self.wait_calls: list[float] = []
        self._wait_returns = list(wait_returns or [])

    def is_set(self) -> bool:
        return self._is_set

    def wait(self, timeout: float) -> bool:
        self.wait_calls.append(timeout)
        if self._wait_returns:
            return self._wait_returns.pop(0)
        return False


class TimedModeTests:
    @pytest.mark.asyncio
    async def test_extract_body_text_returns_empty_when_script_fails(self) -> None:
        driver = _TimedDriver(script_error=RuntimeError("boom"))
        assert await timed_mode._extract_body_text(driver) == ""

    def test_normalize_interval_clamps_invalid_and_extreme_values(self) -> None:
        assert timed_mode._normalize_interval("abc") == timed_mode.DEFAULT_REFRESH_INTERVAL
        assert timed_mode._normalize_interval(0) == timed_mode.DEFAULT_REFRESH_INTERVAL
        assert timed_mode._normalize_interval(999) == 10.0
        assert timed_mode._normalize_interval(0.01) == 0.2

    def test_parse_countdown_seconds_supports_full_and_missing_parts(self) -> None:
        assert timed_mode._parse_countdown_seconds("") is None
        assert timed_mode._parse_countdown_seconds("别的文案") is None
        assert timed_mode._parse_countdown_seconds("距离开始还有1天2时3分4秒") == 93784.0
        assert timed_mode._parse_countdown_seconds("距离开始还有5分") == 300.0

    @pytest.mark.asyncio
    async def test_page_status_detects_ready_not_started_and_ended_states(self) -> None:
        ready_driver = _TimedDriver(body_text="现在可以开始", ready_result=True)
        assert await timed_mode._page_status(ready_driver) == (True, False, False, "现在可以开始")

        not_started_driver = _TimedDriver(body_text="问卷将于2026年5月9日开放", ready_result=True)
        assert await timed_mode._page_status(not_started_driver) == (False, True, False, "问卷将于2026年5月9日开放")

        ended_driver = _TimedDriver(body_text="This survey is closed", ready_result=True)
        assert await timed_mode._page_status(ended_driver) == (False, False, True, "Thissurveyisclosed")

    @pytest.mark.asyncio
    async def test_wait_until_open_returns_false_when_stop_signal_already_set(self) -> None:
        driver = _TimedDriver()
        stop_signal = _StopSignal(is_set=True)
        assert await timed_mode.wait_until_open(driver, "https://example.com", stop_signal) is False
        assert driver.get_calls == []

    @pytest.mark.asyncio
    async def test_wait_until_open_returns_true_when_page_becomes_ready(self, monkeypatch) -> None:
        driver = _TimedDriver()
        stop_signal = _StopSignal()
        logs: list[str] = []
        waited: list[float] = []
        statuses = iter([
            (False, True, False, "距离开始还有1秒"),
            (True, False, False, "已开放"),
        ])

        async def _fake_page_status(*_args, **_kwargs):
            return next(statuses)

        async def _fake_sleep_or_stop(_stop_signal, seconds: float) -> bool:
            waited.append(seconds)
            return False

        monkeypatch.setattr(timed_mode, "_page_status", _fake_page_status)
        monkeypatch.setattr(timed_mode, "sleep_or_stop", _fake_sleep_or_stop)

        result = await timed_mode.wait_until_open(
            driver,
            "https://example.com/survey",
            stop_signal,
            refresh_interval=3,
            logger=logs.append,
        )

        assert result is True
        assert driver.get_calls == ["https://example.com/survey"]
        assert waited == [0.2]
        assert any("倒计时 <= 1.0s" in message for message in logs)
        assert any("问卷已开放" in message for message in logs)

    @pytest.mark.asyncio
    async def test_wait_until_open_returns_false_when_page_has_ended(self, monkeypatch) -> None:
        driver = _TimedDriver()
        logs: list[str] = []
        async def _fake_page_status(*_args, **_kwargs):
            return False, False, True, "已结束"

        monkeypatch.setattr(timed_mode, "_page_status", _fake_page_status)

        assert await timed_mode.wait_until_open(driver, "https://example.com", logger=logs.append) is False
        assert any("已结束/关闭" in message for message in logs)

    @pytest.mark.asyncio
    async def test_wait_until_open_retries_after_refresh_error_and_stops_on_wait(self, monkeypatch) -> None:
        driver = _TimedDriver()
        refresh_failures = {"count": 1}
        original_refresh = driver.refresh

        async def flaky_refresh() -> None:
            if refresh_failures["count"] > 0:
                refresh_failures["count"] -= 1
                raise RuntimeError("refresh failed")
            await original_refresh()

        driver.refresh = flaky_refresh
        stop_signal = _StopSignal(wait_returns=[False, True])
        logs: list[str] = []
        wait_returns = iter([False, True])

        async def _fake_page_status(*_args, **_kwargs):
            return False, False, False, "页面还没开"

        async def _fake_sleep_or_stop(_stop_signal, _seconds: float) -> bool:
            return next(wait_returns)

        monkeypatch.setattr(timed_mode, "_page_status", _fake_page_status)
        monkeypatch.setattr(timed_mode, "sleep_or_stop", _fake_sleep_or_stop)

        assert await timed_mode.wait_until_open(driver, "https://example.com", stop_signal, logger=logs.append) is False
        assert driver.get_calls == ["https://example.com"]
        assert any("刷新失败" in message for message in logs)
        assert any("尚未开放" in message for message in logs)
