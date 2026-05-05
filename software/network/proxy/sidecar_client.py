"""Go 代理 sidecar HTTP 客户端。"""
from __future__ import annotations

from typing import Any, Dict, Optional

import software.network.http as http_client
from software.core.task import ProxyLease
from software.network.proxy.policy.settings import ProxySettings


class ProxySidecarError(RuntimeError):
    """本地代理 sidecar 请求失败。"""


def _coerce_error_message(response: Any, fallback: str) -> str:
    try:
        payload = response.json()
    except Exception:
        payload = None
    if isinstance(payload, dict):
        message = str(payload.get("error") or "").strip()
        if message:
            return message
    return str(fallback or "代理服务请求失败")


def _normalize_proxy_address(proxy_address: str) -> str:
    normalized = str(proxy_address or "").strip()
    if not normalized:
        return ""
    if "://" not in normalized:
        normalized = f"http://{normalized}"
    return normalized


def _coerce_proxy_lease(item: Any) -> Optional[ProxyLease]:
    if isinstance(item, ProxyLease):
        normalized = _normalize_proxy_address(item.address)
        if not normalized:
            return None
        if normalized == item.address:
            return item
        return ProxyLease(
            address=normalized,
            expire_at=item.expire_at,
            expire_ts=float(item.expire_ts or 0.0),
            poolable=bool(item.poolable),
            source=str(item.source or "").strip(),
        )
    if not isinstance(item, dict):
        return None
    address = item.get("address") or item.get("proxy") or item.get("host")
    if address and item.get("port") and isinstance(address, str) and ":" not in address:
        address = f"{address}:{item.get('port')}"
    normalized = _normalize_proxy_address(str(address or ""))
    if not normalized:
        return None
    expire_at = str(item.get("expire_at") or "").strip()
    expire_ts = float(item.get("expire_ts") or 0.0)
    return ProxyLease(
        address=normalized,
        expire_at=expire_at,
        expire_ts=expire_ts,
        poolable=bool(item.get("poolable", True)),
        source=str(item.get("source") or "").strip(),
    )


class ProxySidecarClient:
    def __init__(self, base_url: str):
        self.base_url = str(base_url or "").rstrip("/")

    def _url(self, path: str) -> str:
        normalized = "/" + str(path or "").lstrip("/")
        return f"{self.base_url}{normalized}"

    def _request(self, method: str, path: str, *, json_payload: Optional[Dict[str, Any]] = None) -> Any:
        try:
            response = http_client.request(
                method,
                self._url(path),
                json=json_payload,
                timeout=10,
                proxies={},
            )
        except Exception as exc:
            raise ProxySidecarError(f"代理服务连接失败：{exc}") from exc
        if int(getattr(response, "status_code", 0) or 0) >= 400:
            raise ProxySidecarError(_coerce_error_message(response, f"HTTP {response.status_code}"))
        return response

    def apply_config(self, settings: ProxySettings) -> Dict[str, Any]:
        payload = {
            "source": str(settings.source or ""),
            "custom_api_url": str(settings.custom_api_url or ""),
            "area_code": str(settings.area_code or ""),
            "occupy_minute": int(settings.occupy_minute or 1),
        }
        return self._request("POST", "/config/apply", json_payload=payload).json()

    def prefetch(self, expected_count: int) -> Dict[str, Any]:
        return self._request(
            "POST",
            "/pool/prefetch",
            json_payload={"expected_count": max(1, int(expected_count or 1))},
        ).json()

    def acquire_lease(self, *, thread_name: str, wait: bool) -> Optional[ProxyLease]:
        payload = {
            "thread_name": str(thread_name or ""),
            "wait": bool(wait),
        }
        response = self._request("POST", "/lease/acquire", json_payload=payload).json()
        if not isinstance(response, dict):
            return None
        return _coerce_proxy_lease(response.get("lease"))

    def release_lease(self, *, thread_name: str, requeue: bool) -> Optional[ProxyLease]:
        payload = {
            "thread_name": str(thread_name or ""),
            "requeue": bool(requeue),
        }
        response = self._request("POST", "/lease/release", json_payload=payload).json()
        if not isinstance(response, dict):
            return None
        return _coerce_proxy_lease(response.get("lease"))

    def mark_success(self, *, thread_name: str, proxy_address: str) -> Dict[str, Any]:
        payload = {
            "thread_name": str(thread_name or ""),
            "proxy_address": str(proxy_address or ""),
        }
        return self._request("POST", "/lease/mark-success", json_payload=payload).json()

    def mark_bad(self, *, thread_name: str, proxy_address: str, cooldown_seconds: float) -> Dict[str, Any]:
        payload = {
            "thread_name": str(thread_name or ""),
            "proxy_address": str(proxy_address or ""),
            "cooldown_seconds": float(cooldown_seconds or 0.0),
        }
        return self._request("POST", "/lease/mark-bad", json_payload=payload).json()

    def check_health(self, proxy_address: str, *, skip_for_official: bool = True) -> bool:
        payload = {
            "proxy_address": str(proxy_address or ""),
            "skip_for_official": bool(skip_for_official),
        }
        response = self._request("POST", "/health/check", json_payload=payload).json()
        return bool(isinstance(response, dict) and response.get("responsive"))

    def status(self) -> Dict[str, Any]:
        return self._request("GET", "/status").json()


__all__ = [
    "ProxySidecarClient",
    "ProxySidecarError",
]
