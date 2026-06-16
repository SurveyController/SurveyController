from __future__ import annotations

import asyncio
import logging
import re
import time
import uuid
from collections import OrderedDict
from typing import Any, Mapping, Optional

import software.network.http as http_client
from software.app.config import DEFAULT_HTTP_HEADERS, DEFAULT_USER_AGENT
from software.core.ai.batch_runtime import assert_no_free_ai_placeholders_in_actions, prefill_free_ai_answers_for_questions
from software.core.config.codec import UserAgentProfile
from software.core.modes.duration_control import sample_answer_duration_seconds
from software.core.persona.context import record_answer
from software.core.questions.distribution import record_pending_distribution_choice
from software.core.task import ExecutionConfig, ExecutionState
from software.providers.answering import AnswerAction
from software.providers.answering.option_fill import option_fill_text_map
from software.providers.answering.recording import record_answer_action
from software.providers.http_logic import build_http_logic_plan
from software.providers.http_progress import update_http_submit_step
from software.network.session_policy import SubmitProxyUnavailableError, mark_submit_proxy_success, release_submit_proxy
from software.providers.common import SURVEY_PROVIDER_QQ
from software.providers.contracts import SurveyQuestionMeta, ensure_survey_question_metas
from tencent.provider.answering_builders import build_answer_action
from tencent.provider.parser import (
    _build_qq_api_headers,
    _build_qq_survey_page_url,
    _ensure_qq_api_ok,
    _extract_qq_identifiers,
    _request_qq_api,
    _standardize_qq_questions,
)


class QqSubmitResult:
    SUCCESS = "success"
    FAILED = "failed"


_QQ_SUBMIT_TIMEOUT_SECONDS = 30
_QQ_FILLBLANK_TOKEN_RE = re.compile(r"\{(fillblank-[^{}]+)\}", re.IGNORECASE)


def _proxy_arg(proxy_address: str | None) -> Any:
    proxy = str(proxy_address or "").strip()
    return proxy if proxy else {}


def _headers(page_url: str, user_agent: str | None = None) -> dict[str, str]:
    headers = _build_qq_api_headers(page_url)
    headers["User-Agent"] = str(user_agent or "").strip() or DEFAULT_USER_AGENT
    return headers


def _safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except Exception:
        return 0


def _raw_questions_by_id(questions: list[Any]) -> dict[str, Mapping[str, Any]]:
    result: dict[str, Mapping[str, Any]] = {}
    for item in questions:
        if not isinstance(item, Mapping):
            continue
        question_id = str(item.get("id") or "").strip()
        if question_id:
            result[question_id] = item
    return result


def _normalize_match_text(raw: Any) -> str:
    return "".join(str(raw or "").split())


def _meaningful_type_code(question: SurveyQuestionMeta) -> str:
    type_code = str(getattr(question, "type_code", "") or "").strip()
    return "" if type_code in {"", "0"} else type_code


def _question_signature(question: SurveyQuestionMeta) -> tuple[str, str]:
    provider_type = str(getattr(question, "provider_type", "") or "").strip().lower()
    type_marker = provider_type or _meaningful_type_code(question)
    return type_marker, _normalize_match_text(getattr(question, "title", ""))


def _question_types_compatible(current: SurveyQuestionMeta, existing: SurveyQuestionMeta) -> bool:
    current_provider_type = str(getattr(current, "provider_type", "") or "").strip().lower()
    existing_provider_type = str(getattr(existing, "provider_type", "") or "").strip().lower()
    if current_provider_type and existing_provider_type:
        return current_provider_type == existing_provider_type
    current_type = _meaningful_type_code(current)
    existing_type = _meaningful_type_code(existing)
    if current_type and existing_type:
        return current_type == existing_type
    return True


def _merge_submit_question_meta(existing: SurveyQuestionMeta, current: SurveyQuestionMeta) -> SurveyQuestionMeta:
    merged = current.to_dict()
    merged["num"] = int(getattr(existing, "num", 0) or merged.get("num") or 0)
    merged["display_num"] = getattr(existing, "display_num", None)
    if not str(merged.get("title") or "").strip():
        merged["title"] = str(getattr(existing, "title", "") or "").strip()
    if not str(merged.get("description") or "").strip():
        merged["description"] = str(getattr(existing, "description", "") or "").strip()
    merged["has_jump"] = bool(getattr(existing, "has_jump", False))
    merged["jump_rules"] = list(getattr(existing, "jump_rules", []) or [])
    merged["has_display_condition"] = bool(getattr(existing, "has_display_condition", False))
    merged["display_conditions"] = list(getattr(existing, "display_conditions", []) or [])
    merged["has_dependent_display_logic"] = bool(getattr(existing, "has_dependent_display_logic", False))
    merged["controls_display_targets"] = list(getattr(existing, "controls_display_targets", []) or [])
    merged["logic_parse_status"] = str(getattr(existing, "logic_parse_status", "") or merged.get("logic_parse_status") or "")
    merged["question_media"] = list(getattr(existing, "question_media", []) or merged.get("question_media") or [])
    merged["required"] = bool(getattr(existing, "required", merged.get("required", False)))
    return ensure_survey_question_metas([merged], default_provider=SURVEY_PROVIDER_QQ)[0]


def _match_existing_submit_question(
    current: SurveyQuestionMeta,
    existing_by_signature: dict[tuple[str, str], list[SurveyQuestionMeta]],
    ordered_existing: list[SurveyQuestionMeta],
    index: int,
) -> Optional[SurveyQuestionMeta]:
    signature = _question_signature(current)
    if signature[1]:
        candidates = existing_by_signature.get(signature) or []
        if candidates:
            return candidates.pop(0)
    if index < len(ordered_existing):
        candidate = ordered_existing[index]
        if _question_types_compatible(current, candidate):
            return candidate
    return None


def _normalize_submit_questions(config: ExecutionConfig, raw_questions: list[Any]) -> list[SurveyQuestionMeta]:
    normalized_inputs = _standardize_qq_questions(
        [item for item in raw_questions if isinstance(item, Mapping)]
    )
    normalized_questions = ensure_survey_question_metas(
        normalized_inputs,
        default_provider=SURVEY_PROVIDER_QQ,
    )
    current_questions = [item for item in normalized_questions if not bool(getattr(item, "is_description", False))]
    ordered_existing = [
        item
        for _, item in sorted((config.questions_metadata or {}).items(), key=lambda pair: int(pair[0]))
        if not bool(getattr(item, "is_description", False))
    ]
    existing_by_signature: dict[tuple[str, str], list[SurveyQuestionMeta]] = {}
    for item in ordered_existing:
        signature = _question_signature(item)
        if signature[1]:
            existing_by_signature.setdefault(signature, []).append(item)

    merged_questions: list[SurveyQuestionMeta] = []
    for index, current in enumerate(current_questions):
        existing = _match_existing_submit_question(
            current,
            existing_by_signature,
            ordered_existing,
            index,
        )
        merged_questions.append(_merge_submit_question_meta(existing, current) if existing is not None else current)
    return merged_questions


def _option_items(raw_question: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    options = raw_question.get("options")
    if isinstance(options, list):
        return [item for item in options if isinstance(item, Mapping)]

    provider_type = str(raw_question.get("type") or "").strip()
    if provider_type not in {"star", "nps", "matrix_star"}:
        return []
    try:
        count = int(raw_question.get("star_num") or 0)
    except Exception:
        count = 0
    if count <= 0:
        return []
    raw_start = raw_question.get("star_begin_num")
    try:
        start = int(raw_start) if raw_start is not None else (0 if provider_type == "nps" else 1)
    except Exception:
        start = 0 if provider_type == "nps" else 1
    return [{"id": "", "text": str(start + index)} for index in range(count)]


def _extract_option_blank_id(value: Any, *, depth: int = 0) -> str:
    if depth > 4 or value is None:
        return ""
    if isinstance(value, Mapping):
        for key, item in value.items():
            key_text = str(key or "").strip()
            match = _QQ_FILLBLANK_TOKEN_RE.search(key_text)
            if match:
                return str(match.group(1) or "").strip()
            lowered_key = key_text.lower()
            if "fillblank" in lowered_key:
                raw_id = str(item or "").strip()
                return raw_id or "fillblank"
            nested = _extract_option_blank_id(item, depth=depth + 1)
            if nested:
                return nested
        return ""
    if isinstance(value, (list, tuple, set)):
        for item in value:
            nested = _extract_option_blank_id(item, depth=depth + 1)
            if nested:
                return nested
        return ""
    match = _QQ_FILLBLANK_TOKEN_RE.search(str(value or ""))
    return str(match.group(1) or "").strip() if match else ""


def _option_blank_answer(raw_option: Mapping[str, Any], fill_text: str) -> dict[str, str]:
    blank_id = _extract_option_blank_id(raw_option)
    if not blank_id:
        blank_id = str(raw_option.get("id") or "").strip()
    return {
        "id": blank_id,
        "text": str(fill_text or "").strip(),
    }


def _option_answer(raw_option: Mapping[str, Any], *, checked: bool) -> dict[str, Any]:
    return {
        "id": str(raw_option.get("id") or "").strip(),
        "text": str(raw_option.get("text") or "").strip(),
        "checked": 1 if checked else 0,
    }


def _score_question_answer(raw_question: Mapping[str, Any], action: AnswerAction) -> dict[str, Any]:
    provider_type = str(raw_question.get("type") or "").strip()
    option_items = _option_items(raw_question)
    if not option_items:
        raise RuntimeError(f"腾讯问卷第{int(action.question_num or 0)}题没有可提交的评分选项")
    selected_index: int | None = action.scalar_value
    if selected_index is None and action.selected_indices:
        selected_index = int(action.selected_indices[0])
    if selected_index is None:
        normalized_index = -1
    else:
        try:
            normalized_index = int(selected_index)
        except Exception:
            normalized_index = -1
    if normalized_index < 0 or normalized_index >= len(option_items):
        raise RuntimeError(f"腾讯问卷第{int(action.question_num or 0)}题没有生成评分答案")
    selected_option = option_items[normalized_index]
    question_id = str(raw_question.get("id") or action.question_id).strip()
    score_value = str(selected_option.get("text") or "").strip()
    if not score_value:
        score_value = str(selected_option.get("id") or "").strip()
    if not score_value:
        score_value = str(normalized_index)
    answer_id = question_id
    if provider_type in {"star", "nps"} and score_value:
        answer_id = f"{question_id}-{score_value}"
    return {
        "id": answer_id,
        "type": provider_type,
        "answer": score_value,
    }


def _choice_question_answer(raw_question: Mapping[str, Any], action: AnswerAction) -> dict[str, Any]:
    selected = {int(item) for item in action.selected_indices}
    fill_by_index = option_fill_text_map(action.option_fill_texts)
    blanks: list[dict[str, str]] = []
    options = [
        _option_answer(option, checked=index in selected)
        for index, option in enumerate(_option_items(raw_question))
    ]
    raw_options = _option_items(raw_question)
    for index, option in enumerate(raw_options):
        if index not in selected:
            continue
        fill_text = fill_by_index.get(index, "")
        if not fill_text:
            continue
        blanks.append(_option_blank_answer(option, fill_text))
    return {
        "id": str(raw_question.get("id") or action.question_id).strip(),
        "type": str(raw_question.get("type") or "").strip(),
        "blanks": blanks,
        "options": options,
    }


def _text_question_answer(raw_question: Mapping[str, Any], action: AnswerAction) -> dict[str, Any]:
    text_values = [str(item or "").strip() for item in action.text_values if str(item or "").strip()]
    return {
        "id": str(raw_question.get("id") or action.question_id).strip(),
        "type": str(raw_question.get("type") or "text").strip(),
        "text": "\n".join(text_values),
    }


def _matrix_question_answer(raw_question: Mapping[str, Any], action: AnswerAction) -> list[dict[str, Any]]:
    rows = raw_question.get("sub_titles")
    normalized_answers: list[dict[str, Any]] = []
    question_id = str(raw_question.get("id") or action.question_id).strip()
    provider_type = str(raw_question.get("type") or "").strip()
    if isinstance(rows, list):
        option_template = _option_items(raw_question)
        if not option_template:
            raise RuntimeError(f"腾讯问卷第{int(action.question_num or 0)}题没有可提交的矩阵列")
        for row_index, row in enumerate(rows):
            if not isinstance(row, Mapping):
                continue
            selected_index = action.matrix_indices[row_index] if row_index < len(action.matrix_indices) else -1
            try:
                selected_index = int(selected_index)
            except Exception:
                selected_index = -1
            if selected_index < 0 or selected_index >= len(option_template):
                raise RuntimeError(f"腾讯问卷第{int(action.question_num or 0)}题第{row_index + 1}行没有生成矩阵答案")
            selected_option = option_template[selected_index]
            row_id = str(row.get("id") or "").strip()
            if provider_type == "matrix_radio":
                option_id = str(selected_option.get("id") or "").strip()
                if not option_id:
                    raise RuntimeError(f"腾讯问卷第{int(action.question_num or 0)}题第{row_index + 1}行缺少矩阵列 id")
                if row_id:
                    composite_id = f"{question_id}_{row_id}_{option_id}"
                else:
                    composite_id = f"{question_id}_{option_id}"
                answer_value = "on"
            else:
                score_value = str(selected_option.get("text") or "").strip()
                if not score_value:
                    score_value = str(selected_index + 1)
                if row_id:
                    composite_id = f"{question_id}-{row_id}-{score_value}"
                else:
                    composite_id = f"{question_id}-{score_value}"
                answer_value = "on"
            normalized_answers.append(
                {
                    "id": composite_id,
                    "type": provider_type,
                    "answer": answer_value,
                }
            )
    if not normalized_answers:
        raise RuntimeError(f"腾讯问卷第{int(action.question_num or 0)}题没有生成矩阵答案")
    return normalized_answers


def _question_answer(raw_question: Mapping[str, Any], action: AnswerAction) -> dict[str, Any] | list[dict[str, Any]]:
    provider_type = str(raw_question.get("type") or "").strip()
    if action.kind == "text" or provider_type in {"text", "textarea", "number"}:
        return _text_question_answer(raw_question, action)
    if provider_type in {"star", "nps"}:
        return _score_question_answer(raw_question, action)
    if action.kind == "matrix" or provider_type.startswith("matrix_"):
        return _matrix_question_answer(raw_question, action)
    return _choice_question_answer(raw_question, action)


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
    session_payload = await _request_qq_api(survey_id, "session", hash_value=hash_value, headers=headers, proxies=proxies)
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


def _submit_response_answer_hash(payload: Mapping[str, Any]) -> str:
    data = payload.get("data")
    if not isinstance(data, Mapping):
        return ""
    return str(data.get("answer_hash") or "").strip()


def _extract_answer_session_state(session_data: Mapping[str, Any]) -> tuple[int, int]:
    answer_session = session_data.get("answer_session")
    if not isinstance(answer_session, Mapping):
        return 0, 0
    last_submitted_at = _safe_int(answer_session.get("last_submitted_at"))
    last_answer_id = _safe_int(answer_session.get("last_answer_id"))
    return last_submitted_at, last_answer_id


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


def classify_qq_submit_payload(payload: Mapping[str, Any]) -> str:
    code = str(payload.get("code") or "").upper()
    if code in {"OK", "0"}:
        return QqSubmitResult.SUCCESS
    return QqSubmitResult.FAILED


def _raise_qq_submit_failed(payload: Mapping[str, Any]) -> None:
    message = str(payload.get("message") or payload.get("msg") or payload.get("code") or payload).strip()
    raise RuntimeError(f"腾讯问卷提交失败：{message}")


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
                raise RuntimeError(f"腾讯问卷第{question.num}题暂不支持：{question.unsupported_reason or question.type_code}")

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
        assert_no_free_ai_placeholders_in_actions(actions, provider_label="腾讯问卷")
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
            question_id = str(raw_question.get("id") or "").strip() if isinstance(raw_question, Mapping) else ""
            if not question_id:
                continue
            action = action_by_question_id.get(question_id)
            if action is None:
                continue
            raw_source = raw_by_id.get(question_id, raw_question)
            page_id = str((raw_source.get("page_id") if isinstance(raw_source, Mapping) else "") or "").strip()
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
            submit_proxy_address = str(getattr(submit_proxy_lease, "address", "") or "").strip() or None
        if bool(getattr(config, "random_proxy_ip_enabled", False)) and not submit_proxy_address:
            raise SubmitProxyUnavailableError("提交前未获取到随机 IP")
        submit_proxies = _proxy_arg(submit_proxy_address)
        try:
            response = await http_client.apost(
                f"https://wj.qq.com/api/v2/respondent/surveys/{survey_id}/answers",
                params={"pv_uid": str(uuid.uuid4()), "hash": hash_value, "_": str(int(time.time() * 1000))},
                json=submit_body,
                headers=submit_headers,
                timeout=_QQ_SUBMIT_TIMEOUT_SECONDS,
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
        ctx.clear_free_ai_prefill_answers(thread_name)


__all__ = ["QqSubmitResult", "brush_qq_http", "classify_qq_submit_payload"]
