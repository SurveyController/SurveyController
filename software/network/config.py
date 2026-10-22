from __future__ import annotations

import os
import sys
from typing import Any, cast

PROXY_MAX_PROXIES = 80
PROXY_HEALTH_CHECK_URL = "https://www.wjx.cn"
PROXY_HEALTH_CHECK_TIMEOUT = 15
PROXY_STATUS_TIMEOUT_SECONDS = 5
PROXY_TTL_GRACE_SECONDS = 20
PROXY_MINUTE_OPTIONS = (1, 3, 5, 10, 15, 30)
PROXY_QUOTA_COST_MAP = {
    1: 1,
    3: 2,
    5: 3,
    10: 5,
    15: 8,
    30: 20,
}

PROXY_SOURCE_DEFAULT = "default"
PROXY_SOURCE_BENEFIT = "benefit"
PROXY_SOURCE_CUSTOM = "custom"
PROXY_POOL_ORDINARY = "ordinary"
PROXY_POOL_QUALITY = "quality"

_DEFAULT_AUTH_TRIAL = "https://api-wjx.hungrym0.com/api/auth/trial"
_DEFAULT_CARD_REDEEM = "https://api-wjx.hungrym0.com/api/cards/redeem"
_DEFAULT_IP_EXTRACT = "https://api-wjx.hungrym0.com/api/ip/extract"
_DEFAULT_SUBMISSION_REPORT = "https://api-wjx.hungrym0.com/api/submission/report"
_DEFAULT_STATUS = "https://api-wjx.hungrym0.com/api/status"


def _read_windows_env_var(key: str) -> str:
    if sys.platform != "win32":
        return ""
    try:
        import winreg
    except Exception:
        return ""
    registry = cast(Any, winreg)
    try:
        with registry.OpenKey(registry.HKEY_CURRENT_USER, "Environment") as reg_key:
            value, _ = registry.QueryValueEx(reg_key, key)
    except FileNotFoundError:
        return ""
    except Exception:
        return ""
    return str(value).strip() if value is not None else ""


def _resolve_env_value(key: str, default: str) -> str:
    return os.environ.get(key) or _read_windows_env_var(key) or default


AUTH_TRIAL_ENDPOINT = _resolve_env_value("AUTH_TRIAL_ENDPOINT", _DEFAULT_AUTH_TRIAL)
CARD_REDEEM_ENDPOINT = _resolve_env_value("CARD_REDEEM_ENDPOINT", _DEFAULT_CARD_REDEEM)
IP_EXTRACT_ENDPOINT = _resolve_env_value("IP_EXTRACT_ENDPOINT", _DEFAULT_IP_EXTRACT)
SUBMISSION_REPORT_ENDPOINT = _resolve_env_value(
    "SUBMISSION_REPORT_ENDPOINT",
    _DEFAULT_SUBMISSION_REPORT,
)
STATUS_ENDPOINT = _resolve_env_value("STATUS_ENDPOINT", _DEFAULT_STATUS)

__all__ = [
    "AUTH_TRIAL_ENDPOINT",
    "CARD_REDEEM_ENDPOINT",
    "IP_EXTRACT_ENDPOINT",
    "PROXY_HEALTH_CHECK_TIMEOUT",
    "PROXY_HEALTH_CHECK_URL",
    "PROXY_MAX_PROXIES",
    "PROXY_MINUTE_OPTIONS",
    "PROXY_POOL_ORDINARY",
    "PROXY_POOL_QUALITY",
    "PROXY_QUOTA_COST_MAP",
    "PROXY_SOURCE_BENEFIT",
    "PROXY_SOURCE_CUSTOM",
    "PROXY_SOURCE_DEFAULT",
    "PROXY_STATUS_TIMEOUT_SECONDS",
    "PROXY_TTL_GRACE_SECONDS",
    "STATUS_ENDPOINT",
    "SUBMISSION_REPORT_ENDPOINT",
]
