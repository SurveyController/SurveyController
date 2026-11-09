from __future__ import annotations

import asyncio
import logging
import re
from typing import Any, Dict, List, Tuple
from urllib.parse import urljoin

from surveycore.providers.errors import (
    SurveyEnterpriseUnavailableError,
    SurveyNotOpenError,
    SurveyPausedError,
    SurveyStoppedError,
)
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
from surveycore.wjx.provider.multilevel import MULTILEVEL_DROPDOWN, parse_multilevel_options
from software.providers.surveycore_compat import _normalize_html_text

import software.network.http as http_client
from software.network.http.defaults import DEFAULT_HTTP_HEADERS


async def _load_multilevel_options(questions: List[Dict[str, Any]], html: str, url: str) -> None:
    targets = [q for q in questions if q.get("provider_type") == MULTILEVEL_DROPDOWN]
    if not targets:
        return
    scripts = "\n".join(re.findall(r"<script[^>]*>(.*?)</script>", html, re.IGNORECASE | re.DOTALL))
    activity = re.search(r"\bvar\s+activityId\s*=\s*(?:DecodeId\((\d+)\)|(\d+))", scripts)
    if activity is None:
        raise ValueError("问卷星多级下拉缺少 activityId")
    if activity.group(1):
        decoder = re.search(
            r"function\s+DecodeId\([^)]*\)\s*\{\s*return\s+\w+\s*\^\s*(\d+)",
            scripts,
        )
        if decoder is None:
            raise ValueError("问卷星多级下拉无法解析 activityId")
        activity_id = int(activity.group(1)) ^ int(decoder.group(1))
    else:
        activity_id = int(activity.group(2))
    for question in targets:
        metadata = question.get("provider_page_raw") or {}
        params = {
            "activityid": str(activity_id),
            "ct": "5",
            "pos": str(question["num"]),
        }
        cid = str(metadata.get("cid") or "")
        if cid:
            params["cid"] = cid
        response = await http_client.aget(
            urljoin(url, "/joinnew/setmenuselnew.aspx"),
            params=params,
            headers={**DEFAULT_HTTP_HEADERS, "Referer": url},
            timeout=12,
            proxies={},
        )
        response.raise_for_status()
        options = parse_multilevel_options(response.text, encoded=bool(cid))
        question["option_texts"] = options.pop("option_texts")
        question["options"] = len(question["option_texts"])
        metadata.update(options)
        question["provider_page_raw"] = metadata


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
                await _load_multilevel_options(info, resp.text, url)
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
