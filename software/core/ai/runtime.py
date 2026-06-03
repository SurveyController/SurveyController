import asyncio
import logging
import re
from typing import List, Optional, Union

from software.logging.log_utils import log_suppressed_exception

from software.integrations.ai.client import agenerate_answer
from software.integrations.ai.client import FreeAITimeoutError
from software.app.config import _HTML_SPACE_RE


class AIRuntimeError(RuntimeError):
    """AI 填空运行时错误（需要终止任务）。"""


_AI_FILL_MAX_ATTEMPTS = 4
_AI_FILL_RETRY_BACKOFF_SECONDS = 0.4


def _is_retryable_ai_generation_error(error: Exception) -> bool:
    text = str(error or "").strip().lower()
    if not text:
        return True
    non_retryable_markers = (
        "题干为空",
        "无法获取",
        "请先配置 api key",
        "ai 配置不完整",
        "ai配置不完整",
    )
    return not any(marker in text for marker in non_retryable_markers)


def is_free_ai_runtime_error(error: object) -> bool:
    if is_ai_timeout_runtime_error(error):
        return True
    text = str(error or "").strip()
    return "免费 AI" in text or "免费AI" in text


def is_ai_timeout_runtime_error(error: object) -> bool:
    current = error if isinstance(error, BaseException) else None
    visited: set[int] = set()
    while current is not None and id(current) not in visited:
        visited.add(id(current))
        if isinstance(current, FreeAITimeoutError):
            return True
        text = str(current or "").strip().lower()
        if "timed out" in text or "timeout" in text or "超时" in text:
            return True
        next_error = getattr(current, "__cause__", None) or getattr(current, "__context__", None)
        current = next_error if isinstance(next_error, BaseException) else None
    return False




def _normalize_text(value: Optional[str]) -> str:
    if not value:
        return ""
    return _HTML_SPACE_RE.sub(" ", str(value)).strip()


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
        from software.core.persona.context import build_ai_context_prompt
        context_prompt = build_ai_context_prompt()
        if context_prompt:
            return f"{context_prompt}\n\n请回答以下问卷问题：{title}"
    except Exception as exc:
        log_suppressed_exception(
            "build_ai_question_prompt: from software.core.persona.context import build_ai_context_prompt",
            exc,
            level=logging.WARNING,
        )
    return title


async def agenerate_ai_answer(
    question_title: str,
    *,
    question_type: str = "fill_blank",
    blank_count: Optional[int] = None,
    description: str = "",
    question_number: int = 0,
) -> Union[str, List[str]]:
    cleaned = build_ai_question_prompt(
        question_title,
        description=description,
        question_number=question_number,
    )
    if not cleaned:
        raise AIRuntimeError("题干为空，无法调用 AI")

    last_error: Exception | None = None
    for attempt in range(1, _AI_FILL_MAX_ATTEMPTS + 1):
        try:
            answer = await agenerate_answer(
                cleaned,
                question_type=question_type,
                blank_count=blank_count,
            )
            if question_type == "multi_fill_blank":
                if not isinstance(answer, list):
                    if not answer or not str(answer).strip():
                        raise AIRuntimeError("AI 未返回有效答案")
                    return str(answer).strip()
                cleaned_answers: List[str] = []
                for item in answer:
                    text = str(item or "").strip()
                    if not text:
                        raise AIRuntimeError("AI 返回的多项填空答案包含空值")
                    cleaned_answers.append(text)
                if not cleaned_answers:
                    raise AIRuntimeError("AI 未返回有效答案")
                return cleaned_answers
            if not answer or not str(answer).strip():
                raise AIRuntimeError("AI 未返回有效答案")
            return str(answer).strip()
        except Exception as exc:
            last_error = exc
            if attempt >= _AI_FILL_MAX_ATTEMPTS or not _is_retryable_ai_generation_error(exc):
                raise AIRuntimeError(f"AI 调用失败：{exc}") from exc
            logging.warning(
                "AI 生成失败，准备重试 | attempt=%s/%s | question_type=%s | error=%s",
                attempt,
                _AI_FILL_MAX_ATTEMPTS,
                question_type,
                exc,
            )
            await asyncio.sleep(_AI_FILL_RETRY_BACKOFF_SECONDS)
    if last_error is not None:
        raise AIRuntimeError(f"AI 调用失败：{last_error}") from last_error
    raise AIRuntimeError("AI 调用失败：未知错误")



