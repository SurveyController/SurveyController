from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections import OrderedDict
from typing import Any, Mapping

from surveycore.tencent.provider.http_runtime import (
    QqSubmitResult as QqSubmitResult,
    _QQ_FILLBLANK_TOKEN_RE as _QQ_FILLBLANK_TOKEN_RE,
    _choice_question_answer as _choice_question_answer,
    _extract_answer_session_state as _extract_answer_session_state,
    _extract_option_blank_id as _extract_option_blank_id,
    _match_existing_submit_question as _match_existing_submit_question,
    _matrix_question_answer as _matrix_question_answer,
    _meaningful_type_code as _meaningful_type_code,
    _merge_submit_question_meta as _merge_submit_question_meta,
    _normalize_match_text as _normalize_match_text,
    _normalize_submit_questions as _normalize_submit_questions,
    _option_answer as _option_answer,
    _option_blank_answer as _option_blank_answer,
    _option_items as _option_items,
    _proxy_arg as _proxy_arg,
    _question_answer as _question_answer,
    _question_signature as _question_signature,
    _question_types_compatible as _question_types_compatible,
    _raise_qq_submit_failed as _raise_qq_submit_failed_legacy,
    _raw_questions_by_id as _raw_questions_by_id,
    _safe_int as _safe_int,
    _score_question_answer as _score_question_answer,
    _submit_response_answer_hash as _submit_response_answer_hash,
    _text_question_answer as _text_question_answer,
    classify_qq_submit_payload as classify_qq_submit_payload,
)

import software.network.http as http_client
from software.core.config.user_agents import DEFAULT_USER_AGENT
from software.core.ai.batch_runtime import (
    assert_no_ai_placeholders_in_actions,
    prefill_ai_answers_for_questions,
)
from software.core.config.codec import UserAgentProfile
from surveycore.core.modes.duration_control import sample_answer_duration_seconds
from surveycore.core.persona.context import record_answer
from surveycore.core.questions.distribution import record_pending_distribution_choice
from software.core.task import ExecutionConfig, ExecutionState
from surveycore.providers.answering import AnswerAction
from surveycore.providers.answering.recording import record_answer_action
from surveycore.providers.http_logic import build_http_logic_plan
from surveycore.providers.http_progress import update_http_submit_step
from software.network.session_policy import SubmitProxyUnavailableError, mark_submit_proxy_success
from software.network.http.defaults import DEFAULT_HTTP_HEADERS
from surveycore.providers.contracts import SurveyQuestionMeta
from surveycore.providers.errors import SubmissionVerificationRequiredError
from software.providers.contracts import ProviderSubmissionRejectedError
from tencent.provider.answering_builders import build_answer_action
from tencent.provider.parser import (
    _build_qq_api_headers,
    _build_qq_survey_page_url,
    _ensure_qq_api_ok,
    _extract_qq_identifiers,
    _request_qq_api,
)


def _raise_qq_submit_failed(payload: Mapping[str, Any]) -> None:
    try:
        _raise_qq_submit_failed_legacy(payload)
    except SubmissionVerificationRequiredError:
        raise
    except RuntimeError as exc:
        raise ProviderSubmissionRejectedError(str(exc)) from exc


_QQ_SUBMIT_TIMEOUT_SECONDS = 30


def _headers(page_url: str, user_agent: str | None = None) -> dict[str, str]:
    headers = _build_qq_api_headers(page_url)
    headers["User-Agent"] = str(user_agent or "").strip() or DEFAULT_USER_AGENT
    return headers


def _record_action(ctx: ExecutionState, action: AnswerAction) -> None:
    record_answer_action(
        ctx,
        action,
        record_answer_fn=record_answer,
        record_pending_distribution_choice_fn=record_pending_distribution_choice,
        default_fill_text="",
    )


async def _fetch_submit_source(
    survey_id: str,
    hash_value: str,
    *,
    headers: dict[str, str],
    proxies: Any,
) -> tuple[str, dict[str, Any], list[Any]]:
    session_payload = await _request_qq_api(
        survey_id, "session", hash_value=hash_value, headers=headers, proxies=proxies
    )
    session_data = _ensure_qq_api_ok(session_payload, "session")
    answer_session_id = str(session_data.get("answer_session_id") or "").strip()
    if answer_session_id:
        headers["X-Answer-Session"] = answer_session_id

    questions_payload = await _request_qq_api(
        survey_id,
        "questions",
        hash_value=hash_value,
        headers=headers,
        extra_params={"locale": "zhs"},
        proxies=proxies,
    )
    questions_data = _ensure_qq_api_ok(questions_payload, "questions")
    raw_questions = questions_data.get("questions")
    if not isinstance(raw_questions, list) or not raw_questions:
        raise RuntimeError("腾讯问卷题目接口未返回可提交题目")
    return answer_session_id, session_data, raw_questions


async def _confirm_qq_submit_persisted(
    survey_id: str,
    hash_value: str,
    *,
    headers: dict[str, str],
    proxies: Any,
    answer_session_id: str,
    initial_session_data: Mapping[str, Any],
    submit_payload: Mapping[str, Any],
) -> None:
    answer_hash = _submit_response_answer_hash(submit_payload)
    if not answer_hash:
        raise RuntimeError("腾讯问卷提交返回缺少 answer_hash，无法确认服务端是否已收录")
    if not answer_session_id:
        return

    initial_submitted_at, initial_answer_id = _extract_answer_session_state(initial_session_data)
    verify_headers = dict(headers)
    verify_headers["X-Answer-Session"] = answer_session_id
    for attempt in range(3):
        session_payload = await _request_qq_api(
            survey_id,
            "session",
            hash_value=hash_value,
            headers=verify_headers,
            proxies=proxies,
        )
        session_data = _ensure_qq_api_ok(session_payload, "session")
        last_submitted_at, last_answer_id = _extract_answer_session_state(session_data)
        if last_submitted_at > initial_submitted_at:
            return
        if last_answer_id > 0 and last_answer_id != initial_answer_id:
            return
        if attempt < 2:
            await asyncio.sleep(0.2)
    raise RuntimeError("腾讯问卷提交后未确认到服务端已记录答案")


async def brush_qq_http(
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
    _ = user_agent_profile
    if stop_signal is not None and stop_signal.is_set():
        return False
    try:
        survey_id, hash_value = _extract_qq_identifiers(config.url)
        page_url = _build_qq_survey_page_url(survey_id, hash_value)
        headers = _headers(page_url, user_agent)
        answer_session_id, session_data, raw_questions = await _fetch_submit_source(
            survey_id,
            hash_value,
            headers=headers,
            proxies={},
        )

        raw_by_id = _raw_questions_by_id(raw_questions)
        questions = _normalize_submit_questions(config, raw_questions)

        await update_http_submit_step(ctx, thread_name, "生成答案")
        for question in questions:
            if stop_signal is not None and stop_signal.is_set():
                return False
            if bool(getattr(question, "unsupported", False)):
                raise RuntimeError(
                    f"腾讯问卷第{question.num}题暂不支持：{question.unsupported_reason or question.type_code}"
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
        assert_no_ai_placeholders_in_actions(actions, provider_label="腾讯问卷")
        action_by_question_id = {
            str(action.question_id or "").strip(): action
            for action in actions
            if str(action.question_id or "").strip()
        }
        if not action_by_question_id:
            raise RuntimeError("腾讯问卷没有生成可提交答案")

        page_questions: OrderedDict[str, list[dict[str, Any]]] = OrderedDict()
        for raw_question in raw_questions:
            if stop_signal is not None and stop_signal.is_set():
                return False
            question_id = (
                str(raw_question.get("id") or "").strip()
                if isinstance(raw_question, Mapping)
                else ""
            )
            if not question_id:
                continue
            action = action_by_question_id.get(question_id)
            if action is None:
                continue
            raw_source = raw_by_id.get(question_id, raw_question)
            page_id = str(
                (raw_source.get("page_id") if isinstance(raw_source, Mapping) else "") or ""
            ).strip()
            if not page_id:
                raise RuntimeError(f"腾讯问卷第{int(action.question_num or 0)}题缺少 page_id")
            question_answer = _question_answer(raw_source, action)
            if isinstance(question_answer, list):
                page_questions.setdefault(page_id, []).extend(question_answer)
            else:
                page_questions.setdefault(page_id, []).append(question_answer)

        if not page_questions:
            raise RuntimeError("腾讯问卷没有生成可提交答案")

        for action in actions:
            _record_action(ctx, action)

        try:
            duration = int(
                sample_answer_duration_seconds(
                    config.answer_duration_range_seconds,
                    survey_provider="qq",
                    default_unconfigured_seconds=90,
                )
                or 90
            )
        except Exception:
            duration = 90
        duration = max(1, duration)
        user_agent_value = str(user_agent or "").strip() or DEFAULT_USER_AGENT
        submit_body = {
            "survey_id": int(survey_id),
            "hash": hash_value,
            "answer_survey": {
                "duration": duration,
                "ua": user_agent_value,
                "referrer": "",
                "uid": str(uuid.uuid4()),
                "sid": str(uuid.uuid4()),
                "openid": "",
                "latitude": None,
                "longitude": None,
                "is_update": False,
                "locale": "zhs",
                "pages": [
                    {
                        "id": page_id,
                        "questions": questions_on_page,
                    }
                    for page_id, questions_on_page in page_questions.items()
                ],
            },
        }
        if not bool(getattr(config, "submit_enabled", True)):
            logging.info("腾讯问卷 HTTP 单测已生成答案，未提交。")
            return True

        submit_headers = {
            **DEFAULT_HTTP_HEADERS,
            "User-Agent": user_agent_value,
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json;charset=UTF-8",
            "Origin": "https://wj.qq.com",
            "Referer": page_url,
        }
        if answer_session_id:
            submit_headers["X-Answer-Session"] = answer_session_id
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
        response = await http_client.apost(
            f"https://wj.qq.com/api/v2/respondent/surveys/{survey_id}/answers",
            params={
                "pv_uid": str(uuid.uuid4()),
                "hash": hash_value,
                "_": str(int(time.time() * 1000)),
            },
            json=submit_body,
            headers=submit_headers,
            timeout=_QQ_SUBMIT_TIMEOUT_SECONDS,
            proxies=submit_proxies,
        )
        response.raise_for_status()
        await update_http_submit_step(ctx, thread_name, "校验结果")
        payload = response.json()
        if not isinstance(payload, dict):
            raise RuntimeError("腾讯问卷提交返回了非 JSON 对象")
        if classify_qq_submit_payload(payload) != QqSubmitResult.SUCCESS:
            _raise_qq_submit_failed(payload)
        await _confirm_qq_submit_persisted(
            survey_id,
            hash_value,
            headers=headers,
            proxies={},
            answer_session_id=answer_session_id,
            initial_session_data=session_data,
            submit_payload=payload,
        )
        mark_submit_proxy_success(ctx, submit_proxy_address)
        return True
    finally:
        ctx.clear_ai_prefill_answers(thread_name)


__all__ = ["QqSubmitResult", "brush_qq_http", "classify_qq_submit_payload"]
