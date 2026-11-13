from __future__ import annotations

import asyncio
import logging
import re
import threading
from concurrent.futures import Future
from dataclasses import replace
from urllib.parse import urlsplit
from typing import Any, Dict, Optional

from software.network.config import (
    AUTH_SESSION_ENDPOINT,
    AUTH_TRIAL_ENDPOINT,
    CARD_REDEEM_ENDPOINT,
    IP_EXTRACT_ENDPOINT,
)
from software.io.runtime_environment import preference_store as app_settings
from software.logging.log_utils import log_suppressed_exception
from software.system.device_fingerprint import build_stable_device_id

from . import store
from .client import (
    _aget_json,
    _build_headers,
    _apost_json,
    _extract_error_payload,
    _log_extract_proxy_issue,
    _parse_batch_extract_payload,
    _parse_single_extract_payload,
)
from .models import RandomIPAuthError, RandomIPSession
from .normalize import (
    _build_quota_snapshot,
    _is_valid_user_id,
    _normalize_quota_known,
    _normalize_quota_state,
    _require_valid_user_id,
    _resolve_quota_from_payload,
    _session_state_name,
    _to_non_negative_int,
    _to_non_negative_quota,
)

_SESSION_PERSIST_FAILED_DETAIL = "session_persist_failed"
_EXTRACT_REQUEST_BASE_TIMEOUT_SECONDS = 10.0
_EXTRACT_REQUEST_EXTRA_TIMEOUT_PER_PROXY_SECONDS = 2.0
_EXTRACT_REQUEST_MAX_TIMEOUT_SECONDS = 60.0

_session_lock = threading.RLock()

_session_loaded = False

_session = RandomIPSession()
_session_revision = 0
_authentication_future: Future[RandomIPSession] | None = None


def _get_settings() -> Any:
    return app_settings()


_settings_key = store.settings_key


def _has_complete_session(session: RandomIPSession) -> bool:
    return _is_valid_user_id(session.user_id) and bool(session.access_token)


def _endpoint_name(url: str) -> str:
    parsed = urlsplit(str(url or ""))
    host = str(parsed.netloc or "").strip() or "-"
    path = str(parsed.path or "").strip() or "/"
    return f"{host}{path}"


def _extract_request_timeout_seconds(num: int) -> float:

    request_num = max(1, _to_non_negative_int(num, 1))
    timeout = _EXTRACT_REQUEST_BASE_TIMEOUT_SECONDS + (
        (request_num - 1) * _EXTRACT_REQUEST_EXTRA_TIMEOUT_PER_PROXY_SECONDS
    )
    return min(_EXTRACT_REQUEST_MAX_TIMEOUT_SECONDS, timeout)


def _ensure_loaded() -> None:
    global _session_loaded, _session
    with _session_lock:
        if not _session_loaded:
            _session = store.load_session(_get_settings(), build_stable_device_id)
            _session_loaded = True


def _set_session(
    new_session: RandomIPSession,
    *,
    verify_auth_persistence: bool = False,
    expected_revision: int | None = None,
) -> RandomIPSession:
    global _session, _session_revision
    with _session_lock:
        _ensure_loaded()
        if expected_revision is not None and expected_revision != _session_revision:
            if not _has_complete_session(_session):
                raise RandomIPAuthError("session_changed")
            return replace(_session)
        previous_session = _session
        normalized_remaining, normalized_total, normalized_used = _normalize_quota_state(
            remaining_quota=new_session.remaining_quota,
            total_quota=new_session.total_quota,
            used_quota=new_session.used_quota,
        )
        candidate = replace(
            new_session,
            remaining_quota=normalized_remaining,
            total_quota=normalized_total,
            used_quota=normalized_used,
            quota_known=_normalize_quota_known(
                user_id=new_session.user_id,
                total_quota=normalized_total,
                used_quota=normalized_used,
                quota_known=new_session.quota_known,
            ),
        )
        _session = candidate
        try:
            store.persist_session(_get_settings(), candidate, verify=verify_auth_persistence)
            if candidate.access_token != previous_session.access_token:
                store.persist_access_token(candidate.access_token)
            _session_revision += 1
            return _session
        except Exception:
            _session = previous_session
            store.persist_session(_get_settings(), previous_session)
            if candidate.access_token != previous_session.access_token:
                store.persist_access_token(previous_session.access_token)
            raise


def _read_session() -> RandomIPSession:
    _ensure_loaded()
    with _session_lock:
        return replace(_session)


def get_device_id() -> str:
    return _read_session().device_id


def clear_session(*, reason: str = "unspecified") -> None:
    global _session, _session_revision
    with _session_lock:
        _ensure_loaded()
        _session = RandomIPSession(device_id=_session.device_id)
        _session_revision += 1
        store.clear_session(_get_settings())
        logging.warning("随机IP本地会话已清空：%s", reason)


def has_authenticated_session() -> bool:
    session = _read_session()
    return _has_complete_session(session)


def get_session_snapshot() -> Dict[str, Any]:
    session = _read_session()
    quota = _build_quota_snapshot(session)
    return {
        "authenticated": _has_complete_session(session),
        "device_id": session.device_id,
        "user_id": int(session.user_id or 0),
        "remaining_quota": quota["remaining_quota"],
        "total_quota": quota["total_quota"],
        "used_quota": quota["used_quota"],
        "quota_known": bool(quota.get("quota_known")),
        "has_access_token": bool(session.access_token),
        "has_valid_user_id": _is_valid_user_id(session.user_id),
        "session_state": _session_state_name(session),
    }


def has_unknown_local_quota(snapshot: Optional[Dict[str, Any]] = None) -> bool:

    payload = snapshot if isinstance(snapshot, dict) else get_session_snapshot()
    if not bool(payload.get("authenticated")):
        return False
    if "quota_known" in payload:
        return not bool(payload.get("quota_known"))
    user_id = _to_non_negative_int(payload.get("user_id"), 0)
    total_quota = _to_non_negative_quota(payload.get("total_quota"), 0.0)
    used_quota = _to_non_negative_quota(payload.get("used_quota"), 0.0)
    return user_id > 0 and total_quota <= 0 and used_quota <= 0


def is_quota_exhausted(snapshot: Optional[Dict[str, Any]] = None) -> bool:
    payload = snapshot if isinstance(snapshot, dict) else get_session_snapshot()
    if not bool(payload.get("authenticated")):
        return False
    if "quota_known" in payload and not bool(payload.get("quota_known")):
        return False
    return _to_non_negative_quota(payload.get("remaining_quota"), 0.0) <= 0


def format_random_ip_error(exc: BaseException) -> str:
    if not isinstance(exc, RandomIPAuthError):
        return str(exc or "请求失败，请稍后重试")
    detail = exc.detail
    if detail == "invalid_request_body":
        return "请求格式不正确，请更新客户端后重试"
    if detail.startswith(_SESSION_PERSIST_FAILED_DETAIL) or detail == "session_store_unavailable":
        return "随机IP账号信息没能安全保存或读取，请重启软件重试或通过社区 QQ 群获取帮助"
    if detail in {"invalid_legacy_session", "device_not_bound"}:
        return "本机旧账户与设备记录无法匹配，请通过社区 QQ 群获取帮助"
    if detail == "invalid_access_token":
        return "随机IP登录已失效，请重新启用随机IP连接账户"
    if detail == "token_exchange_rate_limited":
        return "账户连接过于频繁，请稍后重试"
    if detail == "device_banned":
        return "当前设备已被封禁，请通过社区 QQ 群获取帮助"
    if detail == "user_banned":
        return "当前账号已被封禁，请通过社区 QQ 群获取帮助"
    if detail == "user_expired":
        return "随机IP账号已过期，请通过社区 QQ 群获取补充额度或重新开通的帮助"
    if detail == "device_owned_by_other_user":
        return "当前设备绑定的随机IP账号与本机记录不一致，请通过社区 QQ 群获取帮助"
    if detail == "user_id_required":
        return "本机缺少随机IP用户ID，请通过社区 QQ 群获取帮助"
    if detail == "invalid_user_id":
        return "本机保存的随机IP用户ID无效，请重新连接账户或通过社区 QQ 群获取帮助"
    if detail == "unauthorized":
        return "随机IP账号校验失败，请重新连接账户或通过社区 QQ 群获取帮助"
    if detail == "minute_not_allowed":
        return "代理时长参数不被后端接受，请更新客户端"
    if detail == "pool_not_allowed":
        return "代理池参数不被后端接受，请更新客户端"
    if detail == "area_not_allowed":
        return "地区参数不被后端接受，请更新客户端或检查地区配置"
    if detail == "invalid_area":
        return "指定地区无效，请重新选择地区后再试"
    if detail == "invalid_upstream":
        return "代理上游参数不被后端接受，请更新客户端"
    if detail == "minute_not_supported_for_idiot":
        return "限时福利代理源只支持 1 分钟代理，请切回默认代理源"
    if detail == "invalid_area_for_idiot":
        return "限时福利代理源的地区格式不正确，请重新选择具体城市后再试"
    if detail == "insufficient_quota":
        return "随机IP已用额度已达到上限，请先补充额度"
    if detail == "token_rate_limited":
        return "当前账号请求过于频繁，请稍后再试"
    if detail == "device_rate_limited":
        return "当前设备请求过于频繁，请稍后再试"
    if detail == "ip_rate_limited":
        return "当前网络请求过于频繁，请稍后再试"
    if detail == "user_daily_limit_exceeded":
        return "今日随机IP额度已达到上限"
    if detail == "site_daily_limit_exceeded":
        return "服务端今日额度已达上限，请稍后再试"
    if detail == "upstream_surplus_exhausted":
        return "上游代理余额不足，请稍后再试"
    if detail == "upstream_rejected":
        return "上游代理服务拒绝了请求，请稍后重试"
    if detail == "not_authenticated":
        return "本机没有可恢复的随机IP账户，当前暂不支持新账户开通"
    if detail == "session_changed":
        return "随机IP会话已更新，请重试"
    if detail.startswith("network_error:"):
        return f"网络请求失败：{detail.split(':', 1)[1].strip()}"
    if detail == "invalid_response:user_id_invalid":
        return "服务端返回了无效的随机IP用户ID，请稍后重试"
    if detail.startswith("invalid_response"):
        return "服务端返回格式异常，请稍后重试"
    if detail.startswith("http_"):
        return f"服务端暂时不可用（{detail[5:]}）"
    return detail or "请求失败，请稍后重试"


def _parse_session_payload(
    data: Dict[str, Any],
    *,
    device_id: str,
    fallback_session: Optional[RandomIPSession] = None,
) -> RandomIPSession:
    fallback = fallback_session or RandomIPSession(device_id=device_id)
    if "user_id" not in data:
        logging.warning(
            "随机IP会话响应缺少 user_id：keys=%s", ",".join(sorted(str(k) for k in data.keys()))
        )
        raise RandomIPAuthError("invalid_response:user_id_missing")
    raw_user_id = data.get("user_id")
    if not _is_valid_user_id(raw_user_id):
        logging.warning(
            "随机IP会话响应中的 user_id 无效：value=%r type=%s keys=%s",
            raw_user_id,
            type(raw_user_id).__name__,
            ",".join(sorted(str(k) for k in data.keys())),
        )
        raise RandomIPAuthError("invalid_response:user_id_invalid")
    if fallback.user_id and _require_valid_user_id(raw_user_id) != fallback.user_id:
        raise RandomIPAuthError("invalid_response:user_id_mismatch")
    normalized_remaining, normalized_total, normalized_used = _resolve_quota_from_payload(
        data,
        log_context="随机IP会话响应",
    )
    session = RandomIPSession(
        device_id=device_id,
        user_id=_require_valid_user_id(raw_user_id),
        access_token=fallback.access_token,
        remaining_quota=normalized_remaining,
        total_quota=normalized_total,
        used_quota=normalized_used,
        quota_known=True,
    )
    return session


def _parse_session_response(
    response: Any, *, fallback_session: Optional[RandomIPSession] = None
) -> RandomIPSession:
    try:
        data = response.json()
    except Exception:
        raise RandomIPAuthError("invalid_response") from None
    if not isinstance(data, dict):
        raise RandomIPAuthError("invalid_response")
    device_id = fallback_session.device_id if fallback_session is not None else get_device_id()
    return _parse_session_payload(data, device_id=device_id, fallback_session=fallback_session)


async def ensure_authenticated_session_async() -> RandomIPSession:
    global _authentication_future
    with _session_lock:
        session = _read_session()
        if _has_complete_session(session):
            return session
        if not _is_valid_user_id(session.user_id) or not session.device_id:
            raise RandomIPAuthError("not_authenticated")
        owner = _authentication_future is None
        if owner:
            _authentication_future = Future()
        pending = _authentication_future
        session_revision = _session_revision
    assert pending is not None
    if not owner:
        return replace(await asyncio.shield(asyncio.wrap_future(pending)))
    try:
        response = await _apost_json(
            AUTH_TRIAL_ENDPOINT,
            json_body={"user_id": session.user_id},
            headers=_build_headers(device_id=session.device_id),
        )
        if response.status_code != 200:
            raise _extract_error_payload(response)
        data = response.json()
        if not isinstance(data, dict):
            raise RandomIPAuthError("invalid_response")
        token = data.get("access_token")
        if (
            not isinstance(token, str)
            or re.fullmatch(r"[a-f0-9]{64}", token) is None
            or data.get("token_type") != "Bearer"
        ):
            raise RandomIPAuthError("invalid_response:access_token")
        candidate = _parse_session_payload(
            data, device_id=session.device_id, fallback_session=session
        )
        candidate.access_token = token
        result = _set_session(
            candidate, verify_auth_persistence=True, expected_revision=session_revision
        )
        pending.set_result(result)
        return replace(result)
    except BaseException as exc:
        pending.set_exception(exc)
        pending.exception()
        raise
    finally:
        with _session_lock:
            if _authentication_future is pending:
                _authentication_future = None


def invalidate_access_token(session: RandomIPSession) -> None:
    with _session_lock:
        current = _read_session()
        if (
            current.user_id == session.user_id
            and current.device_id == session.device_id
            and current.access_token == session.access_token
        ):
            _set_session(replace(current, access_token=""))


def _response_error(
    response: Any,
    session: RandomIPSession,
    *,
    sensitive_values: tuple[str, ...] = (),
) -> RandomIPAuthError:
    error = _extract_error_payload(
        response,
        sensitive_values=(session.access_token, *sensitive_values),
    )
    if error.detail == "invalid_access_token":
        invalidate_access_token(session)
    return error


def get_authenticated_session() -> RandomIPSession:
    return _require_authenticated_session()


def _require_authenticated_session() -> RandomIPSession:
    session = _read_session()
    if _has_complete_session(session):
        return session
    raise RandomIPAuthError("not_authenticated")


async def extract_proxy_async(
    *,
    minute: int,
    pool: str,
    area: Optional[str],
    num: int = 1,
    upstream: str = "default",
) -> Dict[str, Any]:
    with _session_lock:
        session = _require_authenticated_session()
        session_revision = _session_revision
    body: Dict[str, Any] = {
        "user_id": int(session.user_id),
        "minute": int(minute),
        "pool": str(pool or "").strip(),
    }
    upstream_value = str(upstream or "").strip().lower()
    if upstream_value:
        body["upstream"] = upstream_value
    request_num = max(1, int(num or 1))
    if request_num > 1:
        body["num"] = request_num
    area_code = str(area or "").strip()
    if area_code:
        body["area"] = area_code

    try:
        response = await _apost_json(
            IP_EXTRACT_ENDPOINT,
            json_body=body,
            headers=_build_headers(access_token=session.access_token),
            timeout=_extract_request_timeout_seconds(request_num),
        )
    except RandomIPAuthError as exc:
        _log_extract_proxy_issue("随机IP提取请求异常", request_body=body, attempt=1, error=exc)
        raise
    status_code = int(getattr(response, "status_code", 0) or 0)
    if status_code == 200:
        try:
            data = response.json()
        except Exception as exc:
            _log_extract_proxy_issue(
                "随机IP提取响应解析失败", request_body=body, attempt=1, response=response, error=exc
            )
            raise RandomIPAuthError("invalid_response") from None
        if not isinstance(data, dict):
            _log_extract_proxy_issue(
                "随机IP提取响应结构异常", request_body=body, attempt=1, response=response
            )
            raise RandomIPAuthError("invalid_response")
        if request_num > 1 and isinstance(data.get("items"), list):
            return _parse_batch_extract_payload(
                data,
                request_body=body,
                attempt=1,
                response=response,
                expected_revision=session_revision,
            )
        return _parse_single_extract_payload(
            data,
            request_body=body,
            attempt=1,
            response=response,
            expected_revision=session_revision,
        )
    error = _response_error(response, session)
    _log_extract_proxy_issue(
        "随机IP提取失败", request_body=body, attempt=1, response=response, error=error
    )
    raise error


def get_quota_snapshot() -> Dict[str, Any]:
    return _build_quota_snapshot(_read_session())


def get_fresh_quota_snapshot() -> Dict[str, Any]:
    return _build_quota_snapshot(_require_authenticated_session())


async def sync_quota_snapshot_from_server_async(*, emit_logs: bool = True) -> Dict[str, Any]:
    with _session_lock:
        session = _require_authenticated_session()
        session_revision = _session_revision
    if emit_logs:
        logging.debug("正在同步随机IP额度")
    response = await _aget_json(
        AUTH_SESSION_ENDPOINT, headers=_build_headers(access_token=session.access_token)
    )
    if response.status_code != 200:
        error = _response_error(response, session)
        if emit_logs:
            logging.warning(
                "随机IP额度同步失败：%s",
                format_random_ip_error(error),
            )
        raise error
    refreshed = _parse_session_response(response, fallback_session=session)
    persisted = _set_session(
        refreshed, verify_auth_persistence=True, expected_revision=session_revision
    )
    if emit_logs:
        logging.debug("随机IP额度已同步")
    return _build_quota_snapshot(persisted)


def _apply_quota_payload(
    data: Dict[str, Any],
    *,
    log_context: str = "随机IP额度响应",
    expected_revision: int | None = None,
) -> RandomIPSession:
    session = _read_session()
    normalized_remaining, normalized_total, normalized_used = _resolve_quota_from_payload(
        data,
        log_context=log_context,
    )
    updated = replace(
        session,
        remaining_quota=normalized_remaining,
        total_quota=normalized_total,
        used_quota=normalized_used,
        quota_known=True,
    )
    return _set_session(updated, expected_revision=expected_revision)


async def redeem_card_async(card_code: str) -> Dict[str, Any]:
    with _session_lock:
        session = _require_authenticated_session()
        session_revision = _session_revision
    normalized_card_code = str(card_code or "").strip()
    if re.fullmatch(r"[a-z0-9]{16}", normalized_card_code) is None:
        raise RandomIPAuthError("invalid_redeem_card_code")
    response = await _apost_json(
        CARD_REDEEM_ENDPOINT,
        json_body={"card_code": normalized_card_code},
        headers=_build_headers(access_token=session.access_token),
    )
    if int(getattr(response, "status_code", 0) or 0) != 200:
        raise _response_error(response, session, sensitive_values=(normalized_card_code,))
    try:
        data = response.json()
    except Exception:
        raise RandomIPAuthError("invalid_response") from None
    if not isinstance(data, dict):
        raise RandomIPAuthError("invalid_response")

    updated_session = _apply_quota_payload(
        data,
        log_context="随机IP额度卡密兑换响应",
        expected_revision=session_revision,
    )
    redeemed = bool(data.get("redeemed"))
    card_quota = _to_non_negative_quota(data.get("card_quota"), 0.0)
    detail = str(data.get("detail") or "").strip()
    return {
        "redeemed": redeemed,
        "card_quota": card_quota,
        "detail": detail,
        "used_quota": updated_session.used_quota,
        "remaining_quota": updated_session.remaining_quota,
        "total_quota": updated_session.total_quota,
    }


def load_session_for_startup() -> None:
    try:
        _ensure_loaded()
    except Exception as exc:
        log_suppressed_exception("auth.load_session_for_startup", exc, level=logging.WARNING)
