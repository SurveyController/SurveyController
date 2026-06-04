from __future__ import annotations

import json

import pytest

from software.core.task import ExecutionState
from software.integrations.ai import free_api


class _FakeResponse:
    def __init__(self, status_code: int, payload: dict) -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = json.dumps(payload, ensure_ascii=False)

    def json(self) -> dict:
        return self._payload

    def raise_for_status(self) -> None:
        raise AssertionError("这个测试不该走到 raise_for_status")


@pytest.mark.asyncio
async def test_free_ai_rate_limiter_waits_before_request_101(monkeypatch) -> None:
    state = ExecutionState()
    current_time = 1000.0
    sleep_calls: list[float] = []

    def fake_monotonic() -> float:
        return current_time

    async def fake_sleep(seconds: float) -> None:
        nonlocal current_time
        sleep_calls.append(seconds)
        current_time += seconds

    monkeypatch.setattr(free_api.time, "monotonic", fake_monotonic)
    monkeypatch.setattr(free_api.asyncio, "sleep", fake_sleep)

    for _ in range(free_api._FREE_AI_MAX_REQUESTS_PER_MINUTE):
        await free_api._await_free_ai_rate_limit_async(state)

    assert len(state.free_ai_request_timestamps) == free_api._FREE_AI_MAX_REQUESTS_PER_MINUTE

    await free_api._await_free_ai_rate_limit_async(state)

    assert sleep_calls == [free_api._FREE_AI_RATE_WINDOW_SECONDS]
    assert len(state.free_ai_request_timestamps) == 1


@pytest.mark.asyncio
async def test_submit_free_ai_batch_task_accepts_http_202(monkeypatch) -> None:
    rate_limit_calls: list[str] = []

    async def fake_apost(url, *, headers=None, json=None, timeout=0, proxies=None):
        assert url.endswith("/batch")
        assert headers["X-Device-ID"] == "device-1"
        assert json["user_id"] == 73952
        assert len(json["items"]) == 1
        return _FakeResponse(
            202,
            {
                "task_id": "task-202",
                "status": "queued",
                "total_items": 1,
                "batch_count": 1,
                "poll_after_ms": 1000,
                "expires_at": "2026-06-04T12:00:00Z",
            },
        )

    async def fake_retry(_request_name, request_func):
        return await request_func()

    async def fake_rate_limit(_ctx=None) -> None:
        rate_limit_calls.append("batch_submit")

    monkeypatch.setattr(free_api.http_client, "apost", fake_apost)
    monkeypatch.setattr(free_api, "_aexecute_ai_request_with_retry", fake_retry)
    monkeypatch.setattr(free_api, "_await_free_ai_rate_limit_async", fake_rate_limit)

    result = await free_api._submit_free_ai_batch_task_with_identity_async(
        [
            free_api.FreeAIBatchItem(
                item_id="q1",
                question_type="fill_blank",
                question_content="请填写城市",
            )
        ],
        user_id=73952,
        device_id="device-1",
    )

    assert result.task_id == "task-202"
    assert result.status == "queued"
    assert result.total_items == 1
    assert result.batch_count == 1
    assert result.poll_after_ms == 1000
    assert result.expires_at == "2026-06-04T12:00:00Z"
    assert rate_limit_calls == ["batch_submit"]


@pytest.mark.asyncio
async def test_poll_free_ai_batch_task_uses_shared_rate_limiter(monkeypatch) -> None:
    rate_limit_calls: list[str] = []

    async def fake_aget(url, *, headers=None, timeout=0, proxies=None):
        assert url.endswith("/tasks/task-1")
        assert headers["X-Device-ID"] == "device-1"
        return _FakeResponse(
            200,
            {
                "task_id": "task-1",
                "status": "queued",
                "total_items": 1,
                "completed_items": 0,
                "failed_items": 0,
                "pending_items": 1,
                "poll_after_ms": 1200,
            },
        )

    async def fake_retry(_request_name, request_func):
        return await request_func()

    async def fake_rate_limit(_ctx=None) -> None:
        rate_limit_calls.append("batch_poll")

    monkeypatch.setattr(free_api.http_client, "aget", fake_aget)
    monkeypatch.setattr(free_api, "_aexecute_ai_request_with_retry", fake_retry)
    monkeypatch.setattr(free_api, "_await_free_ai_rate_limit_async", fake_rate_limit)

    result = await free_api._poll_free_ai_batch_task_with_identity_async(
        "task-1",
        device_id="device-1",
    )

    assert result.task_id == "task-1"
    assert result.status == "queued"
    assert result.pending_items == 1
    assert result.poll_after_ms == 1200
    assert rate_limit_calls == ["batch_poll"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("task_status", "detail", "expected_error"),
    [
        ("expired", "expired", "免费 AI 批量调用失败：任务已超时"),
        ("failed", "ai_global_queue_full", "免费 AI 批量调用失败：服务端全局队列已满"),
    ],
)
async def test_wait_free_ai_batch_result_async_maps_terminal_task_failures(
    monkeypatch,
    task_status: str,
    detail: str,
    expected_error: str,
) -> None:
    async def fake_identity():
        return 73952, "device-1"

    async def fake_submit(items, *, user_id, device_id, system_prompt="", timeout=0, ctx=None):
        assert user_id == 73952
        assert device_id == "device-1"
        assert [item.item_id for item in items] == ["q1"]
        assert ctx is None
        return free_api.FreeAIBatchCreateResult(
            task_id=f"task-{task_status}",
            status="queued",
            total_items=1,
            batch_count=1,
            poll_after_ms=0,
        )

    async def fake_poll(task_id, *, device_id, timeout=0, ctx=None):
        assert task_id == f"task-{task_status}"
        assert device_id == "device-1"
        assert ctx is None
        return free_api.FreeAIBatchPollResult(
            task_id=task_id,
            status=task_status,
            total_items=1,
            completed_items=0,
            failed_items=1,
            pending_items=0,
            poll_after_ms=0,
            items=[],
            detail=detail,
        )

    monkeypatch.setattr(free_api, "_ensure_free_ai_identity_async", fake_identity)
    monkeypatch.setattr(free_api, "_submit_free_ai_batch_task_with_identity_async", fake_submit)
    monkeypatch.setattr(free_api, "_poll_free_ai_batch_task_with_identity_async", fake_poll)

    result = await free_api.wait_free_ai_batch_result_async(
        [
            free_api.FreeAIBatchItem(
                item_id="q1",
                question_type="fill_blank",
                question_content="请填写城市",
            )
        ]
    )

    assert result.completed == {}
    assert result.failed == {"q1": expected_error}
    assert result.pending == set()
    assert result.task_ids == [f"task-{task_status}"]
