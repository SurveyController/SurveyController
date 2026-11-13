from __future__ import annotations

import logging
from typing import Any, Optional

import software.network.http as http_client
from software.network.config import SUBMISSION_REPORT_ENDPOINT
from software.network.proxy.policy.source import PROXY_SOURCE_BENEFIT, PROXY_SOURCE_DEFAULT
from software.network.proxy.session import get_authenticated_session, invalidate_access_token


def _normalize_proxy_provider(proxy_provider: Any) -> str:
    provider = str(proxy_provider or "").strip().lower()
    if provider in {PROXY_SOURCE_DEFAULT, PROXY_SOURCE_BENEFIT}:
        return "idiot" if provider == PROXY_SOURCE_BENEFIT else "default"
    if provider in {"default", "idiot", "unknown"}:
        return provider
    return "unknown"


def _build_headers(token: str) -> dict[str, str]:
    return {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
    }


async def report_submission_result_async(
    *,
    user_id: Any,
    survey_url: str,
    result: str,
    proxy_provider: Any,
    enabled: bool = True,
    client_version: Optional[str] = None,
) -> bool:
    if not enabled:
        return False

    try:
        normalized_user_id = int(user_id)
    except Exception:
        return False
    if normalized_user_id <= 0:
        return False
    try:
        session = get_authenticated_session()
    except Exception:
        return False
    if normalized_user_id != session.user_id:
        return False
    normalized_user_id = session.user_id

    payload = {
        "user_id": normalized_user_id,
        "survey_url": str(survey_url or "").strip(),
        "result": str(result or "").strip().lower(),
        "proxy_provider": _normalize_proxy_provider(proxy_provider),
        "client_version": str(client_version or "").strip(),
    }

    try:
        response = await http_client.apost(
            SUBMISSION_REPORT_ENDPOINT,
            json=payload,
            headers=_build_headers(session.access_token),
            timeout=10,
        )
        if int(getattr(response, "status_code", 0) or 0) == 401:
            try:
                payload = response.json()
            except Exception:
                payload = None
            if isinstance(payload, dict) and payload.get("detail") == "invalid_access_token":
                invalidate_access_token(session)
                return False
        response.raise_for_status()
    except Exception as exc:
        logging.info("提交结果上报失败：%s", exc, exc_info=True)
        return False
    return True


__all__ = [
    "report_submission_result_async",
]
