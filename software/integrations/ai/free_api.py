from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional

import software.network.http as http_client
from software.app.config import AI_FREE_ENDPOINT, DEFAULT_HTTP_HEADERS
from software.integrations.ai.protocols import (
    _AI_REQUEST_TIMEOUT_SECONDS,
    _aexecute_ai_request_with_retry,
    _extract_json_dict,
    _is_ai_timeout_exception,
)
from software.network.proxy.session import (
    RandomIPAuthError,
    activate_trial_async,
    format_random_ip_error,
    get_device_id,
    get_session_snapshot,
)
from software.core.task import ExecutionState

logger = logging.getLogger(__name__)


class FreeAITimeoutError(RuntimeError):
    pass


@dataclass(frozen=True)
class FreeAIBatchItem:
    item_id: str
    question_type: str
    question_content: str
    blank_count: Optional[int] = None
    system_prompt: str = ""


@dataclass(frozen=True)
class FreeAIBatchCreateResult:
    task_id: str
    status: str
    total_items: int
    batch_count: int
    poll_after_ms: int
    expires_at: str = ""


@dataclass(frozen=True)
class FreeAIBatchItemResult:
    item_id: str
    status: str
    answers: List[str]
    detail: str = ""


@dataclass(frozen=True)
class FreeAIBatchPollResult:
    task_id: str
    status: str
    total_items: int
    completed_items: int
    failed_items: int
    pending_items: int
    expires_at: str = ""
    poll_after_ms: int = 1000
    items: List[FreeAIBatchItemResult] | None = None
    detail: str = ""


@dataclass(frozen=True)
class FreeAIBatchResolvedResult:
    completed: Dict[str, List[str]]
    failed: Dict[str, str]
    pending: set[str]
    task_ids: List[str]


@dataclass
class _PendingBatchTask:
    task_id: str
    expected_items: Dict[str, FreeAIBatchItem]
    next_poll_at: float
    expires_at: str = ""


_FREE_AI_ERROR_MESSAGES = {
    "device_id_required": "免费 AI 调用失败：缺少设备标识（X-Device-ID）",
    "invalid_request_body": "免费 AI 调用失败：请求参数格式错误",
    "user_id_required": "免费 AI 调用失败：缺少 user_id",
    "invalid_user_id": "免费 AI 调用失败：user_id 无效",
    "items_required": "免费 AI 批量调用失败：缺少 items",
    "too_many_items": "免费 AI 批量调用失败：单个任务最多 64 题",
    "item_id_required": "免费 AI 批量调用失败：item_id 不能为空",
    "duplicate_item_id": "免费 AI 批量调用失败：item_id 不能重复",
    "invalid_question_type": "免费 AI 调用失败：question_type 无效",
    "blank_count_required": "免费 AI 调用失败：多项填空缺少 blank_count",
    "invalid_blank_count": "免费 AI 调用失败：blank_count 无效",
    "question_content_required": "免费 AI 调用失败：题干不能为空",
    "user_expired": "免费 AI 调用失败：账号已过期",
    "user_banned": "免费 AI 调用失败：账号已被封禁",
    "device_owned_by_other_user": "免费 AI 调用失败：当前设备已绑定其他账号",
    "device_banned": "免费 AI 调用失败：当前设备已被封禁",
    "user_ai_banned": "免费 AI 调用失败：当前账号已被禁止使用免费 AI",
    "ai_not_configured": "免费 AI 调用失败：服务端未配置 AI",
    "ai_global_queue_full": "免费 AI 批量调用失败：服务端全局队列已满",
    "ai_task_queue_full": "免费 AI 批量调用失败：任务队列已满",
    "ai_task_not_found": "免费 AI 批量调用失败：任务不存在或设备不匹配",
    "ai_task_expired": "免费 AI 批量调用失败：任务已超时",
    "ai_upstream_failed": "免费 AI 调用失败：上游模型服务异常",
    "ai_empty_response": "免费 AI 调用失败：上游返回空答案",
    "ai_usage_missing": "免费 AI 调用失败：服务端使用记录异常",
    "ai_invalid_answers_format": "免费 AI 调用失败：服务端返回的 answers 格式无效",
    "ai_answers_count_mismatch": "免费 AI 调用失败：服务端返回的答案数量与空位数量不匹配",
    "expired": "免费 AI 批量调用失败：任务已超时",
}

_FREE_AI_LOG_TEXT_LIMIT = 240
_AI_RETRYABLE_STATUS_CODES = frozenset({429, 502, 503, 504})
_FREE_AI_BATCH_MAX_ITEMS = 64
_FREE_AI_BATCH_LOCAL_WAIT_SECONDS = 45.0
_FREE_AI_BATCH_MIN_POLL_MS = 200
_FREE_AI_BATCH_MAX_POLL_MS = 3000
_FREE_AI_BATCH_DEFAULT_POLL_MS = 1000
_FREE_AI_BATCH_MAX_CONCURRENCY = 4
_FREE_AI_MAX_REQUESTS_PER_MINUTE = 100
_FREE_AI_RATE_WINDOW_SECONDS = 60.0
_FREE_AI_BATCH_TERMINAL_STATUSES = frozenset({"completed", "partial", "failed", "expired"})
_FREE_AI_BATCH_ACTIVE_STATUSES = frozenset({"queued", "running"})
_FREE_AI_BATCH_CREATE_ACCEPTED_STATUS_CODES = frozenset({200, 202})
_FREE_AI_BATCH_SEMAPHORE = asyncio.Semaphore(_FREE_AI_BATCH_MAX_CONCURRENCY)

__all__ = [
    "FreeAITimeoutError",
    "FreeAIBatchCreateResult",
    "FreeAIBatchItem",
    "FreeAIBatchItemResult",
    "FreeAIBatchPollResult",
    "FreeAIBatchResolvedResult",
    "call_free_ai_api_async",
    "poll_free_ai_batch_task_async",
    "submit_free_ai_batch_task_async",
    "wait_free_ai_batch_result_async",
]


def _batch_submit_endpoint() -> str:
    return f"{AI_FREE_ENDPOINT.rstrip('/')}/batch"


def _batch_task_endpoint(task_id: str) -> str:
    return f"{AI_FREE_ENDPOINT.rstrip('/')}/tasks/{task_id}"


def _mask_user_id(user_id: Any) -> str:
    text = str(user_id or "").strip()
    if not text:
        return "unknown"
    if len(text) <= 2:
        return text
    return f"{text[:2]}***"


def _mask_device_id(device_id: Any) -> str:
    text = str(device_id or "").strip()
    if not text:
        return "unknown"
    if len(text) <= 8:
        return f"{text[:2]}***"
    return f"{text[:6]}***"


def _shorten_text(value: Any, limit: int = _FREE_AI_LOG_TEXT_LIMIT) -> str:
    text = str(value or "").replace("\r", " ").replace("\n", " ").strip()
    if not text:
        return ""
    if len(text) <= limit:
        return text
    return f"{text[:limit]}..."


def _serialize_log_value(value: Any) -> str:
    if isinstance(value, (dict, list)):
        try:
            return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        except Exception:
            return repr(value)
    return str(value or "")


def _extract_response_body_preview(response: Any) -> str:
    data = _extract_json_dict(response)
    if data:
        return _shorten_text(_serialize_log_value(data))
    try:
        return _shorten_text(getattr(response, "text", ""))
    except Exception:
        return ""


def _format_free_ai_error(detail: str, status_code: int) -> str:
    if detail in _FREE_AI_ERROR_MESSAGES:
        return _FREE_AI_ERROR_MESSAGES[detail]
    if detail:
        return f"免费 AI 调用失败：{detail}"
    if status_code > 0:
        return f"免费 AI 调用失败：服务端异常（HTTP {status_code}）"
    return "免费 AI 调用失败：未知错误"


def _extract_free_error_detail(response: Any) -> str:
    data = _extract_json_dict(response)
    detail = data.get("detail")
    if isinstance(detail, str) and detail.strip():
        return detail.strip()
    if isinstance(detail, dict):
        return _shorten_text(_serialize_log_value(detail))
    if isinstance(detail, list):
        return _shorten_text(_serialize_log_value(detail))
    error = data.get("error")
    if isinstance(error, str) and error.strip():
        return error.strip()
    message = data.get("message")
    if isinstance(message, str) and message.strip():
        return message.strip()
    return ""


def _normalize_batch_status(value: Any) -> str:
    status = str(value or "").strip().lower()
    if status in _FREE_AI_BATCH_TERMINAL_STATUSES or status in _FREE_AI_BATCH_ACTIVE_STATUSES:
        return status
    return "running"


def _clamp_poll_after_ms(value: Any) -> int:
    try:
        poll_after_ms = int(value)
    except Exception:
        poll_after_ms = _FREE_AI_BATCH_DEFAULT_POLL_MS
    return max(_FREE_AI_BATCH_MIN_POLL_MS, min(_FREE_AI_BATCH_MAX_POLL_MS, poll_after_ms))


def _get_free_ai_rate_limit_lock(ctx: ExecutionState) -> asyncio.Lock:
    loop = asyncio.get_running_loop()
    current_lock = getattr(ctx, "_free_ai_rate_limit_async_lock", None)
    current_loop = getattr(ctx, "_free_ai_rate_limit_async_lock_loop", None)
    if not isinstance(current_lock, asyncio.Lock) or current_loop is not loop:
        current_lock = asyncio.Lock()
        setattr(ctx, "_free_ai_rate_limit_async_lock", current_lock)
        setattr(ctx, "_free_ai_rate_limit_async_lock_loop", loop)
    return current_lock


def _prune_free_ai_request_timestamps(ctx: ExecutionState, now: float) -> None:
    while ctx.free_ai_request_timestamps and (now - ctx.free_ai_request_timestamps[0]) >= _FREE_AI_RATE_WINDOW_SECONDS:
        ctx.free_ai_request_timestamps.popleft()


async def _await_free_ai_rate_limit_async(ctx: ExecutionState | None) -> None:
    if ctx is None:
        return
    lock = _get_free_ai_rate_limit_lock(ctx)
    while True:
        wait_seconds = 0.0
        async with lock:
            now = time.monotonic()
            _prune_free_ai_request_timestamps(ctx, now)
            if len(ctx.free_ai_request_timestamps) < _FREE_AI_MAX_REQUESTS_PER_MINUTE:
                ctx.free_ai_request_timestamps.append(now)
                return
            oldest = ctx.free_ai_request_timestamps[0]
            wait_seconds = max(0.05, _FREE_AI_RATE_WINDOW_SECONDS - (now - oldest))
        await asyncio.sleep(wait_seconds)


def _extract_free_answers(data: Dict[str, Any], question_type: str, blank_count: Optional[int]) -> List[str]:
    raw_answers = data.get("answers")
    if not isinstance(raw_answers, list) or not raw_answers:
        raise RuntimeError("免费 AI 返回格式异常：缺少 answers 数组")

    answers: List[str] = []
    for item in raw_answers:
        if not isinstance(item, str):
            raise RuntimeError("免费 AI 返回格式异常：answers 内含非字符串项")
        text = item.strip()
        if not text:
            raise RuntimeError("免费 AI 返回格式异常：answers 内含空字符串")
        answers.append(text)

    if question_type == "fill_blank":
        if len(answers) != 1:
            raise RuntimeError(f"免费 AI 返回格式异常：fill_blank 期望 1 个答案，实际 {len(answers)} 个")
        return answers

    expected = int(blank_count or 0)
    if expected <= 0:
        raise RuntimeError("免费 AI 返回格式异常：multi_fill_blank 缺少有效 blank_count")
    if len(answers) != expected:
        raise RuntimeError(f"免费 AI 返回格式异常：multi_fill_blank 期望 {expected} 个答案，实际 {len(answers)} 个")
    return answers


def _build_free_ai_headers(device_id: str) -> Dict[str, str]:
    return {
        "Content-Type": "application/json",
        "X-Device-ID": device_id,
        **DEFAULT_HTTP_HEADERS,
    }


def _normalize_batch_items(items: Iterable[FreeAIBatchItem]) -> List[FreeAIBatchItem]:
    normalized: List[FreeAIBatchItem] = []
    seen_item_ids: set[str] = set()
    for raw_item in items:
        item_id = str(getattr(raw_item, "item_id", "") or "").strip()
        question_type = str(getattr(raw_item, "question_type", "") or "").strip().lower()
        question_content = str(getattr(raw_item, "question_content", "") or "").strip()
        system_prompt = str(getattr(raw_item, "system_prompt", "") or "").strip()
        blank_count = getattr(raw_item, "blank_count", None)
        normalized_blank_count = None if blank_count is None else int(blank_count)
        if not item_id:
            raise RuntimeError(_format_free_ai_error("item_id_required", 400))
        if item_id in seen_item_ids:
            raise RuntimeError(_format_free_ai_error("duplicate_item_id", 400))
        if not question_content:
            raise RuntimeError(_format_free_ai_error("question_content_required", 400))
        if question_type not in {"fill_blank", "multi_fill_blank"}:
            raise RuntimeError(_format_free_ai_error("invalid_question_type", 400))
        if question_type == "multi_fill_blank":
            if normalized_blank_count is None:
                raise RuntimeError(_format_free_ai_error("blank_count_required", 400))
            if normalized_blank_count <= 0:
                raise RuntimeError(_format_free_ai_error("invalid_blank_count", 400))
        normalized.append(
            FreeAIBatchItem(
                item_id=item_id,
                question_type=question_type,
                question_content=question_content,
                blank_count=normalized_blank_count,
                system_prompt=system_prompt,
            )
        )
        seen_item_ids.add(item_id)
    if not normalized:
        raise RuntimeError(_format_free_ai_error("items_required", 400))
    return normalized


def _chunk_batch_items(items: List[FreeAIBatchItem]) -> List[List[FreeAIBatchItem]]:
    return [
        items[start:start + _FREE_AI_BATCH_MAX_ITEMS]
        for start in range(0, len(items), _FREE_AI_BATCH_MAX_ITEMS)
    ]


def _build_batch_submit_payload(
    *,
    user_id: int,
    system_prompt: str,
    items: List[FreeAIBatchItem],
) -> Dict[str, Any]:
    payload_items: List[Dict[str, Any]] = []
    for item in items:
        payload_item: Dict[str, Any] = {
            "item_id": item.item_id,
            "question_type": item.question_type,
            "question_content": item.question_content,
        }
        if item.question_type == "multi_fill_blank":
            payload_item["blank_count"] = int(item.blank_count or 0)
        if item.system_prompt:
            payload_item["system_prompt"] = item.system_prompt
        payload_items.append(payload_item)
    payload: Dict[str, Any] = {
        "user_id": int(user_id),
        "items": payload_items,
    }
    if system_prompt:
        payload["system_prompt"] = system_prompt
    return payload


def _log_free_ai_request_start(
    *,
    user_id: int,
    device_id: str,
    question_type: str,
    blank_count: Optional[int],
    question: str,
    system_prompt: str = "",
) -> None:
    logger.info(
        "免费 AI 请求开始 | endpoint=%s | question_type=%s | blank_count=%s | user_id=%s | device=%s | system_prompt_len=%s | question_preview=%s",
        AI_FREE_ENDPOINT,
        question_type,
        blank_count if blank_count is not None else "-",
        _mask_user_id(user_id),
        _mask_device_id(device_id),
        len(str(system_prompt or "").strip()),
        _shorten_text(question, 80),
    )


def _log_free_ai_request_failure(
    *,
    user_id: int,
    device_id: str,
    question_type: str,
    blank_count: Optional[int],
    status_code: int,
    detail: str,
    response: Any,
) -> None:
    logger.error(
        "免费 AI 请求失败 | endpoint=%s | question_type=%s | blank_count=%s | user_id=%s | device=%s | status=%s | detail=%s | body=%s",
        AI_FREE_ENDPOINT,
        question_type,
        blank_count if blank_count is not None else "-",
        _mask_user_id(user_id),
        _mask_device_id(device_id),
        status_code or "-",
        detail or "-",
        _extract_response_body_preview(response) or "-",
    )


def _log_free_ai_format_error(
    *,
    user_id: int,
    device_id: str,
    question_type: str,
    blank_count: Optional[int],
    payload: Dict[str, Any],
    error: Exception,
) -> None:
    logger.error(
        "免费 AI 返回格式异常 | question_type=%s | blank_count=%s | user_id=%s | device=%s | error=%s | payload=%s",
        question_type,
        blank_count if blank_count is not None else "-",
        _mask_user_id(user_id),
        _mask_device_id(device_id),
        error,
        _shorten_text(_serialize_log_value(payload)),
    )


def _log_batch_submit_start(
    *,
    user_id: int,
    device_id: str,
    item_count: int,
    system_prompt: str,
) -> None:
    logger.info(
        "免费 AI 批量任务创建开始 | endpoint=%s | item_count=%s | user_id=%s | device=%s | system_prompt_len=%s",
        _batch_submit_endpoint(),
        item_count,
        _mask_user_id(user_id),
        _mask_device_id(device_id),
        len(str(system_prompt or "").strip()),
    )


def _log_batch_poll_start(
    *,
    task_id: str,
    device_id: str,
) -> None:
    logger.debug(
        "免费 AI 批量任务查询 | task_id=%s | device=%s",
        task_id,
        _mask_device_id(device_id),
    )


def _log_batch_task_terminal(
    *,
    task_id: str,
    status: str,
    completed_items: int,
    failed_items: int,
    pending_items: int,
) -> None:
    logger.info(
        "免费 AI 批量任务完成 | task_id=%s | status=%s | completed=%s | failed=%s | pending=%s",
        task_id,
        status,
        completed_items,
        failed_items,
        pending_items,
    )


async def _ensure_free_ai_identity_async() -> tuple[int, str]:
    snapshot = get_session_snapshot()
    user_id = int(snapshot.get("user_id") or 0)
    device_id = str(snapshot.get("device_id") or "").strip()
    if not device_id:
        device_id = str(get_device_id() or "").strip()

    if user_id > 0 and device_id:
        logger.info(
            "免费 AI 身份就绪 | user_id=%s | device=%s | source=session",
            _mask_user_id(user_id),
            _mask_device_id(device_id),
        )
        return user_id, device_id

    logger.info(
        "免费 AI 身份缺失，尝试自动领取试用 | user_id=%s | device=%s",
        _mask_user_id(user_id),
        _mask_device_id(device_id),
    )
    try:
        await activate_trial_async()
    except RandomIPAuthError as exc:
        raise RuntimeError(f"免费 AI 身份初始化失败：{format_random_ip_error(exc)}") from exc
    except Exception as exc:
        raise RuntimeError(f"免费 AI 身份初始化失败：{exc}") from exc

    snapshot = get_session_snapshot()
    user_id = int(snapshot.get("user_id") or 0)
    device_id = str(snapshot.get("device_id") or "").strip()
    if not device_id:
        device_id = str(get_device_id() or "").strip()
    if user_id <= 0 or not device_id:
        raise RuntimeError("免费 AI 身份初始化失败：未获取到有效 user_id/device_id")
    logger.info(
        "免费 AI 身份领取成功 | user_id=%s | device=%s",
        _mask_user_id(user_id),
        _mask_device_id(device_id),
    )
    return user_id, device_id


async def call_free_ai_api_async(
    question: str,
    question_type: str,
    blank_count: Optional[int],
    system_prompt: str = "",
    timeout: int = _AI_REQUEST_TIMEOUT_SECONDS,
    ctx: ExecutionState | None = None,
) -> List[str]:
    user_id, device_id = await _ensure_free_ai_identity_async()
    _log_free_ai_request_start(
        user_id=user_id,
        device_id=device_id,
        question_type=question_type,
        blank_count=blank_count,
        question=question,
        system_prompt=system_prompt,
    )
    headers = _build_free_ai_headers(device_id)
    payload: Dict[str, Any] = {
        "user_id": int(user_id),
        "question_type": question_type,
        "question_content": question,
    }
    normalized_system_prompt = str(system_prompt or "").strip()
    if normalized_system_prompt:
        payload["system_prompt"] = normalized_system_prompt
    if question_type == "multi_fill_blank":
        payload["blank_count"] = int(blank_count or 0)

    async def _send_request():
        await _await_free_ai_rate_limit_async(ctx)
        response = await http_client.apost(AI_FREE_ENDPOINT, headers=headers, json=payload, timeout=timeout, proxies={})
        status_code = int(getattr(response, "status_code", 0) or 0)
        if status_code in _AI_RETRYABLE_STATUS_CODES:
            response.raise_for_status()
        return response

    try:
        response = await _aexecute_ai_request_with_retry("free_ai", _send_request)
    except Exception as exc:
        if _is_ai_timeout_exception(exc):
            raise FreeAITimeoutError("免费 AI 调用超时") from exc
        raise
    status_code = int(getattr(response, "status_code", 0) or 0)
    if status_code != 200:
        detail = _extract_free_error_detail(response)
        _log_free_ai_request_failure(
            user_id=user_id,
            device_id=device_id,
            question_type=question_type,
            blank_count=blank_count,
            status_code=status_code,
            detail=detail,
            response=response,
        )
        raise RuntimeError(_format_free_ai_error(detail, status_code))
    data = _extract_json_dict(response)
    try:
        answers = _extract_free_answers(data, question_type, blank_count)
    except Exception as exc:
        _log_free_ai_format_error(
            user_id=user_id,
            device_id=device_id,
            question_type=question_type,
            blank_count=blank_count,
            payload=data,
            error=exc,
        )
        raise
    logger.info(
        "免费 AI 请求成功 | question_type=%s | blank_count=%s | user_id=%s | device=%s | answers_count=%s",
        question_type,
        blank_count if blank_count is not None else "-",
        _mask_user_id(user_id),
        _mask_device_id(device_id),
        len(answers),
    )
    return answers


async def _submit_free_ai_batch_task_with_identity_async(
    items: Iterable[FreeAIBatchItem],
    *,
    user_id: int,
    device_id: str,
    system_prompt: str = "",
    timeout: int = _AI_REQUEST_TIMEOUT_SECONDS,
    ctx: ExecutionState | None = None,
) -> FreeAIBatchCreateResult:
    normalized_items = _normalize_batch_items(items)
    if len(normalized_items) > _FREE_AI_BATCH_MAX_ITEMS:
        raise RuntimeError(_format_free_ai_error("too_many_items", 400))
    normalized_system_prompt = str(system_prompt or "").strip()
    _log_batch_submit_start(
        user_id=user_id,
        device_id=device_id,
        item_count=len(normalized_items),
        system_prompt=normalized_system_prompt,
    )
    headers = _build_free_ai_headers(device_id)
    payload = _build_batch_submit_payload(
        user_id=user_id,
        system_prompt=normalized_system_prompt,
        items=normalized_items,
    )

    async def _send_request():
        await _await_free_ai_rate_limit_async(ctx)
        response = await http_client.apost(
            _batch_submit_endpoint(),
            headers=headers,
            json=payload,
            timeout=timeout,
            proxies={},
        )
        status_code = int(getattr(response, "status_code", 0) or 0)
        if status_code in _AI_RETRYABLE_STATUS_CODES:
            response.raise_for_status()
        return response

    try:
        response = await _aexecute_ai_request_with_retry("free_ai_batch_submit", _send_request)
    except Exception as exc:
        if _is_ai_timeout_exception(exc):
            raise FreeAITimeoutError("免费 AI 批量任务创建超时") from exc
        raise
    status_code = int(getattr(response, "status_code", 0) or 0)
    if status_code not in _FREE_AI_BATCH_CREATE_ACCEPTED_STATUS_CODES:
        detail = _extract_free_error_detail(response)
        raise RuntimeError(_format_free_ai_error(detail, status_code))
    data = _extract_json_dict(response)
    task_id = str(data.get("task_id") or "").strip()
    if not task_id:
        raise RuntimeError("免费 AI 批量任务创建失败：缺少 task_id")
    return FreeAIBatchCreateResult(
        task_id=task_id,
        status=_normalize_batch_status(data.get("status")),
        total_items=max(0, int(data.get("total_items") or len(normalized_items))),
        batch_count=max(1, int(data.get("batch_count") or 1)),
        poll_after_ms=_clamp_poll_after_ms(data.get("poll_after_ms")),
        expires_at=str(data.get("expires_at") or "").strip(),
    )


async def submit_free_ai_batch_task_async(
    items: Iterable[FreeAIBatchItem],
    *,
    system_prompt: str = "",
    timeout: int = _AI_REQUEST_TIMEOUT_SECONDS,
    ctx: ExecutionState | None = None,
) -> FreeAIBatchCreateResult:
    user_id, device_id = await _ensure_free_ai_identity_async()
    return await _submit_free_ai_batch_task_with_identity_async(
        items,
        user_id=user_id,
        device_id=device_id,
        system_prompt=system_prompt,
        timeout=timeout,
        ctx=ctx,
    )


def _extract_batch_poll_items(data: Dict[str, Any]) -> List[FreeAIBatchItemResult]:
    results: List[FreeAIBatchItemResult] = []
    for raw_item in list(data.get("items") or []):
        if not isinstance(raw_item, dict):
            continue
        item_id = str(raw_item.get("item_id") or "").strip()
        if not item_id:
            continue
        answers: List[str] = []
        raw_answers = raw_item.get("answers")
        if isinstance(raw_answers, list):
            answers = [str(item or "").strip() for item in raw_answers if str(item or "").strip()]
        results.append(
            FreeAIBatchItemResult(
                item_id=item_id,
                status=str(raw_item.get("status") or "").strip().lower() or "unknown",
                answers=answers,
                detail=str(raw_item.get("detail") or "").strip(),
            )
        )
    return results


async def _poll_free_ai_batch_task_with_identity_async(
    task_id: str,
    *,
    device_id: str,
    timeout: int = _AI_REQUEST_TIMEOUT_SECONDS,
    ctx: ExecutionState | None = None,
) -> FreeAIBatchPollResult:
    normalized_task_id = str(task_id or "").strip()
    if not normalized_task_id:
        raise RuntimeError("免费 AI 批量任务查询失败：task_id 不能为空")
    _log_batch_poll_start(task_id=normalized_task_id, device_id=device_id)
    headers = _build_free_ai_headers(device_id)

    async def _send_request():
        await _await_free_ai_rate_limit_async(ctx)
        response = await http_client.aget(
            _batch_task_endpoint(normalized_task_id),
            headers=headers,
            timeout=timeout,
            proxies={},
        )
        status_code = int(getattr(response, "status_code", 0) or 0)
        if status_code in _AI_RETRYABLE_STATUS_CODES:
            response.raise_for_status()
        return response

    try:
        response = await _aexecute_ai_request_with_retry("free_ai_batch_poll", _send_request)
    except Exception as exc:
        if _is_ai_timeout_exception(exc):
            raise FreeAITimeoutError("免费 AI 批量任务查询超时") from exc
        raise
    status_code = int(getattr(response, "status_code", 0) or 0)
    if status_code != 200:
        detail = _extract_free_error_detail(response)
        raise RuntimeError(_format_free_ai_error(detail, status_code))
    data = _extract_json_dict(response)
    result = FreeAIBatchPollResult(
        task_id=str(data.get("task_id") or normalized_task_id).strip() or normalized_task_id,
        status=_normalize_batch_status(data.get("status")),
        total_items=max(0, int(data.get("total_items") or 0)),
        completed_items=max(0, int(data.get("completed_items") or 0)),
        failed_items=max(0, int(data.get("failed_items") or 0)),
        pending_items=max(0, int(data.get("pending_items") or 0)),
        expires_at=str(data.get("expires_at") or "").strip(),
        poll_after_ms=_clamp_poll_after_ms(data.get("poll_after_ms")),
        items=_extract_batch_poll_items(data),
        detail=_extract_free_error_detail(response),
    )
    if result.status in _FREE_AI_BATCH_TERMINAL_STATUSES:
        _log_batch_task_terminal(
            task_id=result.task_id,
            status=result.status,
            completed_items=result.completed_items,
            failed_items=result.failed_items,
            pending_items=result.pending_items,
        )
    return result


async def poll_free_ai_batch_task_async(
    task_id: str,
    *,
    timeout: int = _AI_REQUEST_TIMEOUT_SECONDS,
    ctx: ExecutionState | None = None,
) -> FreeAIBatchPollResult:
    _user_id, device_id = await _ensure_free_ai_identity_async()
    return await _poll_free_ai_batch_task_with_identity_async(
        task_id,
        device_id=device_id,
        timeout=timeout,
        ctx=ctx,
    )


def _consume_batch_poll_result(
    result: FreeAIBatchPollResult,
    expected_items: Dict[str, FreeAIBatchItem],
    completed: Dict[str, List[str]],
    failed: Dict[str, str],
) -> None:
    for item_result in list(result.items or []):
        expected_item = expected_items.get(item_result.item_id)
        if expected_item is None:
            continue
        if item_result.status == "completed":
            try:
                answers_payload = {"answers": list(item_result.answers or [])}
                answers = _extract_free_answers(
                    answers_payload,
                    expected_item.question_type,
                    expected_item.blank_count,
                )
            except Exception as exc:
                completed.pop(item_result.item_id, None)
                failed[item_result.item_id] = str(exc)
                continue
            completed[item_result.item_id] = answers
            failed.pop(item_result.item_id, None)
            continue
        if item_result.status in {"failed", "expired"}:
            failed[item_result.item_id] = _format_free_ai_error(item_result.detail, 0)


async def wait_free_ai_batch_result_async(
    items: Iterable[FreeAIBatchItem],
    *,
    system_prompt: str = "",
    timeout: int = _AI_REQUEST_TIMEOUT_SECONDS,
    ctx: ExecutionState | None = None,
) -> FreeAIBatchResolvedResult:
    normalized_items = _normalize_batch_items(items)
    async with _FREE_AI_BATCH_SEMAPHORE:
        user_id, device_id = await _ensure_free_ai_identity_async()
        completed: Dict[str, List[str]] = {}
        failed: Dict[str, str] = {}
        task_ids: List[str] = []
        pending_tasks: List[_PendingBatchTask] = []

        for chunk in _chunk_batch_items(normalized_items):
            try:
                create_result = await _submit_free_ai_batch_task_with_identity_async(
                    chunk,
                    user_id=user_id,
                    device_id=device_id,
                    system_prompt=system_prompt,
                    timeout=timeout,
                    ctx=ctx,
                )
            except Exception as exc:
                error_text = str(exc)
                for item in chunk:
                    failed[item.item_id] = error_text
                continue
            task_ids.append(create_result.task_id)
            pending_tasks.append(
                _PendingBatchTask(
                    task_id=create_result.task_id,
                    expected_items={item.item_id: item for item in chunk},
                    next_poll_at=time.monotonic() + (create_result.poll_after_ms / 1000.0),
                    expires_at=create_result.expires_at,
                )
            )

        deadline = time.monotonic() + _FREE_AI_BATCH_LOCAL_WAIT_SECONDS
        while pending_tasks and time.monotonic() < deadline:
            now = time.monotonic()
            ready_tasks = [task for task in pending_tasks if task.next_poll_at <= now]
            if not ready_tasks:
                next_poll_at = min(task.next_poll_at for task in pending_tasks)
                await asyncio.sleep(max(0.05, min(next_poll_at - now, 0.5)))
                continue
            for task in list(ready_tasks):
                try:
                    poll_result = await _poll_free_ai_batch_task_with_identity_async(
                        task.task_id,
                        device_id=device_id,
                        timeout=timeout,
                        ctx=ctx,
                    )
                    _consume_batch_poll_result(
                        poll_result,
                        task.expected_items,
                        completed,
                        failed,
                    )
                except Exception as exc:
                    error_text = str(exc)
                    for item_id in task.expected_items:
                        if item_id not in completed:
                            failed[item_id] = error_text
                    pending_tasks.remove(task)
                    continue

                if poll_result.status in _FREE_AI_BATCH_ACTIVE_STATUSES:
                    task.next_poll_at = time.monotonic() + (poll_result.poll_after_ms / 1000.0)
                    continue

                unresolved_item_ids = {
                    item_id
                    for item_id in task.expected_items
                    if item_id not in completed and item_id not in failed
                }
                if poll_result.status == "failed":
                    task_error = _format_free_ai_error(poll_result.detail, 0)
                    for item_id in unresolved_item_ids:
                        failed[item_id] = task_error
                elif poll_result.status == "partial":
                    for item_id in unresolved_item_ids:
                        failed.setdefault(item_id, "免费 AI 批量任务结果不完整")
                elif poll_result.status == "expired":
                    task_error = _format_free_ai_error(poll_result.detail or "expired", 0)
                    for item_id in unresolved_item_ids:
                        failed.setdefault(item_id, task_error)
                else:
                    for item_id in unresolved_item_ids:
                        failed.setdefault(item_id, "免费 AI 批量任务结果异常")
                pending_tasks.remove(task)

        pending: set[str] = set()
        for task in pending_tasks:
            for item_id in task.expected_items:
                if item_id not in completed and item_id not in failed:
                    pending.add(item_id)
        return FreeAIBatchResolvedResult(
            completed=completed,
            failed=failed,
            pending=pending,
            task_ids=task_ids,
        )
