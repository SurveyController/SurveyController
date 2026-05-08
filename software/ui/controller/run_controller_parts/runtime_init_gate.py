"""RunController 启动提示与运行前状态辅助逻辑。"""
from __future__ import annotations

import copy
import logging
import threading
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from software.app.config import DEFAULT_HTTP_HEADERS
from software.core.task import ExecutionConfig, ExecutionState, ProxyLease
from software.integrations.ai.client import AI_MODE_FREE, get_ai_settings
from software.io.config import RuntimeConfig
import software.network.http as http_client
from software.network.proxy.pool import prefetch_proxy_pool
from software.network.proxy.pool.free_pool import FREE_POOL_DEFAULT_PROBE_TIMEOUT_MS, FREE_POOL_DEFAULT_TARGET_COUNT
from software.network.proxy.policy.source import (
    PROXY_SOURCE_FREE_POOL,
    PROXY_SOURCE_IPLIST,
    normalize_proxy_source,
)
from .runtime_preparation import PreparedExecutionArtifacts

from .runtime_constants import (
    STARTUP_HINT_DURATION_MS,
    STARTUP_STATUS_TIMEOUT_SECONDS,
    STATUS_MONITOR_FREE_AI,
    STATUS_MONITOR_RANDOM_IP,
    STATUS_PAGE_BASE_URL,
    STATUS_PAGE_SLUG,
)


def _parse_status_page_monitor_names(payload: Dict[str, Any]) -> Dict[int, str]:
    names: Dict[int, str] = {}
    for group in list(payload.get("publicGroupList") or []):
        monitor_list = group.get("monitorList") or []
        if not isinstance(monitor_list, list):
            continue
        for monitor in monitor_list:
            try:
                monitor_id = int(monitor.get("id"))
            except Exception:
                continue
            monitor_name = str(monitor.get("name") or "").strip()
            if monitor_name:
                names[monitor_id] = monitor_name
    return names


def _extract_startup_service_warnings(
    heartbeat_payload: Dict[str, Any],
    monitor_targets: Dict[int, str],
    monitor_names: Optional[Dict[int, str]] = None,
) -> List[str]:
    warnings: List[str] = []
    heartbeat_map = heartbeat_payload.get("heartbeatList") or {}
    names = dict(monitor_names or {})

    for monitor_id, fallback_name in monitor_targets.items():
        heartbeat_list = heartbeat_map.get(str(monitor_id)) or heartbeat_map.get(monitor_id) or []
        latest = heartbeat_list[-1] if isinstance(heartbeat_list, list) and heartbeat_list else {}
        try:
            raw_status = latest.get("status")
            status = int(0 if raw_status is None else raw_status)
        except Exception:
            status = 0
        if status == 1:
            continue
        service_name = str(names.get(int(monitor_id)) or fallback_name or f"服务 {monitor_id}").strip()
        detail = str(latest.get("msg") or "").strip()
        time_text = str(latest.get("time") or "").strip()
        suffix_parts: List[str] = []
        if detail:
            suffix_parts.append(detail)
        if time_text:
            suffix_parts.append(f"最近时间：{time_text}")
        suffix = f"（{'；'.join(suffix_parts)}）" if suffix_parts else ""
        warnings.append(f"{service_name} 当前状态异常{suffix}")
    return warnings


class RunControllerInitializationMixin:
    if TYPE_CHECKING:
        stop_event: threading.Event
        worker_threads: List[threading.Thread]
        adapter: Any
        config: RuntimeConfig
        running: bool
        _status_timer: Any
        _execution_state: Optional[ExecutionState]
        _init_gate_thread: Optional[threading.Thread]
        _startup_status_check_lock: threading.Lock
        _startup_status_check_active: bool
        survey_title: str
        runStateChanged: Any
        statusUpdated: Any
        threadProgressUpdated: Any
        startupHintEmitted: Any

        @property
        def _starting(self) -> bool: ...
        @_starting.setter
        def _starting(self, value: bool) -> None: ...

        @property
        def _initializing(self) -> bool: ...
        @_initializing.setter
        def _initializing(self, value: bool) -> None: ...

        @property
        def _prepared_execution_artifacts(self) -> Optional[PreparedExecutionArtifacts]: ...
        @_prepared_execution_artifacts.setter
        def _prepared_execution_artifacts(self, value: Optional[PreparedExecutionArtifacts]) -> None: ...

        @property
        def _init_stage_text(self) -> str: ...
        @_init_stage_text.setter
        def _init_stage_text(self, value: str) -> None: ...

        @property
        def _init_steps(self) -> List[Dict[str, str]]: ...
        @_init_steps.setter
        def _init_steps(self, value: List[Dict[str, str]]) -> None: ...

        @property
        def _init_completed_steps(self) -> set[str]: ...
        @_init_completed_steps.setter
        def _init_completed_steps(self, value: set[str]) -> None: ...

        @property
        def _init_current_step_key(self) -> str: ...
        @_init_current_step_key.setter
        def _init_current_step_key(self, value: str) -> None: ...

        @property
        def _init_gate_stop_event(self) -> Optional[threading.Event]: ...
        @_init_gate_stop_event.setter
        def _init_gate_stop_event(self, value: Optional[threading.Event]) -> None: ...

        @property
        def _startup_service_warnings(self) -> List[str]: ...
        @_startup_service_warnings.setter
        def _startup_service_warnings(self, value: List[str]) -> None: ...
        @property
        def _free_proxy_pool(self) -> List[ProxyLease]: ...
        @_free_proxy_pool.setter
        def _free_proxy_pool(self, value: List[ProxyLease]) -> None: ...

        def _start_workers_with_proxy_pool(
            self,
            config: RuntimeConfig,
            proxy_pool: List[ProxyLease],
            *,
            emit_run_state: bool = True,
        ) -> None: ...
        def _emit_status(self) -> None: ...

    def _prepare_engine_state(self, proxy_pool: List[ProxyLease]) -> tuple[ExecutionConfig, ExecutionState]:
        """从已准备好的模板构建本次任务的 ExecutionConfig 与 ExecutionState。"""
        prepared = getattr(self, "_prepared_execution_artifacts", None)
        if prepared is None:
            raise RuntimeError("运行准备产物缺失，无法启动任务")
        execution_config = copy.deepcopy(prepared.execution_config_template)
        execution_config.proxy_ip_pool = list(proxy_pool) if execution_config.random_proxy_ip_enabled else []
        execution_state = ExecutionState(config=execution_config, stop_event=self.stop_event)
        return execution_config, execution_state

    def _build_initialization_logs(self) -> List[str]:
        steps = list(getattr(self, "_init_steps", []) or [])
        if not steps:
            return [str(getattr(self, "_init_stage_text", "") or "正在初始化")]

        completed = set(getattr(self, "_init_completed_steps", set()) or set())
        current = str(getattr(self, "_init_current_step_key", "") or "")
        lines: List[str] = []
        stage_text = str(getattr(self, "_init_stage_text", "") or "").strip()
        if stage_text:
            lines.append(f"当前阶段：{stage_text}")
        for item in steps:
            key = str(item.get("key") or "").strip()
            label = str(item.get("label") or key).strip() or key
            if key in completed:
                lines.append(f"[√] {label}")
            elif key and key == current:
                lines.append(f"[>] {label}")
        return lines

    def _start_startup_status_check(self, config: RuntimeConfig) -> None:
        monitor_targets = self._resolve_startup_status_targets(config)
        with self._startup_status_check_lock:
            self._startup_service_warnings = []
            if not monitor_targets:
                self._startup_status_check_active = False
                return
            if self._startup_status_check_active:
                return
            self._startup_status_check_active = True

        threading.Thread(
            target=self._run_startup_status_check,
            args=(monitor_targets,),
            daemon=True,
            name="StartupStatusHint",
        ).start()

    def _resolve_startup_status_targets(self, config: RuntimeConfig) -> Dict[int, str]:
        targets: Dict[int, str] = {}
        if bool(getattr(config, "random_ip_enabled", False)):
            targets[STATUS_MONITOR_RANDOM_IP] = "随机IP提取"
        try:
            ai_mode = str(get_ai_settings().get("ai_mode") or "").strip().lower()
        except Exception:
            ai_mode = ""
        if ai_mode == AI_MODE_FREE:
            targets[STATUS_MONITOR_FREE_AI] = "免费AI填空"
        return targets

    def _run_startup_status_check(self, monitor_targets: Dict[int, str]) -> None:
        warnings: List[str] = []
        try:
            warnings = self._fetch_startup_service_warnings(monitor_targets)
        except Exception:
            logging.info("启动服务提示检查失败，已忽略", exc_info=True)
        finally:
            with self._startup_status_check_lock:
                self._startup_service_warnings = list(warnings)
                self._startup_status_check_active = False

        for warning in warnings:
            self.startupHintEmitted.emit(str(warning), "warning", int(STARTUP_HINT_DURATION_MS))

    def _fetch_startup_service_warnings(self, monitor_targets: Dict[int, str]) -> List[str]:
        page_url = f"{STATUS_PAGE_BASE_URL}/api/status-page/{STATUS_PAGE_SLUG}"
        heartbeat_url = f"{STATUS_PAGE_BASE_URL}/api/status-page/heartbeat/{STATUS_PAGE_SLUG}"
        monitor_names: Dict[int, str] = {}
        try:
            response = http_client.get(
                page_url,
                timeout=STARTUP_STATUS_TIMEOUT_SECONDS,
                headers=DEFAULT_HTTP_HEADERS,
                proxies={},
            )
            monitor_names = _parse_status_page_monitor_names(response.json())
        except Exception:
            logging.info("读取状态页配置失败，启动时忽略服务提示", exc_info=True)

        try:
            response = http_client.get(
                heartbeat_url,
                timeout=STARTUP_STATUS_TIMEOUT_SECONDS,
                headers=DEFAULT_HTTP_HEADERS,
                proxies={},
            )
            return _extract_startup_service_warnings(response.json(), monitor_targets, monitor_names)
        except Exception:
            logging.info("读取状态页心跳失败，启动时忽略服务提示", exc_info=True)
            return []

    def _snapshot_startup_service_warnings(self) -> List[str]:
        with self._startup_status_check_lock:
            return list(self._startup_service_warnings or [])

    def _initial_proxy_pool_target_count(self, config: RuntimeConfig) -> int:
        target = max(1, int(getattr(config, "target", 1) or 1))
        threads = max(1, int(getattr(config, "threads", 1) or 1))
        source = normalize_proxy_source(getattr(config, "proxy_source", "default"))
        if source in {PROXY_SOURCE_FREE_POOL, PROXY_SOURCE_IPLIST}:
            return max(1, min(target, max(threads * 4, threads + 12), FREE_POOL_DEFAULT_TARGET_COUNT))
        return max(1, min(threads, target, 16))

    def _prefetch_initial_proxy_pool(
        self,
        config: RuntimeConfig,
        stop_signal: threading.Event,
    ) -> List[ProxyLease]:
        if not bool(getattr(config, "random_ip_enabled", False)):
            return []
        source = normalize_proxy_source(getattr(config, "proxy_source", "default"))
        if source == PROXY_SOURCE_FREE_POOL:
            warmed = list(getattr(self, "_free_proxy_pool", []) or [])
            if warmed:
                logging.info("复用已构建公共免费代理池: count=%s", len(warmed))
                self._free_proxy_pool = []
                return warmed
        expected_count = self._initial_proxy_pool_target_count(config)
        kwargs = dict(
            expected_count=expected_count,
            proxy_api_url=str(getattr(config, "custom_proxy_api", "") or "").strip() or None,
            stop_signal=stop_signal,
            max_workers=200 if source == PROXY_SOURCE_FREE_POOL else None,
            force_refresh=False,
            target_url=str(getattr(config, "url", "") or ""),
        )
        if source == PROXY_SOURCE_FREE_POOL:
            kwargs["probe_timeout_ms"] = max(
                1,
                int(
                    getattr(
                        config,
                        "free_proxy_pool_probe_timeout_ms",
                        FREE_POOL_DEFAULT_PROBE_TIMEOUT_MS,
                    )
                    or FREE_POOL_DEFAULT_PROBE_TIMEOUT_MS
                ),
            )
        return prefetch_proxy_pool(**kwargs)

    def _run_initialization_gate(self, config: RuntimeConfig, proxy_pool: List[ProxyLease]) -> None:
        stop_signal = self._init_gate_stop_event or threading.Event()
        warmed_pool = list(proxy_pool or [])
        try:
            if bool(getattr(config, "random_ip_enabled", False)) and not warmed_pool:
                self._initializing = True
                self._init_current_step_key = "proxy_pool"
                self._init_stage_text = "正在构建代理池"
                self._dispatch_to_ui_async(self._emit_status)
                warmed_pool = self._prefetch_initial_proxy_pool(config, stop_signal)
                if stop_signal.is_set() or self.stop_event.is_set():
                    self._dispatch_to_ui_async(self._cancel_initialization_startup)
                    return
                self._init_completed_steps = set(self._init_completed_steps) | {"proxy_pool"}
                self._init_stage_text = "代理池已就绪"
                self._dispatch_to_ui_async(self._emit_status)
            self._reset_initialization_state()
            if stop_signal.is_set() or self.stop_event.is_set():
                self._dispatch_to_ui_async(self._cancel_initialization_startup)
                return
            self._dispatch_to_ui_async(lambda: self._start_workers_with_proxy_pool(config, warmed_pool))
        except Exception as exc:
            logging.warning("启动前代理池构建失败: %s", exc)
            message = f"代理池构建失败：{exc}"
            self._dispatch_to_ui_async(lambda _message=message: self._finish_initialization_idle_state(_message))
        finally:
            self._init_gate_thread = None

    def _start_with_initialization_gate(self, config: RuntimeConfig, proxy_pool: List[ProxyLease]) -> None:
        if self.stop_event.is_set():
            self._starting = False
            return
        if bool(getattr(config, "random_ip_enabled", False)) and not list(proxy_pool or []):
            if not hasattr(self, "_dispatch_to_ui_async"):
                warmed_pool = self._prefetch_initial_proxy_pool(config, self.stop_event)
                if self.stop_event.is_set():
                    self._starting = False
                    return
                self._start_workers_with_proxy_pool(config, warmed_pool)
                return
            stop_signal = threading.Event()
            self._init_gate_stop_event = stop_signal
            self._initializing = True
            self._init_stage_text = "正在构建代理池"
            self._init_steps = [{"key": "proxy_pool", "label": "并发筛选可用代理"}]
            self._init_completed_steps = set()
            self._init_current_step_key = "proxy_pool"
            self._emit_status()
            thread = threading.Thread(
                target=self._run_initialization_gate,
                args=(config, list(proxy_pool)),
                daemon=True,
                name="ProxyPoolInitGate",
            )
            self._init_gate_thread = thread
            thread.start()
            return
        self._start_workers_with_proxy_pool(config, list(proxy_pool))

    def _reset_initialization_state(self) -> None:
        self._initializing = False
        self._init_stage_text = ""
        self._init_steps = []
        self._init_completed_steps = set()
        self._init_current_step_key = ""
        self._init_gate_stop_event = None

    def _finish_initialization_idle_state(self, status_text: str) -> None:
        was_running = bool(self.running)
        self._reset_initialization_state()
        self._starting = False
        self._status_timer.stop()
        self.running = False
        self.worker_threads = []
        self._execution_state = None
        self._prepared_execution_artifacts = None
        if was_running:
            self.runStateChanged.emit(False)
        self.statusUpdated.emit(str(status_text or "已停止"), 0, 0)
        self.threadProgressUpdated.emit(
            {
                "threads": [],
                "target": 0,
                "num_threads": 0,
                "per_thread_target": 0,
                "initializing": False,
            }
        )

    def _cancel_initialization_startup(self) -> None:
        self._finish_initialization_idle_state("已取消启动")
