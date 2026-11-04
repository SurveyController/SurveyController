from __future__ import annotations

import logging
import random
import time
import uuid
from typing import Any

from surveycore.wjx.provider.http_runtime import (
    WJX_PROXY_SUBMISSION_VERIFICATION_MESSAGE as WJX_PROXY_SUBMISSION_VERIFICATION_MESSAGE,
    WJX_SUBMISSION_VERIFICATION_MESSAGE as WJX_SUBMISSION_VERIFICATION_MESSAGE,
    WjxChannelProfile as WjxChannelProfile,
    WjxSubmitResult as WjxSubmitResult,
    _WJX_DEFAULT_SCENE_ID as _WJX_DEFAULT_SCENE_ID,
    _WJX_SPECIAL_CHAR_REPLACEMENTS as _WJX_SPECIAL_CHAR_REPLACEMENTS,
    _WJX_SUBMISSION_VERIFICATION_MARKERS as _WJX_SUBMISSION_VERIFICATION_MARKERS,
    _WJX_SUBMISSION_VERIFICATION_TEXT as _WJX_SUBMISSION_VERIFICATION_TEXT,
    _build_jqsign as _build_jqsign,
    _escape_wjx_submit_text as _escape_wjx_submit_text,
    _extract_wjx_scene_id as _extract_wjx_scene_id,
    _format_selected_indices as _format_selected_indices,
    _format_wjx_starttime as _format_wjx_starttime,
    _is_wechat_user_agent as _is_wechat_user_agent,
    _proxy_arg as _proxy_arg,
    _question_error_label as _question_error_label,
    _question_items as _question_items,
    _raise_submit_rejected as _raise_submit_rejected_legacy,
    _resolve_wjx_channel_profile as _resolve_wjx_channel_profile,
    _resolve_wjx_submit_start_seconds as _resolve_wjx_submit_start_seconds,
    _resolve_wjx_submit_timing as _resolve_wjx_submit_timing,
    _sample_ktimes as _sample_ktimes,
    _shortid_from_url as _shortid_from_url,
    _skipped_submitdata_answer as _skipped_submitdata_answer,
    _submit_domain as _submit_domain,
    _submitdata_answer as _submitdata_answer,
    _submitdata_from_actions as _submitdata_from_actions,
    classify_wjx_submit_response as classify_wjx_submit_response,
    is_wjx_submission_verification_response as is_wjx_submission_verification_response,
)

import software.network.http as http_client
from software.core.config.user_agents import DEFAULT_USER_AGENT, USER_AGENT_PRESETS
from software.core.ai.batch_runtime import (
    assert_no_ai_placeholders_in_actions,
    prefill_ai_answers_for_questions,
)
from software.core.config.codec import UserAgentProfile
from surveycore.core.persona.context import record_answer
from surveycore.core.questions.distribution import record_pending_distribution_choice
from software.core.task import ExecutionConfig, ExecutionState
from software.network.proxy.pool import mask_proxy_for_log
from software.network.http.defaults import DEFAULT_HTTP_HEADERS
from software.network.session_policy import SubmitProxyUnavailableError, mark_submit_proxy_success
from surveycore.providers.answering import AnswerAction
from surveycore.providers.answering.recording import record_answer_action
from surveycore.providers.http_logic import HttpLogicPlan, build_http_logic_plan
from surveycore.providers.http_progress import update_http_submit_step
from surveycore.providers.contracts import SurveyQuestionMeta
from surveycore.providers.errors import (
    SubmissionVerificationRequiredError,
    SurveyEnterpriseUnavailableError,
    SurveyNotOpenError,
    SurveyPausedError,
    SurveyProviderUnavailableAtRuntimeError,
    SurveyStoppedError,
)
from software.providers.contracts import ProviderSubmissionRejectedError
from wjx.provider.answering_builders import build_answer_action
from wjx.provider.parser import _parse_wjx_html, _raise_wjx_page_state_errors


def _raise_submit_rejected(
    config: ExecutionConfig,
    response_text: str,
    *,
    proxy_address: str | None = None,
) -> None:
    try:
        _raise_submit_rejected_legacy(config, response_text, proxy_address=proxy_address)
    except SubmissionVerificationRequiredError:
        raise
    except RuntimeError as exc:
        raise ProviderSubmissionRejectedError(str(exc)) from exc


_WJX_PAGE_LOAD_TIMEOUT_SECONDS = 20
_WJX_SUBMIT_TIMEOUT_SECONDS = 30


def _resolve_user_agent(user_agent: str | None) -> str:
    text = str(user_agent or "").strip()
    if text:
        return text
    return str(DEFAULT_USER_AGENT or USER_AGENT_PRESETS.get("pc_web", {}).get("ua") or "").strip()


def _record_action(ctx: ExecutionState, action: AnswerAction) -> None:
    record_answer_action(
        ctx,
        action,
        record_answer_fn=record_answer,
        record_pending_distribution_choice_fn=record_pending_distribution_choice,
        default_fill_text="",
    )


async def _load_wjx_page(url: str, *, headers: dict[str, str], proxies: Any) -> str:
    response = await http_client.aget(
        url, timeout=_WJX_PAGE_LOAD_TIMEOUT_SECONDS, headers=headers, proxies=proxies
    )
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
            raise RuntimeError(
                f"问卷星第{question.num}题暂不支持：{question.unsupported_reason or question.type_code}"
            )

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
    await prefill_ai_answers_for_questions(
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
        assert_no_ai_placeholders_in_actions(actions, provider_label="问卷星")
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
            submit_proxy_address = (
                str(getattr(submit_proxy_lease, "address", "") or "").strip() or None
            )
        if bool(getattr(config, "random_proxy_ip_enabled", False)) and not submit_proxy_address:
            raise SubmitProxyUnavailableError("提交前未获取到随机 IP")
        submit_proxies = _proxy_arg(submit_proxy_address)
        if str(submit_proxy_address or "").strip():
            logging.debug(
                "问卷星 HTTP 提交使用随机IP：%s", mask_proxy_for_log(submit_proxy_address)
            )
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
        await update_http_submit_step(ctx, thread_name, "校验结果")
        response_text = str(response.text or "").strip()
        if classify_wjx_submit_response(response_text) != WjxSubmitResult.SUCCESS:
            _raise_submit_rejected(config, response_text, proxy_address=submit_proxy_address)
        mark_submit_proxy_success(ctx, submit_proxy_address)
        return True
    finally:
        ctx.clear_ai_prefill_answers(thread_name)


__all__ = [
    "WJX_SUBMISSION_VERIFICATION_MESSAGE",
    "WjxSubmitResult",
    "brush_wjx_http",
    "classify_wjx_submit_response",
    "is_wjx_submission_verification_response",
]
