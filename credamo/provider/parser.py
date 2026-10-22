from __future__ import annotations

from typing import Any, Dict, List, Tuple

from surveycore.credamo.provider.parser import (
    CredamoParseError,
    _is_answerable_question,
    _normalize_question,
    _raw_to_normalized_input,
    _survey_title,
)

from software.core.config.user_agents import DEFAULT_USER_AGENT

from .http_runtime import (
    _CredamoHttpSession,
    _fetch_detail,
    _iter_raw_questions,
    _noauth_short_url,
    _origin_from_url,
    _request_headers,
    _short_url_from_url,
)


async def parse_credamo_survey(url: str) -> Tuple[List[Dict[str, Any]], str]:
    origin = _origin_from_url(url)
    short_url = _noauth_short_url(_short_url_from_url(url))
    headers = _request_headers(origin=origin, short_url=short_url, user_agent=DEFAULT_USER_AGENT)
    async with _CredamoHttpSession() as session:
        detail_data = await _fetch_detail(session, origin=origin, short_url=short_url, headers=headers)

    questions: List[Dict[str, Any]] = []
    for index, raw_question in enumerate(_iter_raw_questions(detail_data), start=1):
        normalized = _normalize_question(_raw_to_normalized_input(raw_question, fallback_num=index), fallback_num=index)
        if _is_answerable_question(normalized):
            questions.append(normalized)
    if not questions:
        raise CredamoParseError("见数详情接口未返回可解析题目，请确认链接为免登录问卷且已开放")
    return questions, _survey_title(detail_data)


__all__ = [
    "CredamoParseError",
    "parse_credamo_survey",
]
