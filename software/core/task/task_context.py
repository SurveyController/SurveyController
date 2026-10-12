from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Any, cast

from surveycore.core.task import (
    ExecutionConfig as CoreExecutionConfig,
    ExecutionState as CoreExecutionState,
)
from surveycore.core.task.progress_state import ThreadProgressState

from software.core.task.proxy_state import ProxyLease, ProxyRuntimeMixin

__all__ = ["ExecutionConfig", "ExecutionState", "ProxyLease", "ThreadProgressState"]


@dataclass
class ExecutionConfig(CoreExecutionConfig):
    """核心配置增加桌面应用管理的代理租约。"""

    random_proxy_ip_enabled: bool = False
    proxy_source: str = "default"
    proxy_ip_pool: list[ProxyLease] | deque[ProxyLease] = field(default_factory=deque)

    def __post_init__(self) -> None:
        self.ai_mode = "provider"


@dataclass
class ExecutionState(ProxyRuntimeMixin, CoreExecutionState):
    """共享核心样本状态，保留应用代理池及异步唤醒语义。"""

    config: CoreExecutionConfig = field(default_factory=ExecutionConfig)
    device_quota_fail_count: int = 0
    proxy_waiting_threads: int = 0
    proxy_in_use_by_thread: dict[str, ProxyLease] = field(default_factory=dict)
    successful_proxy_addresses: set[str] = field(default_factory=set)
    proxy_cooldown_until_by_address: dict[str, float] = field(default_factory=dict)
    _runtime_async_event: Any = field(default=None, init=False, repr=False)
    _runtime_async_event_loop: Any = field(default=None, init=False, repr=False)

    # 锁定核心库仍使用旧缓存名；复用其锁与线程隔离，不接入免费服务。
    set_ai_prefill_answers = CoreExecutionState.set_free_ai_prefill_answers
    get_ai_prefill_answer = CoreExecutionState.get_free_ai_prefill_answer
    clear_ai_prefill_answers = CoreExecutionState.clear_free_ai_prefill_answers
    set_ai_option_fill_prefill_answers = CoreExecutionState.set_free_ai_option_fill_prefill_answers
    get_ai_option_fill_prefill_answer = CoreExecutionState.get_free_ai_option_fill_prefill_answer

    @property
    def app_config(self) -> ExecutionConfig:
        return cast(ExecutionConfig, self.config)

    def __setattr__(self, name: str, value: object) -> None:
        if name in _EXECUTION_STATE_FIELD_NAMES:
            object.__setattr__(self, name, value)
            return
        if name in _EXECUTION_CONFIG_FIELD_NAMES:
            raise AttributeError(
                f"ExecutionState 不允许直接设置配置字段 '{name}'，请改用 state.config.{name}"
            )
        object.__setattr__(self, name, value)


_EXECUTION_CONFIG_FIELD_NAMES = frozenset(ExecutionConfig.__dataclass_fields__)
_EXECUTION_STATE_FIELD_NAMES = frozenset(ExecutionState.__dataclass_fields__)
