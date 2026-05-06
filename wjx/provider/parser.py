"""问卷星解析实现（provider 层）。"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from software.network.browser import (
    describe_playwright_startup_error,
    is_playwright_startup_environment_error,
)
from software.network.browser.parse_pool import acquire_parse_browser_session
from wjx.provider.html_parser import (
    _normalize_html_text,
    extract_survey_title_from_html,
    parse_survey_questions_from_html,
)
import software.network.http as http_client
from software.app.config import DEFAULT_HTTP_HEADERS

PAUSED_SURVEY_ERROR_MESSAGE = "问卷已暂停，需要前往问卷星后台重新发布"
NOT_OPEN_SURVEY_ERROR_MESSAGE = "该问卷暂未开放，无法解析"
_PAUSED_SURVEY_ID_RE = re.compile(r"此问卷[（(]\d+[）)]已暂停")
_NOT_OPEN_TIME_RE = re.compile(
    r"此问卷将于\s*(\d{4}[-/]\d{1,2}[-/]\d{1,2}\s+\d{1,2}:\d{2})\s*开放"
)


class SurveyPausedError(RuntimeError):
    """问卷已暂停时抛出的业务异常。"""


class SurveyNotOpenError(RuntimeError):
    """问卷尚未开放时抛出的业务异常。"""


def _walk_exception_chain(exc: BaseException):
    seen: set[int] = set()
    current: Optional[BaseException] = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        yield current
        current = getattr(current, "__cause__", None) or getattr(current, "__context__", None)


def _exception_has_winerror_10013(exc: BaseException) -> bool:
    for current in _walk_exception_chain(exc):
        if getattr(current, "winerror", None) == 10013:
            return True
    return False


def _build_parser_failure_message(http_exc: Optional[BaseException], browser_exc: Optional[BaseException]) -> str:
    if http_exc is not None and _exception_has_winerror_10013(http_exc):
        if browser_exc is not None and is_playwright_startup_environment_error(browser_exc):
            return (
                "本机环境拦截了网络/本地套接字访问（WinError 10013），"
                "程序既拿不到问卷网页，也拉不起 Playwright 浏览器。"
                "请先检查防火墙、安全软件、系统代理或公司管控策略。"
            )
        return (
            "本机环境拦截了网络套接字访问（WinError 10013），"
            "程序还没拿到问卷网页就被系统、防火墙或安全软件卡死了。"
        )
    if browser_exc is not None and is_playwright_startup_environment_error(browser_exc):
        return describe_playwright_startup_error(browser_exc)
    if http_exc is not None:
        text = str(http_exc).strip()
        if text:
            return f"无法获取问卷网页：{text}"
    if browser_exc is not None:
        text = str(browser_exc).strip()
        if text:
            return f"无法启动解析浏览器：{text}"
    return "无法打开问卷链接，请确认链接有效且网络正常"


def is_paused_survey_page(html: str) -> bool:
    """检测页面是否为“问卷已暂停，不能填写”提示页。"""
    text = _normalize_html_text(html)
    if not text or "已暂停" not in text:
        return False
    if "不能填写" in text or "问卷已暂停" in text:
        return True
    return bool(_PAUSED_SURVEY_ID_RE.search(text))


def build_not_open_survey_message(html: str) -> Optional[str]:
    """构造"问卷暂未开放"提示文案。"""
    text = _normalize_html_text(html)
    if not text:
        return None
    
    # 首先检查是否存在问卷题目容器，如果存在则说明问卷已开放
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")
        # 检查是否有题目容器
        question_container = soup.find("div", id="divQuestion")
        if question_container:
            # 检查是否有实际的题目（fieldset 或 topic 属性的 div）
            has_questions = (
                question_container.find_all("fieldset") or
                question_container.find_all("div", attrs={"topic": True})
            )
            if has_questions:
                # 有题目说明问卷已开放，不应该判定为未开放
                return None
    except Exception:
        # 如果 BeautifulSoup 解析失败，继续使用文本检测
        pass
    
    normalized = "".join(text.split())
    
    # 保留所有关键词，但通过DOM检查优先避免误判
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

    match = _NOT_OPEN_TIME_RE.search(text)
    if match:
        open_time = str(match.group(1) or "").replace("/", "-").strip()
        if open_time:
            return f"{NOT_OPEN_SURVEY_ERROR_MESSAGE}，开放时间：{open_time}"
    return NOT_OPEN_SURVEY_ERROR_MESSAGE


def _load_rendered_wjx_parse_result(url: str) -> Tuple[Optional[List[Dict[str, Any]]], str]:
    with acquire_parse_browser_session() as driver:
        driver.get(url, timeout=20000, wait_until="domcontentloaded")
        page = getattr(driver, "page", None)
        if page is not None:
            try:
                page.wait_for_selector("#divQuestion, div[topic], fieldset", state="attached", timeout=6000)
            except Exception:
                try:
                    page.wait_for_load_state("networkidle", timeout=2000)
                except Exception:
                    pass
            try:
                page.wait_for_load_state("networkidle", timeout=2000)
            except Exception:
                pass
        page_source = driver.page_source
        if is_paused_survey_page(page_source):
            raise SurveyPausedError(PAUSED_SURVEY_ERROR_MESSAGE)
        not_open_message = build_not_open_survey_message(page_source)
        if not_open_message:
            raise SurveyNotOpenError(not_open_message)
        return parse_survey_questions_from_html(page_source), extract_survey_title_from_html(page_source) or ""


def parse_wjx_survey(url: str) -> Tuple[List[Dict[str, Any]], str]:
    info: Optional[List[Dict[str, Any]]] = None
    title = ""
    http_exc: Optional[BaseException] = None
    browser_exc: Optional[BaseException] = None

    try:
        resp = http_client.get(url, timeout=12, headers=DEFAULT_HTTP_HEADERS, proxies={})
        resp.raise_for_status()
        html = resp.text
        if is_paused_survey_page(html):
            raise SurveyPausedError(PAUSED_SURVEY_ERROR_MESSAGE)
        not_open_message = build_not_open_survey_message(html)
        if not_open_message:
            raise SurveyNotOpenError(not_open_message)
        info = parse_survey_questions_from_html(html)
        title = extract_survey_title_from_html(html) or title
    except SurveyPausedError:
        raise
    except SurveyNotOpenError:
        raise
    except Exception as exc:
        http_exc = exc
        logging.exception("使用 httpx 获取问卷失败，url=%r", url)
        info = None

    if info is None:
        try:
            info, rendered_title = _load_rendered_wjx_parse_result(url)
            title = rendered_title or title
        except SurveyPausedError:
            raise
        except SurveyNotOpenError:
            raise
        except Exception as exc:
            browser_exc = exc
            logging.exception("使用 Playwright 获取问卷失败，url=%r", url)
            info = None

    if not info:
        raise RuntimeError(_build_parser_failure_message(http_exc, browser_exc))

    normalized_title = _normalize_html_text(title) if title else ""
    return info, normalized_title


__all__ = [
    "PAUSED_SURVEY_ERROR_MESSAGE",
    "NOT_OPEN_SURVEY_ERROR_MESSAGE",
    "SurveyPausedError",
    "SurveyNotOpenError",
    "build_not_open_survey_message",
    "is_paused_survey_page",
    "parse_wjx_survey",
]


