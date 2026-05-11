"""问卷星提交后的 URL 与页面状态判定。"""

from __future__ import annotations

from urllib.parse import urljoin, urlparse

from software.network.browser.runtime_async import BrowserDriver


def _resolve_completion_url(submit_url: str, payload: str) -> str:
    """把提交响应中的完成页路径转为可访问 URL。"""
    value = str(payload or "").strip()
    if not value:
        return ""
    if value.startswith("http://") or value.startswith("https://"):
        return value
    if value.startswith("/"):
        return urljoin(submit_url, value)
    return urljoin(submit_url, f"/{value}")


def _normalize_url_for_compare(value: str) -> str:
    """用于比较的 URL 归一化：去掉 fragment，去掉首尾空白。"""
    if value is None:
        return ""
    text = str(value).strip()
    if not text:
        return ""
    try:
        parsed = urlparse(text)
    except Exception:
        return text
    try:
        if parsed.fragment:
            parsed = parsed._replace(fragment="")
        return parsed.geturl()
    except Exception:
        return text


def _is_wjx_domain(url_value: str) -> bool:
    try:
        parsed = urlparse(str(url_value))
    except Exception:
        return False
    host = (parsed.netloc or "").split(":", 1)[0].lower()
    return bool(host == "wjx.cn" or host.endswith(".wjx.cn"))


def _looks_like_wjx_survey_url(url_value: str) -> bool:
    """粗略判断是否像问卷星问卷链接。"""
    if not url_value:
        return False
    text = str(url_value).strip()
    if not text:
        return False
    if not _is_wjx_domain(text):
        return False
    try:
        parsed = urlparse(text)
    except Exception:
        return False
    path = (parsed.path or "").lower()
    if "complete" in path:
        return False
    if not path.endswith(".aspx"):
        return False
    if any(segment in path for segment in ("/vm/", "/jq/", "/vj/")):
        return True
    return True


async def _page_looks_like_wjx_questionnaire(driver: BrowserDriver) -> bool:
    """用 DOM 特征判断当前页是否为可作答的问卷页。"""
    script = r"""
        return (() => {
            const normalize = (text) => (text || '').replace(/\s+/g, '').toLowerCase();
            const bodyText = normalize(document.body?.innerText || '');
            const completeMarkers = ['答卷已经提交', '感谢您的参与', '感谢参与'];
            if (completeMarkers.some(m => bodyText.includes(m))) return false;

            const startLabels = [
                '开始作答', '开始答题', '开始填写',
                'startanswering', 'startsurvey', 'startquestionnaire',
                'beginanswering', 'beginsurvey', 'beginquestionnaire'
            ];
            if (startLabels.some(label => bodyText.includes(label))) {
                const startLike = Array.from(document.querySelectorAll('div, a, button, span, input[type="button"], input[type="submit"], [role="button"]')).some(el => {
                    const t = normalize(el.innerText || el.textContent || el.value || '');
                    return startLabels.includes(t);
                });
                if (startLike) return true;
            }

            const questionLike = document.querySelector(
                '#div1, #divQuestion, [id^="divquestion"], .div_question, .question, .wjx_question, [topic]'
            );

            const actionLike = document.querySelector(
                '#submit_button, #divSubmit, #ctlNext, #divNext, #btnNext, #next, ' +
                '.next, .next-btn, .next-button, .btn-next, button[type="submit"], a.button.mainBgColor'
            );

            return !!(questionLike && actionLike);
        })();
    """
    try:
        return bool(await driver.execute_script(script))
    except Exception:
        return False


async def _is_device_quota_limit_page(driver: BrowserDriver) -> bool:
    """检测“设备已达到最大填写次数”提示页。"""
    script = r"""
        return (() => {
            const text = (document.body?.innerText || '').replace(/\s+/g, '').toLowerCase();
            if (!text) return false;

            const limitMarkers = [
                '设备已达到最大填写次数',
                '已达到最大填写次数',
                '达到最大填写次数',
                '填写次数已达上限',
                '超过最大填写次数',
            ];
            const hasLimit = limitMarkers.some(marker => text.includes(marker));
            if (!hasLimit) return false;

            const hasThanks = text.includes('感谢参与') || text.includes('感谢参与!');
            const hasApology = text.includes('很抱歉') || text.includes('提示');
            if (!(hasThanks || hasApology)) return false;

            const questionLike = document.querySelector(
                '#divQuestion, [id^="divquestion"], .div_question, .question, .wjx_question, [topic]'
            );
            if (questionLike) return false;

            const startHints = [
                '开始作答', '开始答题', '开始填写', '继续作答', '继续填写',
                'startanswering', 'startsurvey', 'startquestionnaire',
                'beginanswering', 'beginsurvey', 'beginquestionnaire',
                'continueanswering', 'continuesurvey', 'resumeanswering', 'resumesurvey'
            ];
            if (startHints.some(hint => text.includes(hint))) return false;

            const submitSelectors = [
                '#submit_button',
                '#divSubmit',
                '#ctlNext',
                '#SM_BTN_1',
                '.submitDiv a',
                '.btn-submit',
                'button[type="submit"]',
                'a.mainBgColor',
            ];
            if (submitSelectors.some(sel => document.querySelector(sel))) return false;

            return true;
        })();
    """
    try:
        return bool(await driver.execute_script(script))
    except Exception:
        return False


async def is_completion_page(driver: BrowserDriver) -> bool:
    try:
        current_url = str(await driver.current_url() or "")
    except Exception:
        current_url = ""
    if "complete" in current_url.lower():
        return True
    if await _page_looks_like_wjx_questionnaire(driver):
        return False
    script = r"""
        return (() => {
            const normalize = (text) => (text || '').replace(/\s+/g, '').toLowerCase();
            const text = normalize(document.body?.innerText || '');
            if (!text) return false;
            const markers = [
                '答卷已经提交',
                '感谢您的参与',
                '问卷提交成功',
                '提交成功',
                '已完成本次问卷',
                '已完成本次答卷',
                '感谢您的宝贵时间',
            ];
            if (!markers.some(marker => text.includes(marker))) return false;
            const actionSelectors = [
                '#submit_button',
                '#divSubmit',
                '#ctlNext',
                '#divNext',
                '#btnNext',
                '#next',
                '#SM_BTN_1',
                '.submitDiv a',
                '.btn-next',
                '.btn-submit',
                'button[type="submit"]',
                'a.button.mainBgColor'
            ];
            const visible = (el) => {
                if (!el) return false;
                const style = window.getComputedStyle(el);
                if (!style) return false;
                if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') return false;
                const rect = el.getBoundingClientRect();
                return rect.width > 0 && rect.height > 0;
            };
            return !actionSelectors.some((selector) => Array.from(document.querySelectorAll(selector)).some(visible));
        })();
    """
    try:
        return bool(await driver.execute_script(script))
    except Exception:
        return False


__all__ = [
    "_is_device_quota_limit_page",
    "_is_wjx_domain",
    "_looks_like_wjx_survey_url",
    "_normalize_url_for_compare",
    "_page_looks_like_wjx_questionnaire",
    "_resolve_completion_url",
    "is_completion_page",
]
