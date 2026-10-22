from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional, Tuple

from surveycore.tencent.provider.parser import (
    QQ_PROVIDER_TYPE_TO_INTERNAL,
    QQ_SUPPORTED_PROVIDER_TYPES,
    _QQ_HTTP_LOCALES,
    _build_qq_parse_result,
    _build_qq_survey_page_url as _build_qq_survey_page_url,
    _ensure_qq_api_ok as _ensure_qq_api_ok,
    _extract_qq_identifiers as _extract_qq_identifiers,
    _is_qq_login_required_error,
    _is_qq_login_required_response,
    _is_qq_login_required_url,
    _raise_if_qq_login_required,
    _raise_qq_login_required,
    _standardize_qq_questions as _standardize_qq_questions,
)

import software.network.http as http_client
from software.network.http.defaults import DEFAULT_HTTP_HEADERS


def _build_qq_api_headers(page_url: str) -> Dict[str, str]:
    return {
        **DEFAULT_HTTP_HEADERS,
        "Accept": "application/json, text/plain, */*",
        "Origin": "https://wj.qq.com",
        "Referer": page_url,
    }


async def _request_qq_api(
    survey_id: str,
    endpoint: str,
    *,
    hash_value: str,
    headers: Dict[str, str],
    extra_params: Optional[Dict[str, Any]] = None,
    proxies: Any = None,
) -> Dict[str, Any]:
    url = f"https://wj.qq.com/api/v2/respondent/surveys/{survey_id}/{endpoint}"
    params: Dict[str, Any] = {
        "_": str(int(time.time() * 1000)),
        "hash": hash_value,
    }
    if extra_params:
        params.update(extra_params)
    response = await http_client.aget(
        url,
        params=params,
        headers=headers,
        timeout=15,
        proxies={} if proxies is None else proxies,
    )
    if _is_qq_login_required_response(response):
        _raise_qq_login_required()
    response.raise_for_status()
    try:
        payload = response.json()
    except Exception as exc:
        if _is_qq_login_required_response(response):
            _raise_qq_login_required()
        raise RuntimeError(f"腾讯问卷接口返回了无法解析的响应：{endpoint}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"腾讯问卷接口返回了非对象响应：{endpoint}")
    if _is_qq_login_required_error(payload):
        _raise_qq_login_required()
    return payload


async def _fetch_qq_locale_payload(
    survey_id: str,
    hash_value: str,
    headers: Dict[str, str],
    locale: str,
) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    meta_payload = await _request_qq_api(
        survey_id,
        "meta",
        hash_value=hash_value,
        headers=headers,
        extra_params={"locale": locale},
    )
    meta_data = _ensure_qq_api_ok(meta_payload, f"meta?locale={locale}")

    questions_payload = await _request_qq_api(
        survey_id,
        "questions",
        hash_value=hash_value,
        headers=headers,
        extra_params={"locale": locale},
    )
    questions_data = _ensure_qq_api_ok(questions_payload, f"questions?locale={locale}")
    questions = questions_data.get("questions")
    if not isinstance(questions, list) or not questions:
        raise RuntimeError(f"腾讯问卷题目接口未返回可解析的题目数据（locale={locale}）")
    return meta_data, questions


async def _fetch_qq_survey_via_http(survey_id: str, hash_value: str) -> Tuple[List[Dict[str, Any]], str]:
    page_url = _build_qq_survey_page_url(survey_id, hash_value)
    headers = _build_qq_api_headers(page_url)

    session_payload = await _request_qq_api(
        survey_id,
        "session",
        hash_value=hash_value,
        headers=headers,
    )
    _ensure_qq_api_ok(session_payload, "session")

    last_error: Optional[Exception] = None
    for locale in _QQ_HTTP_LOCALES:
        try:
            meta_data, questions = await _fetch_qq_locale_payload(survey_id, hash_value, headers, locale)
            return _build_qq_parse_result(
                questions,
                raw_title=meta_data.get("title") or "",
                empty_error_message=f"腾讯问卷解析结果为空（locale={locale}）",
            )
        except Exception as exc:
            _raise_if_qq_login_required(exc)
            last_error = exc

    if last_error is not None:
        raise RuntimeError(f"腾讯问卷 HTTP 解析失败：{last_error}") from last_error
    raise RuntimeError("腾讯问卷 HTTP 解析失败：未获得可用 locale")


async def parse_qq_survey(url: str) -> Tuple[List[Dict[str, Any]], str]:
    if _is_qq_login_required_url(url):
        _raise_qq_login_required()
    survey_id, hash_value = _extract_qq_identifiers(url)

    try:
        return await _fetch_qq_survey_via_http(survey_id, hash_value)
    except Exception as exc:
        _raise_if_qq_login_required(exc)
        logging.exception("腾讯问卷 HTTP 解析失败，url=%r", url)
        message = str(exc or "").strip() or "腾讯问卷 HTTP 解析失败"
        if not (
            message.startswith("腾讯问卷 HTTP 解析失败：")
            or message.startswith("腾讯问卷当前版本暂不支持")
        ):
            message = f"腾讯问卷 HTTP 解析失败：{message}"
        raise RuntimeError(message) from exc


__all__ = [
    "QQ_SUPPORTED_PROVIDER_TYPES",
    "QQ_PROVIDER_TYPE_TO_INTERNAL",
    "parse_qq_survey",
]
