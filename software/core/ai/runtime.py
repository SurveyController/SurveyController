import asyncio
import logging
import re
from enum import StrEnum
from typing import Any, Callable, List, Optional, Union, cast

import httpx

from software.core.task import ExecutionState
from software.core.ai.batch_models import PendingAIAnswer
from software.integrations.ai.errors import AIConfigurationError
from software.logging.log_utils import log_suppressed_exception

from software.integrations.ai.client import agenerate_answer
from software.core.text_constants import WHITESPACE_PATTERN


class AIRuntimeError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        kind: "AIErrorKind | None" = None,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.kind = kind or AIErrorKind.UNKNOWN
        self.retryable = bool(retryable)


class AIErrorKind(StrEnum):
    CONFIGURATION = "configuration"
    NETWORK = "network"
    RESPONSE = "response"
    UNKNOWN = "unknown"


_AI_FILL_MAX_ATTEMPTS = 4
_AI_FILL_RETRY_BACKOFF_SECONDS = 0.4


def is_ai_timeout_runtime_error(error: object) -> bool:
    current = error if isinstance(error, BaseException) else None
    visited: set[int] = set()
    while current is not None and id(current) not in visited:
        visited.add(id(current))
        text = str(current or "").strip().lower()
        if "timed out" in text or "timeout" in text or "超时" in text:
            return True
        next_error = getattr(current, "__cause__", None) or getattr(current, "__context__", None)
        current = next_error if isinstance(next_error, BaseException) else None
    return False


def _normalize_text(value: Optional[str]) -> str:
    if not value:
        return ""
    return WHITESPACE_PATTERN.sub(" ", str(value)).strip()


def _cleanup_question_title(raw_title: str) -> str:
    title = _normalize_text(raw_title)
    if not title:
        return ""
    title = re.sub(r"^\*?\s*\d+[\.、]?\s*", "", title)
    title = title.replace("【单选题】", "").replace("【多选题】", "")
    return title.strip()


def build_ai_question_prompt(
    question_title: str,
    *,
    description: str = "",
    question_number: int = 0,
) -> str:
    title = _cleanup_question_title(question_title)
    if not title:
        title = f"第{int(question_number or 0)}题" if int(question_number or 0) > 0 else ""
    extra_description = _normalize_text(description)
    if extra_description and extra_description not in title:
        title = f"{title}\n补充说明：{extra_description}" if title else extra_description
    if not title:
        return ""

    try:
        from surveycore.core.persona.context import build_ai_context_prompt

        context_prompt = build_ai_context_prompt()
        if context_prompt:
            return f"{context_prompt}\n\n请回答以下问卷问题：{title}"
    except Exception as exc:
        log_suppressed_exception(
            "build_ai_question_prompt: from surveycore.core.persona.context import build_ai_context_prompt",
            exc,
            level=logging.WARNING,
        )
    return title


def build_ai_option_fill_prompt(
    *,
    question_title: str,
    question_number: int,
    option_text: str = "",
) -> str:
    title = _cleanup_question_title(question_title)
    if not title:
        title = f"第{int(question_number or 0)}题" if int(question_number or 0) > 0 else ""
    if not title:
        title = "当前题目"
    prompt = f"{title}\n\n当前需要填写的是某个选择题选项后面的补充输入框。"
    normalized_option_text = _normalize_text(option_text)
    if normalized_option_text:
        prompt += f"\n已选择的选项是：{normalized_option_text}"
    prompt += "\n请只输出最终要填写的内容，不要解释。"
    return prompt


def build_pending_ai_text_answer(question_num: int, blank_index: int) -> PendingAIAnswer:
    return PendingAIAnswer(
        item_id=f"q{int(question_num or 0)}",
        expected_count=max(1, int(blank_index or 0) + 1),
    )


def build_pending_ai_option_fill_answer(question_num: int, option_index: int) -> PendingAIAnswer:
    return PendingAIAnswer(
        item_id=f"q{int(question_num or 0)}_opt{int(option_index or 0)}",
        expected_count=1,
    )


def is_pending_ai_answer(value: object) -> bool:
    return isinstance(value, PendingAIAnswer)


async def agenerate_ai_answer(
    question_title: str,
    *,
    question_type: str = "fill_blank",
    blank_count: Optional[int] = None,
    description: str = "",
    question_number: int = 0,
    ctx: ExecutionState | None = None,
) -> Union[str, List[str]]:
    cleaned = build_ai_question_prompt(
        question_title,
        description=description,
        question_number=question_number,
    )
    if not cleaned:
        raise AIRuntimeError("题干为空，无法调用 AI", kind=AIErrorKind.CONFIGURATION)

    return cast(
        Union[str, List[str]],
        await generate_ai_answer_with_retry(
            cleaned,
            question_type=question_type,
            blank_count=blank_count,
            ctx=ctx,
        ),
    )


async def generate_ai_answer_with_retry(
    prompt: str,
    *,
    question_type: str = "fill_blank",
    blank_count: Optional[int] = None,
    ctx: ExecutionState | None = None,
    validate: Callable[[Any], Any] | None = None,
    provider_call: Callable[..., Any] | None = None,
) -> Any:
    if not str(prompt or "").strip():
        raise AIRuntimeError("题干为空，无法调用 AI", kind=AIErrorKind.CONFIGURATION)

    last_error: Exception | None = None
    for attempt in range(1, _AI_FILL_MAX_ATTEMPTS + 1):
        try:
            call = provider_call or agenerate_answer
            answer = await call(
                prompt,
                question_type=question_type,
                blank_count=blank_count,
                ctx=ctx,
            )
            if validate is not None:
                return validate(answer)
            if question_type == "multi_fill_blank":
                if not isinstance(answer, list):
                    if not answer or not str(answer).strip():
                        raise AIRuntimeError(
                            "AI 未返回有效答案",
                            kind=AIErrorKind.RESPONSE,
                            retryable=True,
                        )
                    return str(answer).strip()
                cleaned_answers: List[str] = []
                for item in answer:
                    text = str(item or "").strip()
                    if not text:
                        raise AIRuntimeError(
                            "AI 返回的多项填空答案包含空值",
                            kind=AIErrorKind.RESPONSE,
                            retryable=True,
                        )
                    cleaned_answers.append(text)
                if not cleaned_answers:
                    raise AIRuntimeError(
                        "AI 未返回有效答案",
                        kind=AIErrorKind.RESPONSE,
                        retryable=True,
                    )
                return cleaned_answers
            if not answer or not str(answer).strip():
                raise AIRuntimeError(
                    "AI 未返回有效答案",
                    kind=AIErrorKind.RESPONSE,
                    retryable=True,
                )
            return str(answer).strip()
        except Exception as exc:
            last_error = exc
            if isinstance(exc, AIRuntimeError):
                kind = exc.kind
                retryable = exc.retryable
            elif isinstance(exc, httpx.TransportError):
                kind = AIErrorKind.NETWORK
                retryable = True
            elif isinstance(exc, httpx.HTTPStatusError):
                kind = AIErrorKind.NETWORK
                retryable = exc.response.status_code == 429 or exc.response.status_code >= 500
            elif isinstance(exc, AIConfigurationError):
                kind = AIErrorKind.CONFIGURATION
                retryable = False
            else:
                kind = AIErrorKind.UNKNOWN
                retryable = False
            if attempt >= _AI_FILL_MAX_ATTEMPTS or not retryable:
                raise AIRuntimeError(
                    f"AI 调用失败：{exc}",
                    kind=kind,
                    retryable=False,
                ) from exc
            logging.warning(
                "AI 生成失败，准备重试 | attempt=%s/%s | question_type=%s | error=%s",
                attempt,
                _AI_FILL_MAX_ATTEMPTS,
                question_type,
                exc,
            )
            await asyncio.sleep(_AI_FILL_RETRY_BACKOFF_SECONDS)
    if last_error is not None:
        raise AIRuntimeError(
            f"AI 调用失败：{last_error}",
            kind=AIErrorKind.UNKNOWN,
            retryable=False,
        ) from last_error
    raise AIRuntimeError("AI 调用失败：未知错误", kind=AIErrorKind.UNKNOWN)
