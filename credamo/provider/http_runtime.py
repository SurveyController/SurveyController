from __future__ import annotations

import json
import logging
import time
from typing import Any, Mapping

from surveycore.credamo.provider.http_runtime import (
    CredamoSubmitResult as CredamoSubmitResult,
    _CIPHER as _CIPHER,
    _CredamoAnswerInit as _CredamoAnswerInit,
    _DEFAULT_ORIGIN as _DEFAULT_ORIGIN,
    _RANDOM_CHARS as _RANDOM_CHARS,
    _RESOLUTION as _RESOLUTION,
    _answer_page_url as _answer_page_url,
    _answer_payload_items as _answer_payload_items,
    _as_mapping_list as _as_mapping_list,
    _build_signature_headers as _build_signature_headers,
    _build_submit_body as _build_submit_body,
    _choice_answer as _choice_answer,
    _choice_index_by_text as _choice_index_by_text,
    _choice_payload as _choice_payload,
    _config_entry_for_question as _config_entry_for_question,
    _enrich_question_meta as _enrich_question_meta,
    _ensure_api_ok as _ensure_api_ok,
    _forced_index_from_config as _forced_index_from_config,
    _id_from_mapping as _id_from_mapping,
    _iter_raw_questions as _iter_raw_questions,
    _matrix_answer as _matrix_answer,
    _new_time_code as _new_time_code,
    _noauth_short_url as _noauth_short_url,
    _normalize_id as _normalize_id,
    _normalized_choice_text as _normalized_choice_text,
    _order_answer as _order_answer,
    _origin_from_url as _origin_from_url,
    _question_answer as _question_answer,
    _question_items as _question_items,
    _random_token as _random_token,
    _raw_option_count as _raw_option_count,
    _raw_provider_type as _raw_provider_type,
    _raw_question_num as _raw_question_num,
    _raw_question_type as _raw_question_type,
    _raw_questions_by_num as _raw_questions_by_num,
    _raw_row_count as _raw_row_count,
    _raw_selector as _raw_selector,
    _resolve_httpx_proxy as _resolve_httpx_proxy,
    _sample_answer_start_time_ms as _sample_answer_start_time_ms,
    _sample_duration_seconds as _sample_duration_seconds,
    _scale_answer as _scale_answer,
    _selected_choice_index as _selected_choice_index,
    _selected_item as _selected_item,
    _sha1_upper as _sha1_upper,
    _short_url_from_url as _short_url_from_url,
    _sort_value as _sort_value,
    _text_answer as _text_answer,
    classify_credamo_api_payload as classify_credamo_api_payload,
)

import httpx
from software.app.config import DEFAULT_HTTP_HEADERS, DEFAULT_USER_AGENT
from software.core.config.codec import UserAgentProfile
from surveycore.core.persona.context import record_answer
from surveycore.core.questions.distribution import record_pending_distribution_choice
from software.core.task import ExecutionConfig, ExecutionState
from surveycore.providers.answering import AnswerAction
from surveycore.providers.answering.recording import record_answer_action
from surveycore.providers.contracts import SurveyQuestionMeta
from surveycore.providers.http_logic import build_http_logic_plan
from surveycore.providers.http_progress import update_http_submit_step
from software.network.session_policy import SubmitProxyUnavailableError, mark_submit_proxy_success, release_submit_proxy

from surveycore.credamo.provider.answering_builders import build_answer_action

_CREDAMO_REQUEST_TIMEOUT_SECONDS = 30


class _CredamoHttpSession:
    def __init__(self, proxy_address: str | None = None) -> None:
        self.proxy_address = str(proxy_address or "").strip()
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> "_CredamoHttpSession":
        self._client = httpx.AsyncClient(
            proxy=_resolve_httpx_proxy(self.proxy_address),
            follow_redirects=True,
            trust_env=not bool(self.proxy_address),
            timeout=None,
        )
        return self

    async def __aexit__(self, *_exc: Any) -> None:
        if self._client is not None:
            await self._client.aclose()
        self._client = None

    def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None:
            raise RuntimeError("见数 HTTP 会话尚未启动")
        return self._client

    async def get(self, url: str, **kwargs: Any) -> httpx.Response:
        return await self._ensure_client().get(url, **kwargs)

    async def post(self, url: str, **kwargs: Any) -> httpx.Response:
        return await self._ensure_client().post(url, **kwargs)


def _request_headers(
    *,
    origin: str,
    short_url: str,
    user_agent: str | None = None,
    answer_token: str = "",
    json_body: bool = False,
) -> dict[str, str]:
    headers = {
        **DEFAULT_HTTP_HEADERS,
        "User-Agent": str(user_agent or "").strip() or DEFAULT_USER_AGENT,
        "Accept": "application/json, text/plain, */*",
        "Referer": _answer_page_url(origin, short_url),
        **_build_signature_headers(answer_token=answer_token),
    }
    if json_body:
        headers["Origin"] = origin.rstrip("/")
        headers["Content-Type"] = "application/json"
    return headers


def _json_payload(response: Any, label: str) -> Mapping[str, Any]:
    try:
        payload = response.json()
    except Exception:
        response.raise_for_status()
        raise RuntimeError(f"见数{label}接口返回了非 JSON 内容")
    if getattr(response, "is_error", False):
        message = ""
        if isinstance(payload, Mapping):
            message = str(payload.get("message") or payload.get("msg") or payload.get("code") or "").strip()
        if message:
            raise RuntimeError(f"见数{label}失败：{message}")
        response.raise_for_status()
    if not isinstance(payload, Mapping):
        raise RuntimeError(f"见数{label}接口返回了非 JSON 对象")
    return payload


async def _fetch_detail(
    session: _CredamoHttpSession,
    *,
    origin: str,
    short_url: str,
    headers: dict[str, str],
) -> Mapping[str, Any]:
    response = await session.get(
        f"{origin.rstrip('/')}/v1/survey/noauth/detail/get/{short_url}",
        headers=headers,
        timeout=_CREDAMO_REQUEST_TIMEOUT_SECONDS,
    )
    return _ensure_api_ok(_json_payload(response, "详情"), "详情")


async def _init_answer(
    session: _CredamoHttpSession,
    *,
    origin: str,
    short_url: str,
    time_code: str,
    headers: dict[str, str],
) -> _CredamoAnswerInit:
    response = await session.get(
        f"{origin.rstrip('/')}/v1/survey/answer/noauth/init/{short_url}",
        params={
            "timeCode": time_code,
            "accountCode": "CDM",
            "resolution": _RESOLUTION,
        },
        headers=headers,
        timeout=_CREDAMO_REQUEST_TIMEOUT_SECONDS,
    )
    data = _ensure_api_ok(_json_payload(response, "初始化"), "初始化")
    answer_token = str(data.get("answerToken") or "").strip()
    if not answer_token:
        raise RuntimeError("见数初始化接口未返回 answerToken")
    try:
        timestamp_ms = int(data.get("timestamp") or int(time.time() * 1000))
    except Exception:
        timestamp_ms = int(time.time() * 1000)
    return _CredamoAnswerInit(
        answer_token=answer_token,
        timestamp_ms=timestamp_ms,
        time_code=time_code,
    )


async def _build_actions(
    config: ExecutionConfig,
    ctx: ExecutionState,
    *,
    raw_by_num: Mapping[int, Mapping[str, Any]],
    psycho_plan: Any,
    stop_signal: Any,
) -> list[AnswerAction]:
    questions = _question_items(config, raw_by_num)
    for question in questions:
        if stop_signal is not None and stop_signal.is_set():
            return []
        if bool(getattr(question, "unsupported", False)):
            raise RuntimeError(f"见数第{question.num}题暂不支持：{question.unsupported_reason or question.type_code}")

    async def _build_action(question: SurveyQuestionMeta) -> AnswerAction | None:
        if stop_signal is not None and stop_signal.is_set():
            return None
        entry = _config_entry_for_question(config, question)
        if entry is None:
            return None
        entry_type, config_index = entry
        return build_answer_action(
            root_index=int(getattr(question, "num", 0) or 0) - 1,
            question_num=int(getattr(question, "num", 0) or 0),
            entry_type=str(entry_type or ""),
            config_index=int(config_index or 0),
            config=config,
            question_meta=question,
            psycho_plan=psycho_plan,
        )

    plan = await build_http_logic_plan(
        questions,
        build_action=_build_action,
    )
    return list(plan.actions)


def _record_action(ctx: ExecutionState, action: AnswerAction) -> None:
    record_answer_action(
        ctx,
        action,
        record_answer_fn=record_answer,
        record_pending_distribution_choice_fn=record_pending_distribution_choice,
        default_fill_text="",
    )


async def _save_answers(
    session: _CredamoHttpSession,
    *,
    origin: str,
    short_url: str,
    init_data: _CredamoAnswerInit,
    body: dict[str, Any],
    user_agent: str | None,
) -> Mapping[str, Any]:
    answer_token = init_data.answer_token
    content = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    response = await session.post(
        (
            f"{origin.rstrip('/')}/v1/survey/answer/noauth/save"
            f"?timeCode={init_data.time_code}&answerToken={answer_token}"
        ),
        content=content,
        headers=_request_headers(
            origin=origin,
            short_url=short_url,
            user_agent=user_agent,
            answer_token=answer_token,
            json_body=True,
        ),
        timeout=_CREDAMO_REQUEST_TIMEOUT_SECONDS,
    )
    payload = _json_payload(response, "提交")
    return _ensure_api_ok(payload, "提交")


async def brush_credamo_http(
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

    origin = _origin_from_url(config.url)
    short_url = _noauth_short_url(_short_url_from_url(config.url))
    user_agent_value = str(user_agent or "").strip() or DEFAULT_USER_AGENT
    base_headers = _request_headers(
        origin=origin,
        short_url=short_url,
        user_agent=user_agent_value,
    )
    async with _CredamoHttpSession() as read_session:
        detail_data = await _fetch_detail(
            read_session,
            origin=origin,
            short_url=short_url,
            headers=base_headers,
        )
        raw_questions = _iter_raw_questions(detail_data)
        if not raw_questions:
            raise RuntimeError("见数详情接口未返回可提交题目")
        raw_by_num = _raw_questions_by_num(raw_questions)

        await update_http_submit_step(ctx, thread_name, "生成答案")
        actions = await _build_actions(
            config,
            ctx,
            raw_by_num=raw_by_num,
            psycho_plan=psycho_plan,
            stop_signal=stop_signal,
        )
        if not actions:
            return False
        for action in actions:
            _record_action(ctx, action)

        duration_seconds = _sample_duration_seconds(config)
        if not bool(getattr(config, "submit_enabled", True)):
            logging.info("见数 HTTP 单测已生成答案，未提交。")
            return True

    if stop_signal is not None and stop_signal.is_set():
        return False
    await update_http_submit_step(ctx, thread_name, "提交问卷")
    time_code = _new_time_code()
    submit_headers = _request_headers(origin=origin, short_url=short_url, user_agent=user_agent_value)
    async with _CredamoHttpSession() as init_session:
        init_data = await _init_answer(
            init_session,
            origin=origin,
            short_url=short_url,
            time_code=time_code,
            headers=submit_headers,
        )
    if stop_signal is not None and stop_signal.is_set():
        return False
    body = _build_submit_body(
        short_url=short_url,
        raw_by_num=raw_by_num,
        actions=actions,
        config=config,
        answer_started_at_ms=_sample_answer_start_time_ms(
            config,
            init_started_at_ms=init_data.timestamp_ms,
            duration_seconds=duration_seconds,
        ),
        duration_seconds=duration_seconds,
    )
    submit_proxy_address = str(proxy_address or "").strip() or None
    submit_proxy_lease = None
    if submit_proxy_lease_factory is not None:
        submit_proxy_lease = await submit_proxy_lease_factory()
        submit_proxy_address = str(getattr(submit_proxy_lease, "address", "") or "").strip() or None
    if bool(getattr(config, "random_proxy_ip_enabled", False)) and not submit_proxy_address:
        raise SubmitProxyUnavailableError("提交前未获取到随机 IP")
    try:
        async with _CredamoHttpSession(submit_proxy_address) as submit_session:
            await _save_answers(
                submit_session,
                origin=origin,
                short_url=short_url,
                init_data=init_data,
                body=body,
                user_agent=user_agent_value,
            )
        if submit_proxy_address and thread_name:
            release_submit_proxy(ctx, thread_name, submit_proxy_address)
    except Exception:
        if submit_proxy_address and thread_name:
            release_submit_proxy(ctx, thread_name, submit_proxy_address)
        raise
    mark_submit_proxy_success(ctx, submit_proxy_address)
    await update_http_submit_step(ctx, thread_name, "校验结果")
    return True


__all__ = ["CredamoSubmitResult", "brush_credamo_http", "classify_credamo_api_payload"]
