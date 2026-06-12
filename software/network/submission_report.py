from __future__ import annotations

import logging
from typing import Any, Optional

import software.network.http as http_client
from software.app.config import (
    SUBMISSION_REPORT_ENDPOINT,
    SUBMISSION_REPORT_TELEMETRY_SETTING_KEY,
    app_settings,
    get_bool_from_qsettings,
)
from software.app.version import __VERSION__
from software.network.proxy.policy.source import PROXY_SOURCE_BENEFIT, PROXY_SOURCE_DEFAULT
from software.network.proxy.session import get_device_id


def is_submission_report_telemetry_enabled() -> bool:
    settings = app_settings()
    return get_bool_from_qsettings(settings.value(SUBMISSION_REPORT_TELEMETRY_SETTING_KEY), True)


def _normalize_proxy_provider(proxy_provider: Any) -> str:
    provider = str(proxy_provider or "").strip().lower()
    if provider in {PROXY_SOURCE_DEFAULT, PROXY_SOURCE_BENEFIT}:
        return "idiot" if provider == PROXY_SOURCE_BENEFIT else "default"
    if provider in {"default", "idiot", "unknown"}:
        return provider
    return "unknown"


def _build_headers() -> dict[str, str]:
    return {
        "Content-Type": "application/json",
        "X-Device-ID": get_device_id(),
    }


async def report_submission_result_async(
    *,
    user_id: Any,
    survey_url: str,
    result: str,
    proxy_provider: Any,
    client_version: Optional[str] = None,
) -> bool:
    if not is_submission_report_telemetry_enabled():
        return False

    try:
        normalized_user_id = int(user_id)
    except Exception:
        return False
    if normalized_user_id <= 0:
        return False

    payload = {
        "user_id": normalized_user_id,
        "survey_url": str(survey_url or "").strip(),
        "result": str(result or "").strip().lower(),
        "proxy_provider": _normalize_proxy_provider(proxy_provider),
        "client_version": str(client_version or __VERSION__).strip(),
    }

    try:
        response = await http_client.apost(
            SUBMISSION_REPORT_ENDPOINT,
            json=payload,
            headers=_build_headers(),
            timeout=10,
        )
        response.raise_for_status()
    except Exception as exc:
        logging.info("提交结果上报失败：%s", exc, exc_info=True)
        return False
    return True


__all__ = [
    "is_submission_report_telemetry_enabled",
    "report_submission_result_async",
]
