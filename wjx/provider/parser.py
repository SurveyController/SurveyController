from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Tuple

from surveycore.providers.errors import (
    SurveyEnterpriseUnavailableError,
    SurveyNotOpenError,
    SurveyPausedError,
    SurveyStoppedError,
)
from surveycore.wjx.provider.html_parser import _normalize_html_text
from surveycore.wjx.provider.parser import (
    ENTERPRISE_UNAVAILABLE_SURVEY_ERROR_MESSAGE,
    NOT_OPEN_SURVEY_ERROR_MESSAGE,
    PAUSED_SURVEY_ERROR_MESSAGE,
    STOPPED_SURVEY_ERROR_MESSAGE,
    _PARSE_RETRY_ATTEMPTS,
    _PARSE_RETRY_DELAY_SECONDS,
    _build_unparseable_page_summary,
    _parse_wjx_html as _parse_wjx_html,
    _raise_wjx_page_state_errors as _raise_wjx_page_state_errors,
    build_not_open_survey_message,
    is_enterprise_unavailable_survey_page,
    is_paused_survey_page,
    is_stopped_survey_page,
)

import software.network.http as http_client
from software.app.config import DEFAULT_HTTP_HEADERS


async def parse_wjx_survey(url: str) -> Tuple[List[Dict[str, Any]], str]:
    resp = None
    try:
        info: List[Dict[str, Any]] = []
        title = ""
        for attempt in range(1, _PARSE_RETRY_ATTEMPTS + 1):
            resp = await http_client.aget(url, timeout=12, headers=DEFAULT_HTTP_HEADERS, proxies={})
            resp.raise_for_status()
            info, title = _parse_wjx_html(resp.text)
            if info:
                break
            if attempt >= _PARSE_RETRY_ATTEMPTS:
                break
            summary = _build_unparseable_page_summary(resp.text)
            logging.warning(
                "问卷星解析命中临时空页面，准备重试 | url=%r | attempt=%s/%s | summary=%s",
                url,
                attempt,
                _PARSE_RETRY_ATTEMPTS,
                summary,
            )
            await asyncio.sleep(_PARSE_RETRY_DELAY_SECONDS)
    except (
        SurveyPausedError,
        SurveyStoppedError,
        SurveyEnterpriseUnavailableError,
        SurveyNotOpenError,
    ):
        raise
    except Exception as exc:
        if getattr(exc, "winerror", None) == 10013:
            raise RuntimeError(f"无法获取问卷网页：WinError 10013：{exc}") from exc
        raise RuntimeError(f"无法获取问卷网页：{exc}") from exc
    if not info:
        summary = _build_unparseable_page_summary(getattr(resp, "text", ""))
        raise RuntimeError(f"无法打开问卷链接，HTTP 页面未返回可解析题目：{summary}")
    normalized_title = _normalize_html_text(title) if title else ""
    return info, normalized_title


__all__ = [
    "PAUSED_SURVEY_ERROR_MESSAGE",
    "STOPPED_SURVEY_ERROR_MESSAGE",
    "ENTERPRISE_UNAVAILABLE_SURVEY_ERROR_MESSAGE",
    "NOT_OPEN_SURVEY_ERROR_MESSAGE",
    "SurveyPausedError",
    "SurveyStoppedError",
    "SurveyEnterpriseUnavailableError",
    "SurveyNotOpenError",
    "build_not_open_survey_message",
    "is_enterprise_unavailable_survey_page",
    "is_paused_survey_page",
    "is_stopped_survey_page",
    "parse_wjx_survey",
]
