from __future__ import annotations

import sys
from typing import Any, Callable

from software.system.secure_store import delete_secret, read_secret, set_secret

from .models import RandomIPAuthError, RandomIPSession
from .normalize import (
    _normalize_quota_known,
    _normalize_quota_state,
    _to_non_negative_int,
    _to_non_negative_quota,
    _to_optional_bool,
    format_quota_value,
)

_TOKEN_KEY = "random_ip/access_token"
_SESSION_FIELDS = ("user_id", "remaining_quota", "total_quota", "used_quota", "quota_known")


def settings_key(name: str) -> str:
    return f"random_ip_auth/{name}"


def _token_store_supported() -> bool:
    return sys.platform == "win32"


def load_access_token() -> str:
    if not _token_store_supported():
        return ""
    result = read_secret(_TOKEN_KEY)
    if result.status == "not_found":
        return ""
    if result.status != "ok":
        raise RandomIPAuthError("session_store_unavailable")
    return result.value


def persist_access_token(token: str) -> None:
    if not _token_store_supported():
        return
    if token:
        set_secret(_TOKEN_KEY, token)
    else:
        delete_secret(_TOKEN_KEY)
    if load_access_token() != token:
        raise RandomIPAuthError("session_persist_failed:access_token")


def load_session(settings: Any, build_device_id: Callable[[], str]) -> RandomIPSession:
    device_id = str(settings.value(settings_key("device_id")) or "").strip()
    if not device_id:
        device_id = build_device_id()
        settings.setValue(settings_key("device_id"), device_id)
        settings.sync()
    user_id = _to_non_negative_int(settings.value(settings_key("user_id")))
    remaining = _to_non_negative_quota(settings.value(settings_key("remaining_quota")))
    total = _to_non_negative_quota(settings.value(settings_key("total_quota")), remaining)
    used = _to_non_negative_quota(
        settings.value(settings_key("used_quota")), max(0.0, total - remaining)
    )
    remaining, total, used = _normalize_quota_state(
        remaining_quota=remaining, total_quota=total, used_quota=used
    )
    try:
        access_token = load_access_token() if user_id > 0 else ""
    except RandomIPAuthError:
        access_token = ""
    return RandomIPSession(
        device_id=device_id,
        user_id=user_id,
        access_token=access_token,
        remaining_quota=remaining,
        total_quota=total,
        used_quota=used,
        quota_known=_normalize_quota_known(
            user_id=user_id,
            total_quota=total,
            used_quota=used,
            quota_known=_to_optional_bool(settings.value(settings_key("quota_known"))),
        ),
    )


def persist_session(settings: Any, session: RandomIPSession, *, verify: bool = False) -> None:
    values = {
        "device_id": session.device_id,
        "user_id": session.user_id,
        "remaining_quota": format_quota_value(session.remaining_quota),
        "total_quota": format_quota_value(session.total_quota),
        "used_quota": format_quota_value(session.used_quota),
        "quota_known": session.quota_known,
    }
    for key, value in values.items():
        settings.setValue(settings_key(key), value)
    settings.sync()
    if verify:
        for key, value in values.items():
            actual = settings.value(settings_key(key))
            if key == "quota_known":
                matches = _to_optional_bool(actual) == value
            else:
                matches = str(actual) == str(value)
            if not matches:
                raise RandomIPAuthError(f"session_persist_failed:settings.{key}")


def clear_session(settings: Any) -> None:
    persist_access_token("")
    for key in _SESSION_FIELDS:
        settings.remove(settings_key(key))
    settings.sync()
