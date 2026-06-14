"""提交结果遥测上报。"""

from __future__ import annotations

import logging
from typing import Any, Dict

import software.network.http as http_client
from software.app.config import (
    DEFAULT_HTTP_HEADERS,
    SUBMISSION_REPORT_ENDPOINT,
    SUBMISSION_REPORT_TELEMETRY_SETTING_KEY,
    app_settings,
    get_bool_from_qsettings,
)
from software.app.version import __VERSION__
from software.network.proxy.policy.source import PROXY_SOURCE_BENEFIT, PROXY_SOURCE_CUSTOM, PROXY_SOURCE_DEFAULT
from software.network.proxy.session import get_device_id

_VALID_RESULTS = {"success", "failed"}
_PROXY_PROVIDER_ALIASES = {
    PROXY_SOURCE_DEFAULT: "default",
    PROXY_SOURCE_BENEFIT: "idiot",
    PROXY_SOURCE_CUSTOM: "custom",
}


def is_submission_report_telemetry_enabled() -> bool:
    return get_bool_from_qsettings(
        app_settings().value(SUBMISSION_REPORT_TELEMETRY_SETTING_KEY),
        True,
    )


def _normalize_result(value: Any) -> str:
    result = str(value or "").strip().lower()
    return result if result in _VALID_RESULTS else "failed"


def _normalize_proxy_provider(value: Any) -> str:
    provider = str(value or "").strip().lower()
    return _PROXY_PROVIDER_ALIASES.get(provider, provider or "unknown")


def build_submission_report_payload(
    *,
    survey_url: str,
    result: str,
    proxy_provider: str,
    user_id: int,
    device_id: str | None = None,
) -> Dict[str, Any]:
    return {
        "user_id": int(user_id or 0),
        "device_id": str(device_id or get_device_id() or ""),
        "survey_url": str(survey_url or ""),
        "result": _normalize_result(result),
        "proxy_provider": _normalize_proxy_provider(proxy_provider),
        "app_version": str(__VERSION__),
    }


async def report_submission_result_async(
    *,
    survey_url: str,
    result: str,
    proxy_provider: str,
    user_id: int,
) -> bool:
    if not is_submission_report_telemetry_enabled():
        return False
    if int(user_id or 0) <= 0:
        return False
    endpoint = str(SUBMISSION_REPORT_ENDPOINT or "").strip()
    if not endpoint:
        return False
    payload = build_submission_report_payload(
        survey_url=survey_url,
        result=result,
        proxy_provider=proxy_provider,
        user_id=int(user_id or 0),
    )
    headers = dict(DEFAULT_HTTP_HEADERS)
    headers["Content-Type"] = "application/json"
    try:
        response = await http_client.apost(
            endpoint,
            json=payload,
            headers=headers,
            timeout=10,
        )
        response.raise_for_status()
        return True
    except Exception:
        logging.info("提交结果遥测上报失败", exc_info=True)
        return False


__all__ = [
    "build_submission_report_payload",
    "is_submission_report_telemetry_enabled",
    "report_submission_result_async",
]
