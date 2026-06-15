from __future__ import annotations

from typing import Callable, Optional

from software.core.engine.runtime_ui_bridge import RuntimeUiBridge
from software.core.engine.stop_signal import StopSignalLike
from software.core.task import ExecutionConfig, ExecutionState
from software.network.session_policy import (
    _select_user_agent_for_session,
)


class AsyncProxySession:
    

    def __init__(
        self,
        *,
        config: ExecutionConfig,
        state: ExecutionState,
        slot_label: str,
        stop_signal: StopSignalLike,
        runtime_bridge: RuntimeUiBridge | None,
        update_step: Callable[[str], None],
    ) -> None:
        self.config = config
        self.state = state
        self.slot_label = slot_label
        self.stop_signal = stop_signal
        self.runtime_bridge = runtime_bridge
        self.update_step = update_step
        self.proxy_address: Optional[str] = None
        self.proxy_provider: str = "unknown"

    async def select_user_agent(self) -> Optional[str]:
        ua_value, _ = _select_user_agent_for_session(self.state)
        return ua_value

    async def select_proxy_and_user_agent(self) -> tuple[Optional[str], Optional[str]]:
        ua_value = await self.select_user_agent()
        return None, ua_value

    def set_current_submit_proxy(self, proxy_address: str | None, *, provider: str = "unknown") -> None:
        self.proxy_address = str(proxy_address or "").strip() or None
        self.proxy_provider = str(provider or "unknown").strip() or "unknown"

    def clear_current_submit_proxy(self) -> None:
        self.proxy_address = None
        self.proxy_provider = "unknown"

    def mark_successful_proxy(self) -> None:
        return None

    def release_current_proxy(self) -> None:
        self.clear_current_submit_proxy()


__all__ = ["AsyncProxySession"]
