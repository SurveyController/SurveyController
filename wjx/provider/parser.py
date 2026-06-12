from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional, Tuple

import software.network.http as http_client
from software.app.config import DEFAULT_HTTP_HEADERS
from software.providers.match_utils import normalize_match_text
from software.providers.errors import (
    SurveyEnterpriseUnavailableError,
    SurveyNotOpenError,
    SurveyPausedError,
    SurveyStoppedError,
)
from wjx.provider.html_parser import (
    _normalize_html_text,
    extract_survey_title_from_html,
    parse_survey_questions_from_html,
)
from wjx.provider.regexes import WJX_NOT_OPEN_TIME_RE, WJX_PAUSED_SURVEY_RE

PAUSED_SURVEY_ERROR_MESSAGE = "问卷已暂停，需要前往问卷星后台重新发布"
STOPPED_SURVEY_ERROR_MESSAGE = "问卷已停止，无法作答"
ENTERPRISE_UNAVAILABLE_SURVEY_ERROR_MESSAGE = "问卷发布者企业标准版未购买或已到期，暂时不能填写"
NOT_OPEN_SURVEY_ERROR_MESSAGE = "该问卷暂未开放，无法解析"
_PAGE_SUMMARY_MAX_LENGTH = 120
_PARSE_RETRY_ATTEMPTS = 3
_PARSE_RETRY_DELAY_SECONDS = 0.35


def _format_not_open_time(match) -> str:
    try:
        year = int(match.group("year"))
        month = int(match.group("month"))
        day = int(match.group("day"))
        hour = int(match.group("hour"))
        minute = int(match.group("minute"))
        second_text = match.group("second")
        if second_text:
            second = int(second_text)
            return f"{year:04d}-{month:02d}-{day:02d} {hour:02d}:{minute:02d}:{second:02d}"
        return f"{year:04d}-{month:02d}-{day:02d} {hour:02d}:{minute:02d}"
    except Exception:
        return ""


def _build_unparseable_page_summary(html: str) -> str:
    text = _normalize_html_text(html)
    if not text:
        return "空页面"
    if len(text) > _PAGE_SUMMARY_MAX_LENGTH:
        text = f"{text[:_PAGE_SUMMARY_MAX_LENGTH]}..."
    return text

def is_paused_survey_page(html: str) -> bool:
    
    text = normalize_match_text(html)
    if not text or "已暂停" not in text:
        return False
    if "不能填写" in text or "问卷已暂停" in text:
        return True
    return bool(WJX_PAUSED_SURVEY_RE.search(text))


def _html_has_question_content(html: str) -> bool:
    try:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "html.parser")
        question_container = soup.find("div", id="divQuestion")
        if not question_container:
            return False
        return bool(
            question_container.find_all("fieldset")
            or question_container.find_all("div", attrs={"topic": True})
        )
    except Exception:
        return False


def is_stopped_survey_page(html: str) -> bool:
    
    text = normalize_match_text(html)
    if not text or "停止状态" not in text or "无法作答" not in text:
        return False

    try:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "html.parser")
        for selector_id in ("divWorkError", "divTip"):
            error_container = soup.find("div", id=selector_id)
            if error_container is not None:
                error_text = _normalize_html_text(error_container.get_text(" ", strip=True))
                error_text = normalize_match_text(error_text)
                if "停止状态" in error_text and "无法作答" in error_text:
                    return True
    except Exception:
        pass

    if _html_has_question_content(html):
        return False

    normalized = "".join(text.split())
    return "此问卷处于停止状态，无法作答" in normalized


def is_enterprise_unavailable_survey_page(html: str) -> bool:
    
    text = normalize_match_text(html)
    if not text:
        return False
    normalized = "".join(text.split())
    if "企业标准版" not in normalized:
        return False
    if "问卷发布者" not in normalized:
        return False
    if "未购买" not in normalized and "已到期" not in normalized:
        return False
    return "暂时不能被填写" in normalized or "暂时不能填写" in normalized


def build_not_open_survey_message(html: str) -> Optional[str]:
    
    text = normalize_match_text(html)
    if not text:
        return None

    if _html_has_question_content(html):
        return None

    normalized = "".join(text.split())
    
    
    keywords = (
        "此问卷将于",
        "请到时再进入此页面进行填写",
        "距离开始还有",
        "尚未开始",
        "未到开始时间",
        "未开放",
        "开放时间",
    )
    if not any(keyword in normalized for keyword in keywords):
        return None

    match = WJX_NOT_OPEN_TIME_RE.search(text)
    if match:
        open_time = _format_not_open_time(match)
        if open_time:
            return f"{NOT_OPEN_SURVEY_ERROR_MESSAGE}，开放时间：{open_time}"
    return NOT_OPEN_SURVEY_ERROR_MESSAGE


def _raise_wjx_page_state_errors(html: str) -> None:
    if is_paused_survey_page(html):
        raise SurveyPausedError(PAUSED_SURVEY_ERROR_MESSAGE)
    if is_stopped_survey_page(html):
        raise SurveyStoppedError(STOPPED_SURVEY_ERROR_MESSAGE)
    if is_enterprise_unavailable_survey_page(html):
        raise SurveyEnterpriseUnavailableError(ENTERPRISE_UNAVAILABLE_SURVEY_ERROR_MESSAGE)
    not_open_message = build_not_open_survey_message(html)
    if not_open_message:
        raise SurveyNotOpenError(not_open_message)


def _parse_wjx_html(html: str) -> Tuple[List[Dict[str, Any]], str]:
    _raise_wjx_page_state_errors(html)
    return parse_survey_questions_from_html(html), extract_survey_title_from_html(html) or ""


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
