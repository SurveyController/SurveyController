from __future__ import annotations

import threading

import pytest

from wjx.provider import starttime


class _FakeDriver:
    def __init__(self, result):
        self.result = result
        self.calls: list[tuple[str, tuple[object, ...]]] = []

    async def execute_script(self, script: str, *args):
        self.calls.append((script, args))
        return self.result


class WjxStarttimeTests:
    @pytest.mark.asyncio
    async def test_try_apply_submit_starttime_writes_target_seconds(self) -> None:
        driver = _FakeDriver({"ok": True, "value": "2026/5/15 0:09:04"})

        applied = await starttime.try_apply_submit_starttime(driver, 60)

        assert applied is True
        assert len(driver.calls) == 1
        script, args = driver.calls[0]
        assert "document.getElementById('starttime')" in script
        assert args == (60.0,)

    @pytest.mark.asyncio
    async def test_prepare_answer_duration_before_submit_falls_back_to_real_wait_when_starttime_fails(self, monkeypatch) -> None:
        waited: list[float] = []

        async def _fake_try_apply(_driver, _target_seconds: float) -> bool:
            return False

        async def _fake_wait(_stop_signal, seconds: float) -> bool:
            waited.append(seconds)
            return False

        monkeypatch.setattr(starttime, "try_apply_submit_starttime", _fake_try_apply)
        monkeypatch.setattr(starttime, "sample_answer_duration_seconds", lambda _range: 42.5)
        monkeypatch.setattr(starttime, "wait_answer_duration_seconds", _fake_wait)

        interrupted = await starttime.prepare_answer_duration_before_submit(
            _FakeDriver(None),
            threading.Event(),
            (40, 45),
        )

        assert interrupted is False
        assert waited == [42.5]

    @pytest.mark.asyncio
    async def test_prepare_answer_duration_before_submit_returns_interrupt_state_from_fallback_wait(self, monkeypatch) -> None:
        async def _fake_try_apply(_driver, _target_seconds: float) -> bool:
            return False

        async def _fake_wait(_stop_signal, _seconds: float) -> bool:
            return True

        monkeypatch.setattr(starttime, "try_apply_submit_starttime", _fake_try_apply)
        monkeypatch.setattr(starttime, "sample_answer_duration_seconds", lambda _range: 15.0)
        monkeypatch.setattr(starttime, "wait_answer_duration_seconds", _fake_wait)

        interrupted = await starttime.prepare_answer_duration_before_submit(
            _FakeDriver(None),
            threading.Event(),
            (15, 15),
        )

        assert interrupted is True
