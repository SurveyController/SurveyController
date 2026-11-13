from __future__ import annotations

import logging
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, Optional

from .models import RandomIPAuthError, RandomIPSession


def _to_non_negative_int(value: Any, default: int = 0) -> int:
    try:
        parsed = int(value)
    except Exception:
        return max(0, int(default))
    return max(0, parsed)


def _to_decimal(value: Any) -> Optional[Decimal]:
    if isinstance(value, Decimal):
        parsed = value
    else:
        try:
            text = str(value).strip()
        except Exception:
            return None
        if not text:
            return None
        try:
            parsed = Decimal(text)
        except (InvalidOperation, ValueError):
            return None
    if not parsed.is_finite():
        return None
    return parsed


def _to_non_negative_quota(value: Any, default: float = 0.0) -> float:
    parsed = _to_decimal(value)
    if parsed is None:
        parsed = _to_decimal(default)
    if parsed is None:
        parsed = Decimal("0")
    if parsed < 0:
        return 0.0
    return float(parsed)


def _to_optional_non_negative_quota(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, str) and not value.strip():
        return None
    parsed = _to_decimal(value)
    if parsed is None or parsed < 0:
        return None
    return float(parsed)


def format_quota_value(value: Any) -> str:
    parsed = _to_decimal(value)
    if parsed is None or parsed < 0:
        parsed = Decimal("0")
    normalized = (
        parsed.quantize(Decimal(1)) if parsed == parsed.to_integral() else parsed.normalize()
    )
    text = format(normalized, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def _is_valid_user_id(value: Any) -> bool:
    try:
        return int(value) > 0
    except Exception:
        return False


def _require_valid_user_id(value: Any) -> int:
    if not _is_valid_user_id(value):
        raise RandomIPAuthError("invalid_response:user_id_invalid")
    return int(value)


def _to_optional_bool(value: Any) -> Optional[bool]:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if not text:
        return None
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return None


def _can_trust_quota_numbers(*, total_quota: float, used_quota: float) -> bool:
    return (
        _to_non_negative_quota(total_quota, 0.0) > 0 or _to_non_negative_quota(used_quota, 0.0) > 0
    )


def _normalize_quota_known(
    *,
    user_id: Any,
    total_quota: float,
    used_quota: float,
    quota_known: Optional[bool],
) -> bool:
    if not _is_valid_user_id(user_id):
        return False
    if quota_known is False:
        return False
    return quota_known is True or _can_trust_quota_numbers(
        total_quota=total_quota, used_quota=used_quota
    )


def _session_state_name(session: RandomIPSession) -> str:
    if _is_valid_user_id(session.user_id) and session.access_token:
        return "ready"
    if _is_valid_user_id(session.user_id):
        return "legacy"
    return "anonymous"


def _normalize_quota_state(
    *,
    remaining_quota: Any = None,
    total_quota: Any = None,
    used_quota: Any = None,
    default_total_quota: float = 0.0,
) -> tuple[float, float, float]:
    has_remaining = remaining_quota is not None
    has_used = used_quota is not None
    remaining = _to_non_negative_quota(remaining_quota, 0.0) if has_remaining else 0.0
    total = _to_non_negative_quota(total_quota, default_total_quota)
    if has_used:
        used = _to_non_negative_quota(used_quota, 0.0)
        total = max(total, used)
        remaining = min(remaining, total) if has_remaining else max(0.0, total - used)
        return remaining, total, used
    if has_remaining:
        total = max(total, remaining)
        used = max(0.0, total - remaining)
        return remaining, total, used
    total = max(0.0, total)
    used = 0.0
    remaining = total
    return remaining, total, used


def _read_payload_quota_number(
    data: Dict[str, Any], key: str, *, log_context: str
) -> Optional[float]:
    if key not in data:
        return None
    value = data.get(key)
    parsed = _to_optional_non_negative_quota(value)
    if parsed is not None:
        return parsed
    logging.warning("%s 中的额度字段无效：field=%s value=%r", log_context, key, value)
    return None


def _resolve_quota_from_payload(
    data: Dict[str, Any],
    *,
    log_context: str,
) -> tuple[float, float, float]:
    remaining_quota = _read_payload_quota_number(data, "remaining_quota", log_context=log_context)
    total_quota = _read_payload_quota_number(data, "total_quota", log_context=log_context)
    used_quota = _read_payload_quota_number(data, "used_quota", log_context=log_context)
    if remaining_quota is None or total_quota is None:
        raise RandomIPAuthError(f"invalid_response:quota_missing:{log_context}")
    return _normalize_quota_state(
        remaining_quota=remaining_quota,
        total_quota=total_quota,
        used_quota=used_quota,
    )


def _build_quota_snapshot(session: RandomIPSession) -> Dict[str, Any]:
    remaining_quota, total_quota, used_quota = _normalize_quota_state(
        remaining_quota=session.remaining_quota,
        total_quota=session.total_quota,
        used_quota=session.used_quota,
    )
    return {
        "used_quota": used_quota,
        "total_quota": total_quota,
        "remaining_quota": remaining_quota,
        "quota_known": bool(session.quota_known),
    }
