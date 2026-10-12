from __future__ import annotations

from typing import Any

from surveycore.providers.common import (
    SUPPORTED_SURVEY_PROVIDERS as SUPPORTED_SURVEY_PROVIDERS,
    SURVEY_PROVIDER_CREDAMO as SURVEY_PROVIDER_CREDAMO,
    SURVEY_PROVIDER_QQ as SURVEY_PROVIDER_QQ,
    SURVEY_PROVIDER_WJX as SURVEY_PROVIDER_WJX,
    ensure_question_provider_fields as ensure_question_provider_fields,
    ensure_questions_provider_fields as ensure_questions_provider_fields,
    is_credamo_survey_url as is_credamo_survey_url,
    is_qq_survey_url as is_qq_survey_url,
    is_supported_survey_url as is_supported_survey_url,
    is_wjx_domain,
    is_wjx_survey_url as is_wjx_survey_url,
    make_provider_question_key as make_provider_question_key,
    normalize_survey_parse_url as normalize_survey_parse_url,
    supports_answer_datetime_window as supports_answer_datetime_window,
)

__all__ = [
    "SURVEY_PROVIDER_WJX", "SURVEY_PROVIDER_QQ", "SURVEY_PROVIDER_CREDAMO",
    "SUPPORTED_SURVEY_PROVIDERS", "normalize_survey_provider", "detect_survey_provider",
    "is_wjx_domain", "is_wjx_survey_url", "is_qq_survey_url", "is_credamo_survey_url",
    "is_supported_survey_url", "normalize_survey_parse_url", "supports_answer_datetime_window",
    "ensure_question_provider_fields", "ensure_questions_provider_fields",
    "make_provider_question_key",
]


def normalize_survey_provider(value: Any, default: str = SURVEY_PROVIDER_WJX) -> str:
    """保持桌面应用现有的未知平台默认值。"""
    try:
        provider = str(value or "").strip().lower()
    except Exception:
        provider = ""
    return provider if provider in SUPPORTED_SURVEY_PROVIDERS else str(default or SURVEY_PROVIDER_WJX)


def detect_survey_provider(url_value: str, default: str = SURVEY_PROVIDER_WJX) -> str:
    if is_qq_survey_url(url_value):
        return SURVEY_PROVIDER_QQ
    if is_credamo_survey_url(url_value):
        return SURVEY_PROVIDER_CREDAMO
    if is_wjx_domain(url_value):
        return SURVEY_PROVIDER_WJX
    return normalize_survey_provider(default)
