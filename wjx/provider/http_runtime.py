from __future__ import annotations

import logging
import random
import html as html_lib
import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from urllib.parse import urlparse

import software.network.http as http_client
from software.app.config import DEFAULT_HTTP_HEADERS, DEFAULT_USER_AGENT, USER_AGENT_PRESETS
from software.core.ai.batch_runtime import assert_no_free_ai_placeholders_in_actions, prefill_free_ai_answers_for_questions
from software.core.config.codec import UserAgentProfile
from software.core.modes.duration_control import sample_answer_duration_seconds
from software.core.persona.context import record_answer
from software.core.questions.distribution import record_pending_distribution_choice
from software.core.task import ExecutionConfig, ExecutionState
from software.network.proxy.pool import mask_proxy_for_log
from software.network.session_policy import SubmitProxyUnavailableError, mark_submit_proxy_success, release_submit_proxy
from software.providers.answering import AnswerAction
from software.providers.answering.recording import record_answer_action
from software.providers.http_logic import HttpLogicPlan, build_http_logic_plan
from software.providers.http_progress import update_http_submit_step
from software.providers.contracts import SurveyQuestionMeta
from software.providers.errors import (
    SubmissionVerificationRequiredError,
    SurveyEnterpriseUnavailableError,
    SurveyNotOpenError,
    SurveyPausedError,
    SurveyProviderUnavailableAtRuntimeError,
    SurveyStoppedError,
)
from wjx.provider.answering_builders import build_answer_action
from wjx.provider.parser import _parse_wjx_html, _raise_wjx_page_state_errors
from wjx.provider.regexes import WJX_SCENE_ID_PATTERNS


WJX_SUBMISSION_VERIFICATION_MESSAGE = "问卷星触发智能验证，当前链路已停止。请启用随机 IP 后再提交。"
WJX_PROXY_SUBMISSION_VERIFICATION_MESSAGE = "问卷星触发智能验证，当前随机 IP 已被风控，正在更换随机 IP 重试。"
_WJX_SUBMISSION_VERIFICATION_TEXT = "需要安全校验，请重新提交"
_WJX_SUBMISSION_VERIFICATION_MARKERS = (
    _WJX_SUBMISSION_VERIFICATION_TEXT,
    "请输入验证码",
)
_WJX_PAGE_LOAD_TIMEOUT_SECONDS = 20
_WJX_SUBMIT_TIMEOUT_SECONDS = 30


class WjxSubmitResult:
    SUCCESS = "success"
    VERIFICATION = "verification"
    REJECTED = "rejected"


@dataclass(frozen=True)
class WjxChannelProfile:
    category: str
    source: str
    extra_params: dict[str, str]


_WJX_DEFAULT_SCENE_ID = "q0hcfsca"
_WJX_SPECIAL_CHAR_REPLACEMENTS = (
    ("$", "ξ"),
    ("}", "｝"),
    ("^", "ˆ"),
    ("|", "¦"),
    ("!", "！"),
    ("<", "＜"),
)


def _proxy_arg(proxy_address: str | None) -> Any:
    proxy = str(proxy_address or "").strip()
    return proxy if proxy else {}


def _shortid_from_url(url: str) -> str:
    parsed = urlparse(str(url or "").strip())
    path = parsed.path or ""
    last = path.rstrip("/").rsplit("/", 1)[-1]
    shortid = last.replace(".aspx", "").strip()
    if not shortid:
        raise RuntimeError("问卷星链接缺少 shortid")
    return shortid


def _submit_domain(url: str) -> str:
    host = urlparse(str(url or "").strip()).netloc.lower()
    if "ks.wjx.com" in host:
        return "ks.wjx.com"
    return "v.wjx.cn"


def _format_wjx_starttime(timestamp_seconds: int) -> str:
    dt = datetime.fromtimestamp(int(timestamp_seconds))
    return f"{dt.year}/{dt.month}/{dt.day} {dt.hour}:{dt.minute}:{dt.second}"


def _resolve_wjx_submit_start_seconds(*, current_ms: int, ktimes: int) -> int:
    current_seconds = max(1, int(int(current_ms or 0) / 1000))
    duration_seconds = max(1, int(ktimes or 1))
    return max(1, current_seconds - duration_seconds)


def _resolve_wjx_submit_timing(*, page_html: str, current_ms: int, sampled_ktimes: int) -> tuple[int, int]:
    ktimes = max(1, int(sampled_ktimes or 1))
    return _resolve_wjx_submit_start_seconds(
        current_ms=current_ms,
        ktimes=ktimes,
    ), ktimes


def _extract_wjx_scene_id(page_html: str) -> str:
    text = html_lib.unescape(str(page_html or ""))
    if not text:
        return _WJX_DEFAULT_SCENE_ID
    for pattern in WJX_SCENE_ID_PATTERNS:
        match = pattern.search(text)
        if not match:
            continue
        value = str(match.group("value") or "").strip()
        if value:
            return value
    return _WJX_DEFAULT_SCENE_ID


def _resolve_user_agent(user_agent: str | None) -> str:
    text = str(user_agent or "").strip()
    if text:
        return text
    return str(DEFAULT_USER_AGENT or USER_AGENT_PRESETS.get("pc_web", {}).get("ua") or "").strip()


def _is_wechat_user_agent(user_agent: str | None) -> bool:
    return "micromessenger" in str(user_agent or "").strip().lower()


def _resolve_wjx_channel_profile(
    user_agent: str | None,
    user_agent_profile: UserAgentProfile | None = None,
) -> WjxChannelProfile:
    category = str(getattr(user_agent_profile, "category", "") or "").strip().lower()
    if not category:
        category = "wechat" if _is_wechat_user_agent(user_agent) else "pc"
    if category == "wechat":
        return WjxChannelProfile(
            category="wechat",
            source="微信",
            extra_params={
                "wxfs": "100",
                "access_token": "1",
                "openid": str(random.randint(100000000, 999999999)),
                "unionId": str(random.randint(100000000, 999999999)),
                "wxappid": "wx8fe84c5d52db247a",
                "iwx": "1",
            },
        )
    if category == "mobile":
        return WjxChannelProfile(
            category="mobile",
            source="手机访问",
            extra_params={},
        )
    return WjxChannelProfile(
        category="pc",
        source="直链访问",
        extra_params={},
    )


def _build_jqsign(jqnonce: str, ktimes: int) -> str:
    t_value = 1 if int(ktimes or 0) % 10 == 0 else int(ktimes or 0) % 10
    return "".join(chr(ord(ch) ^ t_value) for ch in jqnonce)


def _escape_wjx_submit_text(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    for source, target in _WJX_SPECIAL_CHAR_REPLACEMENTS:
        text = text.replace(source, target)
    return text


def _question_items(config: ExecutionConfig) -> list[SurveyQuestionMeta]:
    return sorted(
        list((config.questions_metadata or {}).values()),
        key=lambda item: (int(getattr(item, "page", 1) or 1), int(getattr(item, "num", 0) or 0)),
    )


def _format_selected_indices(indices: tuple[int, ...], *, option_fill_texts: tuple[tuple[int, str], ...] = ()) -> str:
    fills = {
        int(index): _escape_wjx_submit_text(value)
        for index, value in option_fill_texts
        if _escape_wjx_submit_text(value)
    }
    parts: list[str] = []
    for index in indices:
        value = str(int(index) + 1)
        fill = fills.get(int(index), "")
        if fill:
            value = f"{value}^{fill}"
        parts.append(value)
    return "|".join(parts)


def _submitdata_answer(action: AnswerAction) -> str:
    if action.kind in {"choice", "select"}:
        return _format_selected_indices(
            tuple(int(item) for item in action.selected_indices),
            option_fill_texts=action.option_fill_texts,
        )
    if action.kind == "text":
        separator = "^" if len(action.text_values) > 1 else ""
        return separator.join(_escape_wjx_submit_text(item) for item in action.text_values)
    if action.kind == "matrix":
        return ",".join(
            f"{row_index + 1}!{int(item) + 1}"
            for row_index, item in enumerate(action.matrix_indices)
        )
    if action.kind == "slider":
        return str(action.slider_value if action.slider_value is not None else "")
    if action.kind == "order":
        return ",".join(str(int(item) + 1) for item in action.selected_indices)
    return ""


def _skipped_submitdata_answer(question: SurveyQuestionMeta) -> str:
    type_code = str(getattr(question, "type_code", "") or "").strip()
    option_count = max(1, int(getattr(question, "options", 0) or 0))
    rows = max(1, int(getattr(question, "rows", 1) or 1))
    if type_code in {"3", "4", "5", "7"}:
        return "-3"
    if type_code == "11":
        return ",".join("-3" for _ in range(option_count))
    if type_code == "6":
        return ",".join(f"{row_index + 1}!-3" for row_index in range(rows))
    if type_code in {"1", "2", "8", "9", "33", "34"}:
        return "(跳过)"
    return "-3"


def _submitdata_from_actions(
    actions: list[AnswerAction],
    *,
    questions: list[SurveyQuestionMeta] | None = None,
    skipped_question_nums: tuple[int, ...] = (),
) -> str:
    action_by_num = {int(action.question_num or 0): action for action in actions if int(action.question_num or 0) > 0}
    skipped_nums = {int(item) for item in skipped_question_nums if int(item) > 0}
    question_by_num = {
        int(getattr(question, "num", 0) or 0): question
        for question in list(questions or [])
        if int(getattr(question, "num", 0) or 0) > 0
    }
    ordered_nums = sorted(set(action_by_num) | skipped_nums)
    parts: list[str] = []
    for question_num in ordered_nums:
        action = action_by_num.get(question_num)
        if action is not None:
            answer = _submitdata_answer(action)
        else:
            question = question_by_num.get(question_num)
            answer = _skipped_submitdata_answer(question) if question is not None else "-3"
        if question_num <= 0 or not answer:
            continue
        answer = answer.replace("，", ",")
        parts.append(f"{question_num}${answer}")
    if not parts:
        raise RuntimeError("问卷星没有生成可提交答案")
    return "}".join(parts)


def _record_action(ctx: ExecutionState, action: AnswerAction) -> None:
    record_answer_action(
        ctx,
        action,
        record_answer_fn=record_answer,
        record_pending_distribution_choice_fn=record_pending_distribution_choice,
        default_fill_text="",
    )


def _question_error_label(config: ExecutionConfig, question_num: int) -> str:
    try:
        question = (config.questions_metadata or {}).get(int(question_num))
    except Exception:
        question = None
    if question is None:
        return f"第{int(question_num)}题"
    try:
        display_num = int(getattr(question, "display_num", 0) or 0)
    except Exception:
        display_num = 0
    title = str(getattr(question, "title", "") or "").strip()
    prefix = f"第{display_num if display_num > 0 else int(question_num)}题"
    return f"{prefix}（{title}）" if title else prefix


def is_wjx_submission_verification_response(response_text: str) -> bool:
    text = str(response_text or "").strip()
    if not text:
        return False
    return any(marker in text for marker in _WJX_SUBMISSION_VERIFICATION_MARKERS)


def classify_wjx_submit_response(response_text: str) -> str:
    text = str(response_text or "").strip()
    if is_wjx_submission_verification_response(text):
        return WjxSubmitResult.VERIFICATION
    lowered = text.lower()
    success = (
        "complete.aspx" in lowered
        or "success" in lowered
        or lowered.startswith("10")
        or lowered in {"1", "ok"}
    )
    failure = any(token in text for token in ("抱歉", "不符合", "错误", "重新提交"))
    if success and not failure:
        return WjxSubmitResult.SUCCESS
    return WjxSubmitResult.REJECTED


def _raise_submit_rejected(
    config: ExecutionConfig,
    response_text: str,
    *,
    proxy_address: str | None = None,
) -> None:
    text = str(response_text or "").strip()
    if is_wjx_submission_verification_response(text):
        message = (
            WJX_PROXY_SUBMISSION_VERIFICATION_MESSAGE
            if str(proxy_address or "").strip()
            else WJX_SUBMISSION_VERIFICATION_MESSAGE
        )
        raise SubmissionVerificationRequiredError(message)
    parts = [part.strip() for part in text.split("〒", 2)]
    if len(parts) != 3:
        raise RuntimeError(f"问卷星提交被拒绝：{text[:200]}")
    try:
        question_num = int(parts[1])
    except Exception:
        question_num = 0
    reason = parts[2] or text
    if question_num > 0:
        label = _question_error_label(config, question_num)
        raise RuntimeError(f"问卷星提交被拒绝：{label}，{reason}")
    raise RuntimeError(f"问卷星提交被拒绝：{reason}")


async def _load_wjx_page(url: str, *, headers: dict[str, str], proxies: Any) -> str:
    response = await http_client.aget(url, timeout=_WJX_PAGE_LOAD_TIMEOUT_SECONDS, headers=headers, proxies=proxies)
    response.raise_for_status()
    try:
        _raise_wjx_page_state_errors(response.text)
    except (
        SurveyPausedError,
        SurveyStoppedError,
        SurveyEnterpriseUnavailableError,
        SurveyNotOpenError,
    ) as exc:
        raise SurveyProviderUnavailableAtRuntimeError(str(exc)) from exc
    _parse_wjx_html(response.text)
    return str(response.text or "")


async def _build_actions(
    config: ExecutionConfig,
    ctx: ExecutionState,
    *,
    psycho_plan: Any,
    stop_signal: Any,
    thread_name: str = "",
) -> list[AnswerAction]:
    plan = await _build_action_plan(
        config,
        ctx,
        psycho_plan=psycho_plan,
        stop_signal=stop_signal,
        thread_name=thread_name,
    )
    return list(plan.actions)


async def _build_action_plan(
    config: ExecutionConfig,
    ctx: ExecutionState,
    *,
    psycho_plan: Any,
    stop_signal: Any,
    thread_name: str = "",
) -> HttpLogicPlan:
    questions = _question_items(config)
    for question in questions:
        if stop_signal is not None and stop_signal.is_set():
            return HttpLogicPlan(actions=())
        if bool(getattr(question, "unsupported", False)):
            raise RuntimeError(f"问卷星第{question.num}题暂不支持：{question.unsupported_reason or question.type_code}")

    async def _build_action(question: SurveyQuestionMeta) -> AnswerAction | None:
        if stop_signal is not None and stop_signal.is_set():
            return None
        return await build_answer_action(
            None,
            question,
            ctx,
            psycho_plan=psycho_plan,
            thread_name=thread_name,
            allow_ai_placeholder=True,
        )

    plan = await build_http_logic_plan(
        questions,
        build_action=_build_action,
    )
    actions = list(plan.actions)
    await prefill_free_ai_answers_for_questions(
        questions,
        actions,
        ctx,
        thread_name=thread_name,
    )
    return HttpLogicPlan(
        actions=tuple(actions),
        skipped_question_nums=plan.skipped_question_nums,
        terminated_early=plan.terminated_early,
    )


def _sample_ktimes(config: ExecutionConfig) -> int:
    default_seconds = 90
    try:
        sampled = sample_answer_duration_seconds(
            config.answer_duration_range_seconds,
            survey_provider="wjx",
            default_unconfigured_seconds=default_seconds,
        )
    except Exception:
        sampled = float(default_seconds)
    if sampled and sampled > 0:
        return max(1, int(round(sampled)))
    return default_seconds


async def brush_wjx_http(
    config: ExecutionConfig,
    ctx: ExecutionState,
    *,
    stop_signal: Any = None,
    thread_name: str = "",
    psycho_plan: Any = None,
    proxy_address: str | None = None,
    user_agent: str | None = None,
    user_agent_profile: UserAgentProfile | None = None,
    submit_proxy_lease_factory: Any = None,
) -> bool:
    if stop_signal is not None and stop_signal.is_set():
        return False
    try:
        shortid = _shortid_from_url(config.url)
        user_agent_value = _resolve_user_agent(user_agent)
        headers = {
            **DEFAULT_HTTP_HEADERS,
            "User-Agent": user_agent_value,
            "Referer": config.url,
        }
        page_html = await _load_wjx_page(config.url, headers=headers, proxies={})

        await update_http_submit_step(ctx, thread_name, "生成答案")
        plan = await _build_action_plan(
            config,
            ctx,
            psycho_plan=psycho_plan,
            stop_signal=stop_signal,
            thread_name=thread_name,
        )
        actions = list(plan.actions)
        if not actions:
            return False
        assert_no_free_ai_placeholders_in_actions(actions, provider_label="问卷星")
        for action in actions:
            _record_action(ctx, action)
        submitdata = _submitdata_from_actions(
            actions,
            questions=_question_items(config),
            skipped_question_nums=plan.skipped_question_nums,
        )
        if not bool(getattr(config, "submit_enabled", True)):
            logging.info("问卷星 HTTP 单测已生成答案，未提交。")
            return True

        current_ms = int(time.time() * 1000)
        ktimes = _sample_ktimes(config)
        start_seconds, ktimes = _resolve_wjx_submit_timing(
            page_html=page_html,
            current_ms=current_ms,
            sampled_ktimes=ktimes,
        )
        scene_id = _extract_wjx_scene_id(page_html)
        jqnonce = str(uuid.uuid4())
        domain = _submit_domain(config.url)
        submit_url = f"https://{domain}/joinnew/processjq.ashx"
        channel_profile = _resolve_wjx_channel_profile(user_agent_value, user_agent_profile)
        params = {
            "shortid": shortid,
            "starttime": _format_wjx_starttime(start_seconds),
            "cst": str(start_seconds * 1000),
            "source": channel_profile.source,
            "submittype": "1",
            "ktimes": str(ktimes),
            "rn": str(2000000000 + random.random() * 100000000),
            "jcn": shortid,
            "nw": "1",
            "jwt": "4",
            "jpm": "62",
            "capt": "2",
            "t": str(current_ms),
            "jqnonce": jqnonce,
            "jqsign": _build_jqsign(jqnonce, ktimes),
        }
        params.update(channel_profile.extra_params)
        await update_http_submit_step(ctx, thread_name, "提交问卷")
        submit_proxy_address = str(proxy_address or "").strip() or None
        submit_proxy_lease = None
        if submit_proxy_lease_factory is not None:
            submit_proxy_lease = await submit_proxy_lease_factory()
            submit_proxy_address = str(getattr(submit_proxy_lease, "address", "") or "").strip() or None
        if bool(getattr(config, "random_proxy_ip_enabled", False)) and not submit_proxy_address:
            raise SubmitProxyUnavailableError("提交前未获取到随机 IP")
        submit_proxies = _proxy_arg(submit_proxy_address)
        if str(submit_proxy_address or "").strip():
            logging.debug("问卷星 HTTP 提交使用随机IP：%s", mask_proxy_for_log(submit_proxy_address))
        try:
            response = await http_client.apost(
                submit_url,
                params=params,
                data={"submitdata": submitdata, "sceneId": scene_id},
                headers={
                    **headers,
                    "Accept": "text/plain, */*; q=0.01",
                    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                    "Origin": f"https://{domain}",
                    "X-Requested-With": "XMLHttpRequest",
                },
                timeout=_WJX_SUBMIT_TIMEOUT_SECONDS,
                proxies=submit_proxies,
            )
            response.raise_for_status()
            if submit_proxy_address and thread_name:
                release_submit_proxy(ctx, thread_name, submit_proxy_address)
        except Exception:
            if submit_proxy_address and thread_name:
                release_submit_proxy(ctx, thread_name, submit_proxy_address)
            raise
        await update_http_submit_step(ctx, thread_name, "校验结果")
        response_text = str(response.text or "").strip()
        if classify_wjx_submit_response(response_text) != WjxSubmitResult.SUCCESS:
            _raise_submit_rejected(config, response_text, proxy_address=submit_proxy_address)
        mark_submit_proxy_success(ctx, submit_proxy_address)
        return True
    finally:
        ctx.clear_free_ai_prefill_answers(thread_name)


__all__ = [
    "WJX_SUBMISSION_VERIFICATION_MESSAGE",
    "WjxSubmitResult",
    "brush_wjx_http",
    "classify_wjx_submit_response",
    "is_wjx_submission_verification_response",
]
