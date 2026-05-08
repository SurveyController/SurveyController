"""RunController 的内部状态容器。"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

from software.io.config import RuntimeConfig
from software.network.proxy.pool.free_pool import FREE_POOL_DEFAULT_PROBE_TIMEOUT_MS


@dataclass
class RunControllerRuntimeState:
    """收口运行控制器里零散的生命周期状态。"""

    paused: bool = False
    stopping: bool = False
    completion_cleanup_done: bool = False
    cleanup_scheduled: bool = False
    stopped_by_stop_run: bool = False
    quick_feedback_prompt_emitted: bool = False
    starting: bool = False
    initializing: bool = False
    init_stage_text: str = ""
    init_steps: List[Dict[str, str]] = field(default_factory=list)
    init_completed_steps: Set[str] = field(default_factory=set)
    init_current_step_key: str = ""
    init_gate_stop_event: Optional[Any] = None
    prepared_execution_artifacts: Optional[Any] = None
    startup_service_warnings: List[str] = field(default_factory=list)
    free_proxy_pool: List[Any] = field(default_factory=list)
    free_proxy_pool_built_at: float = 0.0
    free_proxy_pool_build_active: bool = False
    free_proxy_pool_stop_event: Optional[Any] = None


class RuntimeUiStateStore:
    """集中管理运行参数页同步到控制器的 UI 状态。"""

    def __init__(self) -> None:
        self._state: Dict[str, Any] = {}

    @staticmethod
    def normalize_value(key: str, value: Any) -> Any:
        if key in {"target", "threads"}:
            return max(1, int(value or 1))
        if key in {"random_ip_enabled", "headless_mode", "timed_mode_enabled"}:
            return bool(value)
        if key == "proxy_source":
            normalized = str(value or "default").strip().lower()
            return normalized if normalized in {"default", "benefit", "custom", "free_pool", "iplist"} else "default"
        if key == "free_proxy_pool_probe_timeout_ms":
            try:
                return max(1, int(value or FREE_POOL_DEFAULT_PROBE_TIMEOUT_MS))
            except Exception:
                return FREE_POOL_DEFAULT_PROBE_TIMEOUT_MS
        if key == "answer_duration":
            raw = value if isinstance(value, (list, tuple)) else (0, 0)
            low = max(0, int(raw[0] if len(raw) >= 1 else 0))
            high = max(low, int(raw[1] if len(raw) >= 2 else low))
            return (low, high)
        return value

    def get(self) -> Dict[str, Any]:
        return dict(self._state)

    def update(self, **updates: Any) -> tuple[Dict[str, Any], bool]:
        normalized: Dict[str, Any] = {}
        changed = False
        for key, value in updates.items():
            normalized_value = self.normalize_value(key, value)
            normalized[key] = normalized_value
            if self._state.get(key) != normalized_value:
                changed = True
        if normalized:
            self._state.update(normalized)
        return dict(self._state), changed

    def sync_from_config(self, config: RuntimeConfig) -> tuple[Dict[str, Any], bool]:
        return self.update(
            target=getattr(config, "target", 1),
            threads=getattr(config, "threads", 1),
            random_ip_enabled=getattr(config, "random_ip_enabled", False),
            headless_mode=getattr(config, "headless_mode", True),
            timed_mode_enabled=getattr(config, "timed_mode_enabled", False),
            proxy_source=getattr(config, "proxy_source", "default"),
            free_proxy_pool_probe_timeout_ms=getattr(config, "free_proxy_pool_probe_timeout_ms", FREE_POOL_DEFAULT_PROBE_TIMEOUT_MS),
            answer_duration=getattr(config, "answer_duration", (0, 0)),
        )
