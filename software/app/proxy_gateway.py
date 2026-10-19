from __future__ import annotations

from typing import Any

from software.application.errors import ProxyAuthenticationError
from software.application.ports import ProxyGatewayPort
from software.network.proxy import is_custom_proxy_api_active
from software.network.proxy.policy.source import get_random_ip_counter_snapshot_local
from software.network.proxy.session import (
    RandomIPAuthError,
    activate_trial_async,
    format_random_ip_error,
    get_fresh_quota_snapshot,
    get_quota_snapshot,
    get_session_snapshot,
    has_authenticated_session,
    is_quota_exhausted,
    load_session_for_startup,
    sync_quota_snapshot_from_server_async,
)


def _raise_port_error(error: RandomIPAuthError) -> ProxyAuthenticationError:
    return ProxyAuthenticationError(
        error.detail,
        status_code=error.status_code,
        retry_after_seconds=error.retry_after_seconds,
    )


class PythonProxyGateway(ProxyGatewayPort):
    def is_custom_api_active(self) -> bool:
        return is_custom_proxy_api_active()

    def has_authenticated_session(self) -> bool:
        return has_authenticated_session()

    def get_fresh_quota_snapshot(self) -> dict[str, Any]:
        try:
            return get_fresh_quota_snapshot()
        except RandomIPAuthError as exc:
            raise _raise_port_error(exc) from exc

    def get_quota_snapshot(self) -> dict[str, Any]:
        try:
            return get_quota_snapshot()
        except RandomIPAuthError as exc:
            raise _raise_port_error(exc) from exc

    def get_counter_snapshot_local(self) -> tuple[float, float, bool]:
        try:
            return get_random_ip_counter_snapshot_local()
        except RandomIPAuthError as exc:
            raise _raise_port_error(exc) from exc

    def load_session_for_startup(self) -> None:
        try:
            load_session_for_startup()
        except RandomIPAuthError as exc:
            raise _raise_port_error(exc) from exc

    async def sync_quota_snapshot(self, *, emit_logs: bool = True) -> dict[str, Any]:
        try:
            return await sync_quota_snapshot_from_server_async(emit_logs=emit_logs)
        except RandomIPAuthError as exc:
            raise _raise_port_error(exc) from exc

    async def activate_trial(self) -> Any:
        try:
            return await activate_trial_async()
        except RandomIPAuthError as exc:
            raise _raise_port_error(exc) from exc

    def is_quota_exhausted(self, snapshot: dict[str, Any]) -> bool:
        return is_quota_exhausted(snapshot)

    def get_session_snapshot(self) -> dict[str, Any]:
        return get_session_snapshot()

    def format_error(self, error: Exception) -> str:
        if isinstance(error, ProxyAuthenticationError):
            error = RandomIPAuthError(
                error.detail,
                status_code=error.status_code,
                retry_after_seconds=error.retry_after_seconds,
            )
        return format_random_ip_error(error)


__all__ = ["PythonProxyGateway"]
