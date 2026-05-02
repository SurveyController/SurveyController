"""任务模型 - 静态执行配置与运行态状态。"""

from __future__ import annotations

import time
import threading
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple, Union

from software.providers.contracts import SurveyQuestionMeta
from software.core.reverse_fill import (
    ReverseFillAcquireResult,
    ReverseFillAnswer,
    ReverseFillRuntimeState,
    ReverseFillSpec,
    create_reverse_fill_runtime_state,
)

@dataclass
class ThreadProgressState:
    """单个工作线程的运行状态快照。"""

    thread_name: str
    thread_index: int = 0
    owner_id: int = 0
    success_count: int = 0
    fail_count: int = 0
    step_current: int = 0
    step_total: int = 0
    status_text: str = "等待中"
    running: bool = False
    last_update_ts: float = 0.0


@dataclass
class ProxyLease:
    """代理租约对象，保存地址与过期时间信息。"""

    address: str = ""
    expire_at: str = ""
    expire_ts: float = 0.0
    poolable: bool = True
    source: str = ""


@dataclass
class ExecutionConfig:
    """一次任务在启动前固定下来的静态执行配置。"""

    url: str = ""
    survey_title: str = ""
    survey_provider: str = "wjx"

    single_prob: List[Union[List[float], int, float, None]] = field(default_factory=list)
    droplist_prob: List[Union[List[float], int, float, None]] = field(default_factory=list)
    multiple_prob: List[List[float]] = field(default_factory=list)
    matrix_prob: List[Union[List[float], int, float, None]] = field(default_factory=list)
    scale_prob: List[Union[List[float], int, float, None]] = field(default_factory=list)
    slider_targets: List[float] = field(default_factory=list)
    texts: List[List[str]] = field(default_factory=list)
    texts_prob: List[List[float]] = field(default_factory=list)
    text_entry_types: List[str] = field(default_factory=list)
    text_ai_flags: List[bool] = field(default_factory=list)
    text_titles: List[str] = field(default_factory=list)
    multi_text_blank_modes: List[List[str]] = field(default_factory=list)
    multi_text_blank_ai_flags: List[List[bool]] = field(default_factory=list)
    multi_text_blank_int_ranges: List[List[List[int]]] = field(default_factory=list)
    single_option_fill_texts: List[Optional[List[Optional[str]]]] = field(default_factory=list)
    single_attached_option_selects: List[List[Dict[str, Any]]] = field(default_factory=list)
    droplist_option_fill_texts: List[Optional[List[Optional[str]]]] = field(default_factory=list)
    multiple_option_fill_texts: List[Optional[List[Optional[str]]]] = field(default_factory=list)
    answer_rules: List[Dict[str, Any]] = field(default_factory=list)
    reverse_fill_spec: Optional[ReverseFillSpec] = None

    question_config_index_map: Dict[int, Tuple[str, int]] = field(default_factory=dict)
    question_dimension_map: Dict[int, Optional[str]] = field(default_factory=dict)
    question_strict_ratio_map: Dict[int, bool] = field(default_factory=dict)
    question_psycho_bias_map: Dict[int, Any] = field(default_factory=dict)
    questions_metadata: Dict[int, SurveyQuestionMeta] = field(default_factory=dict)
    joint_psychometric_answer_plan: Optional[Any] = None

    psycho_target_alpha: float = 0.9

    headless_mode: bool = False
    browser_preference: List[str] = field(default_factory=list)
    num_threads: int = 1
    target_num: int = 1
    fail_threshold: int = 5
    stop_on_fail_enabled: bool = True

    submit_interval_range_seconds: Tuple[int, int] = (0, 0)
    answer_duration_range_seconds: Tuple[int, int] = (0, 0)

    timed_mode_enabled: bool = False
    timed_mode_refresh_interval: float = 0.5

    random_proxy_ip_enabled: bool = False
    proxy_ip_pool: List[ProxyLease] = field(default_factory=list)
    random_user_agent_enabled: bool = False
    user_agent_ratios: Dict[str, int] = field(
        default_factory=lambda: {"wechat": 33, "mobile": 33, "pc": 34}
    )
    pause_on_aliyun_captcha: bool = True


@dataclass
class ExecutionState:
    """一次任务运行中的动态状态。"""

    config: ExecutionConfig = field(default_factory=ExecutionConfig)

    cur_num: int = 0
    cur_fail: int = 0
    device_quota_fail_count: int = 0
    terminal_stop_category: str = ""
    terminal_failure_reason: str = ""
    terminal_stop_message: str = ""
    thread_progress: Dict[str, ThreadProgressState] = field(default_factory=dict)
    distribution_runtime_stats: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    distribution_pending_by_thread: Dict[str, List[Tuple[str, int, int]]] = field(default_factory=dict)
    joint_reserved_sample_by_thread: Dict[str, int] = field(default_factory=dict)
    joint_committed_sample_indexes: set[int] = field(default_factory=set)

    proxy_waiting_threads: int = 0
    proxy_in_use_by_thread: Dict[str, ProxyLease] = field(default_factory=dict)
    submit_proxy_in_use_by_thread: Dict[str, ProxyLease] = field(default_factory=dict)
    proxy_cooldown_until_by_address: Dict[str, float] = field(default_factory=dict)
    reverse_fill_runtime: Optional[ReverseFillRuntimeState] = None

    stop_event: threading.Event = field(default_factory=threading.Event)
    lock: threading.Lock = field(default_factory=threading.Lock)

    _aliyun_captcha_stop_triggered: bool = False
    _aliyun_captcha_stop_lock: threading.Lock = field(default_factory=threading.Lock)
    _aliyun_captcha_popup_shown: bool = False
    _target_reached_stop_triggered: bool = False
    _target_reached_stop_lock: threading.Lock = field(default_factory=threading.Lock)
    _terminal_stop_lock: threading.Lock = field(default_factory=threading.Lock)
    _runtime_condition: threading.Condition = field(default_factory=threading.Condition, repr=False)

    _proxy_fetch_lock: threading.Lock = field(default_factory=threading.Lock)
    _browser_semaphore: Optional[threading.Semaphore] = field(default=None, repr=False)
    _browser_semaphore_lock: threading.Lock = field(default_factory=threading.Lock)
    _browser_semaphore_max_instances: int = 0

    def __setattr__(self, name: str, value: Any) -> None:
        """阻止把静态配置字段误写到运行态对象本身。"""
        if name in _EXECUTION_STATE_FIELD_NAMES:
            object.__setattr__(self, name, value)
            return
        if name in _EXECUTION_CONFIG_FIELD_NAMES:
            raise AttributeError(f"ExecutionState 不允许直接设置配置字段 '{name}'，请改用 state.config.{name}")
        object.__setattr__(self, name, value)

    def get_browser_semaphore(self, max_instances: int) -> threading.Semaphore:
        normalized = max(1, int(max_instances or 1))
        with self._browser_semaphore_lock:
            if self._browser_semaphore is None or self._browser_semaphore_max_instances != normalized:
                self._browser_semaphore = threading.Semaphore(normalized)
                self._browser_semaphore_max_instances = normalized
            return self._browser_semaphore

    @staticmethod
    def _resolve_thread_index(thread_name: str) -> int:
        text = str(thread_name or "").strip()
        if not text:
            return 0
        for prefix in ("Worker-", "Slot-"):
            if not text.startswith(prefix):
                continue
            suffix = text.split("-", 1)[1].strip()
            try:
                value = int(suffix)
                return value if value > 0 else 0
            except Exception:
                return 0
        tail = []
        for ch in reversed(text):
            if ch.isdigit():
                tail.append(ch)
            else:
                break
        if not tail:
            return 0
        try:
            return int("".join(reversed(tail)))
        except Exception:
            return 0

    @staticmethod
    def _format_thread_display_name(thread_name: str, thread_index: int) -> str:
        if thread_index > 0:
            text = str(thread_name or "").strip()
            if text.startswith("Slot-"):
                return f"会话 {thread_index}"
            return f"线程 {thread_index}"
        text = str(thread_name or "").strip()
        if text.startswith("Worker-?"):
            return "线程 ?"
        if text.startswith("Slot-?"):
            return "会话 ?"
        return text or "线程 ?"

    def _get_or_create_thread_state_locked(self, thread_name: str) -> ThreadProgressState:
        key = str(thread_name or "").strip() or "Worker-?"
        state = self.thread_progress.get(key)
        if state is not None:
            return state
        state = ThreadProgressState(
            thread_name=key,
            thread_index=self._resolve_thread_index(key),
            last_update_ts=time.time(),
        )
        self.thread_progress[key] = state
        return state

    def ensure_worker_threads(self, expected_count: int, *, prefix: str = "Worker") -> None:
        count = max(1, int(expected_count or 1))
        now = time.time()
        normalized_prefix = str(prefix or "Worker").strip() or "Worker"
        with self.lock:
            for idx in range(1, count + 1):
                name = f"{normalized_prefix}-{idx}"
                state = self.thread_progress.get(name)
                if state is None:
                    self.thread_progress[name] = ThreadProgressState(
                        thread_name=name,
                        thread_index=idx,
                        last_update_ts=now,
                    )
                else:
                    state.thread_index = idx
                    state.last_update_ts = now

    def register_proxy_waiter(self) -> None:
        with self.lock:
            self.proxy_waiting_threads = max(0, int(self.proxy_waiting_threads or 0)) + 1

    def unregister_proxy_waiter(self) -> None:
        with self.lock:
            self.proxy_waiting_threads = max(0, int(self.proxy_waiting_threads or 0) - 1)

    def mark_proxy_in_use(self, thread_name: str, lease: ProxyLease) -> None:
        key = str(thread_name or "").strip()
        if not key or not isinstance(lease, ProxyLease):
            return
        with self.lock:
            self.proxy_in_use_by_thread[key] = lease

    def mark_submit_proxy_in_use(self, thread_name: str, lease: ProxyLease) -> None:
        key = str(thread_name or "").strip()
        if not key or not isinstance(lease, ProxyLease):
            return
        with self.lock:
            self.submit_proxy_in_use_by_thread[key] = lease

    def _purge_expired_proxy_cooldowns_locked(self, *, now_ts: Optional[float] = None) -> None:
        current = float(now_ts if now_ts is not None else time.time())
        expired = [
            address
            for address, cooldown_until in self.proxy_cooldown_until_by_address.items()
            if float(cooldown_until or 0.0) <= current
        ]
        for address in expired:
            self.proxy_cooldown_until_by_address.pop(address, None)

    def purge_expired_proxy_cooldowns(self, *, now_ts: Optional[float] = None) -> None:
        with self.lock:
            self._purge_expired_proxy_cooldowns_locked(now_ts=now_ts)

    def _is_proxy_in_cooldown_locked(self, proxy_address: str, *, now_ts: Optional[float] = None) -> bool:
        normalized = str(proxy_address or "").strip()
        if not normalized:
            return False
        self._purge_expired_proxy_cooldowns_locked(now_ts=now_ts)
        current = float(now_ts if now_ts is not None else time.time())
        return float(self.proxy_cooldown_until_by_address.get(normalized, 0.0) or 0.0) > current

    def is_proxy_in_cooldown(self, proxy_address: str, *, now_ts: Optional[float] = None) -> bool:
        normalized = str(proxy_address or "").strip()
        if not normalized:
            return False
        with self.lock:
            return self._is_proxy_in_cooldown_locked(normalized, now_ts=now_ts)

    def mark_proxy_in_cooldown(self, proxy_address: str, cooldown_seconds: float) -> None:
        normalized = str(proxy_address or "").strip()
        if not normalized:
            return
        try:
            seconds = max(0.0, float(cooldown_seconds))
        except Exception:
            seconds = 0.0
        if seconds <= 0:
            return
        cooldown_until = time.time() + seconds
        with self.lock:
            previous_until = float(self.proxy_cooldown_until_by_address.get(normalized, 0.0) or 0.0)
            self.proxy_cooldown_until_by_address[normalized] = max(previous_until, cooldown_until)
        self.notify_runtime_change()

    def active_proxy_addresses_locked(self, *, exclude_thread_name: str = "") -> set[str]:
        excluded = str(exclude_thread_name or "").strip()
        active = set()
        for proxy_map in (self.proxy_in_use_by_thread, self.submit_proxy_in_use_by_thread):
            for thread_name, lease in proxy_map.items():
                if excluded and str(thread_name or "").strip() == excluded:
                    continue
                address = str(getattr(lease, "address", "") or "").strip()
                if address:
                    active.add(address)
        return active

    def snapshot_active_proxy_addresses(self, *, exclude_thread_name: str = "") -> set[str]:
        with self.lock:
            return self.active_proxy_addresses_locked(exclude_thread_name=exclude_thread_name)

    def is_proxy_address_in_use(self, proxy_address: str, *, exclude_thread_name: str = "") -> bool:
        normalized = str(proxy_address or "").strip()
        if not normalized:
            return False
        with self.lock:
            return normalized in self.active_proxy_addresses_locked(exclude_thread_name=exclude_thread_name)
        return False

    def notify_runtime_change(self) -> None:
        with self._runtime_condition:
            self._runtime_condition.notify_all()

    def wait_for_runtime_change(
        self,
        *,
        stop_signal: Optional[threading.Event] = None,
        timeout: Optional[float] = None,
    ) -> bool:
        if stop_signal is not None and stop_signal.is_set():
            return True
        wait_timeout = None if timeout is None else max(0.0, float(timeout))
        with self._runtime_condition:
            self._runtime_condition.wait(timeout=wait_timeout)
        return bool(stop_signal is not None and stop_signal.is_set())

    def release_proxy_in_use(self, thread_name: str) -> Optional[ProxyLease]:
        key = str(thread_name or "").strip()
        if not key:
            return None
        with self.lock:
            submit_released = self.submit_proxy_in_use_by_thread.pop(key, None)
            released = self.proxy_in_use_by_thread.pop(key, None)
        if released is not None or submit_released is not None:
            self.notify_runtime_change()
        return released

    def update_thread_status(
        self,
        thread_name: str,
        status_text: str,
        *,
        running: Optional[bool] = None,
    ) -> None:
        now = time.time()
        with self.lock:
            state = self._get_or_create_thread_state_locked(thread_name)
            state.status_text = str(status_text or "")
            if running is not None:
                state.running = bool(running)
            state.last_update_ts = now

    def update_thread_step(
        self,
        thread_name: str,
        step_current: int,
        step_total: int,
        *,
        status_text: Optional[str] = None,
        running: Optional[bool] = None,
    ) -> None:
        now = time.time()
        current = max(0, int(step_current or 0))
        total = max(0, int(step_total or 0))
        if total > 0:
            current = min(current, total)
        with self.lock:
            thread_state = self._get_or_create_thread_state_locked(thread_name)
            thread_state.step_current = current
            thread_state.step_total = total
            if status_text is not None:
                thread_state.status_text = str(status_text or "")
            if running is not None:
                thread_state.running = bool(running)
            thread_state.last_update_ts = now

    def increment_thread_success(self, thread_name: str, *, status_text: str = "提交成功") -> None:
        now = time.time()
        with self.lock:
            state = self._get_or_create_thread_state_locked(thread_name)
            state.success_count += 1
            if state.step_total > 0:
                state.step_current = state.step_total
            state.status_text = str(status_text or "提交成功")
            state.running = True
            state.last_update_ts = now

    def increment_thread_fail(self, thread_name: str, *, status_text: str = "失败重试") -> None:
        now = time.time()
        with self.lock:
            state = self._get_or_create_thread_state_locked(thread_name)
            state.fail_count += 1
            state.status_text = str(status_text or "失败重试")
            state.running = True
            state.last_update_ts = now

    def mark_thread_finished(self, thread_name: str, *, status_text: str = "已停止") -> None:
        now = time.time()
        with self.lock:
            state = self._get_or_create_thread_state_locked(thread_name)
            state.running = False
            state.status_text = str(status_text or "已停止")
            state.last_update_ts = now

    def mark_terminal_stop(
        self,
        category: str,
        *,
        failure_reason: str = "",
        message: str = "",
        overwrite: bool = False,
    ) -> None:
        normalized_category = str(category or "").strip()
        if not normalized_category:
            return
        normalized_failure_reason = str(failure_reason or "").strip()
        normalized_message = str(message or "").strip()
        with self._terminal_stop_lock:
            if self.terminal_stop_category and not overwrite:
                return
            self.terminal_stop_category = normalized_category
            self.terminal_failure_reason = normalized_failure_reason
            self.terminal_stop_message = normalized_message
        self.notify_runtime_change()

    def get_terminal_stop_snapshot(self) -> Tuple[str, str, str]:
        with self._terminal_stop_lock:
            return (
                str(self.terminal_stop_category or ""),
                str(self.terminal_failure_reason or ""),
                str(self.terminal_stop_message or ""),
            )

    @staticmethod
    def _normalize_distribution_counts(raw_counts: Any, option_count: int) -> List[int]:
        count = max(0, int(option_count or 0))
        normalized = [0] * count
        if not isinstance(raw_counts, list):
            return normalized
        for idx in range(min(len(raw_counts), count)):
            try:
                normalized[idx] = max(0, int(raw_counts[idx] or 0))
            except Exception:
                normalized[idx] = 0
        return normalized

    def snapshot_distribution_stats(self, stat_key: str, option_count: int) -> Tuple[int, List[int]]:
        with self.lock:
            bucket = self.distribution_runtime_stats.get(str(stat_key or "")) or {}
            total = max(0, int(bucket.get("total") or 0)) if isinstance(bucket, dict) else 0
            counts = self._normalize_distribution_counts(
                bucket.get("counts") if isinstance(bucket, dict) else None,
                option_count,
            )
        return total, counts

    def reset_pending_distribution(self, thread_name: Optional[str] = None) -> None:
        key = str(thread_name or threading.current_thread().name or "Worker-?").strip() or "Worker-?"
        with self.lock:
            self.distribution_pending_by_thread[key] = []

    def append_pending_distribution_choice(
        self,
        stat_key: str,
        option_index: int,
        option_count: int,
        thread_name: Optional[str] = None,
    ) -> None:
        key = str(thread_name or threading.current_thread().name or "Worker-?").strip() or "Worker-?"
        normalized_option_count = max(0, int(option_count or 0))
        normalized_option_index = int(option_index or 0)
        if normalized_option_count <= 0:
            return
        if normalized_option_index < 0 or normalized_option_index >= normalized_option_count:
            return
        item = (str(stat_key or ""), normalized_option_index, normalized_option_count)
        with self.lock:
            pending = self.distribution_pending_by_thread.setdefault(key, [])
            pending.append(item)

    def commit_pending_distribution(self, thread_name: Optional[str] = None) -> int:
        key = str(thread_name or threading.current_thread().name or "Worker-?").strip() or "Worker-?"
        committed = 0
        with self.lock:
            pending = list(self.distribution_pending_by_thread.get(key) or [])
            self.distribution_pending_by_thread[key] = []
            for stat_key, option_index, option_count in pending:
                if option_count <= 0 or option_index < 0 or option_index >= option_count:
                    continue
                bucket = self.distribution_runtime_stats.get(stat_key) or {}
                total = max(0, int(bucket.get("total") or 0)) if isinstance(bucket, dict) else 0
                counts = self._normalize_distribution_counts(
                    bucket.get("counts") if isinstance(bucket, dict) else None,
                    option_count,
                )
                counts[option_index] += 1
                self.distribution_runtime_stats[stat_key] = {
                    "total": total + 1,
                    "counts": counts,
                }
                committed += 1
        return committed

    def peek_reserved_joint_sample(self, thread_name: Optional[str] = None) -> Optional[int]:
        key = str(thread_name or threading.current_thread().name or "Worker-?").strip() or "Worker-?"
        with self.lock:
            reserved = self.joint_reserved_sample_by_thread.get(key)
            return int(reserved) if reserved is not None else None

    def reserve_joint_sample(self, sample_count: int, thread_name: Optional[str] = None) -> Optional[int]:
        key = str(thread_name or threading.current_thread().name or "Worker-?").strip() or "Worker-?"
        total = max(0, int(sample_count or 0))
        if total <= 0:
            return None
        with self.lock:
            existing = self.joint_reserved_sample_by_thread.get(key)
            if existing is not None:
                return int(existing)
            reserved_values = set(self.joint_reserved_sample_by_thread.values())
            for sample_index in range(total):
                if sample_index in reserved_values or sample_index in self.joint_committed_sample_indexes:
                    continue
                self.joint_reserved_sample_by_thread[key] = sample_index
                return sample_index
        return None

    def release_joint_sample(self, thread_name: Optional[str] = None) -> Optional[int]:
        key = str(thread_name or threading.current_thread().name or "Worker-?").strip() or "Worker-?"
        with self.lock:
            reserved = self.joint_reserved_sample_by_thread.pop(key, None)
        if reserved is not None:
            self.notify_runtime_change()
            return int(reserved)
        return None

    def commit_joint_sample(self, thread_name: Optional[str] = None) -> Optional[int]:
        key = str(thread_name or threading.current_thread().name or "Worker-?").strip() or "Worker-?"
        with self.lock:
            reserved = self.joint_reserved_sample_by_thread.pop(key, None)
            if reserved is None:
                return None
            self.joint_committed_sample_indexes.add(int(reserved))
        self.notify_runtime_change()
        return int(reserved)

    def initialize_reverse_fill_runtime(self) -> None:
        with self.lock:
            self.reverse_fill_runtime = create_reverse_fill_runtime_state(getattr(self.config, "reverse_fill_spec", None))
        self.notify_runtime_change()

    def _reverse_fill_thread_key(self, thread_name: Optional[str] = None) -> str:
        key = str(thread_name or threading.current_thread().name or "Worker-?").strip()
        return key or "Worker-?"

    def _reverse_fill_possible_total_locked(self) -> int:
        runtime = self.reverse_fill_runtime
        if runtime is None:
            return max(0, int(self.cur_num or 0))
        return (
            max(0, int(self.cur_num or 0))
            + len(runtime.queued_row_numbers)
            + len(runtime.reserved_row_by_thread)
        )

    def acquire_reverse_fill_sample(self, thread_name: Optional[str] = None) -> ReverseFillAcquireResult:
        key = self._reverse_fill_thread_key(thread_name)
        with self.lock:
            runtime = self.reverse_fill_runtime
            if runtime is None:
                return ReverseFillAcquireResult(status="disabled", message="reverse_fill_disabled")
            existing_row = runtime.reserved_row_by_thread.get(key)
            if existing_row is not None:
                sample = runtime.samples_by_row_number.get(int(existing_row))
                if sample is not None:
                    return ReverseFillAcquireResult(status="acquired", sample=sample, message="already_reserved")
                runtime.reserved_row_by_thread.pop(key, None)
            while runtime.queued_row_numbers:
                row_number = int(runtime.queued_row_numbers.popleft())
                sample = runtime.samples_by_row_number.get(row_number)
                if sample is None:
                    continue
                runtime.reserved_row_by_thread[key] = row_number
                return ReverseFillAcquireResult(status="acquired", sample=sample, message="reserved")
            target_num = max(0, int(getattr(self.config, "target_num", 0) or 0))
            if target_num > 0 and self._reverse_fill_possible_total_locked() < target_num:
                return ReverseFillAcquireResult(status="exhausted", message="reverse_fill_target_unreachable")
            return ReverseFillAcquireResult(status="waiting", message="reverse_fill_waiting")

    def release_reverse_fill_sample(self, thread_name: Optional[str] = None, *, requeue: bool = True) -> Optional[int]:
        key = self._reverse_fill_thread_key(thread_name)
        with self.lock:
            runtime = self.reverse_fill_runtime
            if runtime is None:
                return None
            row_number = runtime.reserved_row_by_thread.pop(key, None)
            if row_number is None:
                return None
            normalized_row = int(row_number)
            if requeue and normalized_row not in runtime.committed_row_numbers and normalized_row not in runtime.discarded_row_numbers:
                runtime.queued_row_numbers.appendleft(normalized_row)
        self.notify_runtime_change()
        return normalized_row

    def commit_reverse_fill_sample(self, thread_name: Optional[str] = None) -> Optional[int]:
        key = self._reverse_fill_thread_key(thread_name)
        with self.lock:
            runtime = self.reverse_fill_runtime
            if runtime is None:
                return None
            row_number = runtime.reserved_row_by_thread.pop(key, None)
            if row_number is None:
                return None
            normalized_row = int(row_number)
            runtime.committed_row_numbers.add(normalized_row)
            runtime.failure_count_by_row.pop(normalized_row, None)
        self.notify_runtime_change()
        return normalized_row

    def mark_reverse_fill_submission_failed(self, thread_name: Optional[str] = None, *, max_retries: int = 1) -> Tuple[Optional[int], bool]:
        key = self._reverse_fill_thread_key(thread_name)
        with self.lock:
            runtime = self.reverse_fill_runtime
            if runtime is None:
                return None, False
            row_number = runtime.reserved_row_by_thread.pop(key, None)
            if row_number is None:
                return None, False
            normalized_row = int(row_number)
            next_count = max(0, int(runtime.failure_count_by_row.get(normalized_row, 0))) + 1
            runtime.failure_count_by_row[normalized_row] = next_count
            if next_count <= max(0, int(max_retries or 0)):
                runtime.queued_row_numbers.appendleft(normalized_row)
                self.notify_runtime_change()
                return normalized_row, False
            runtime.discarded_row_numbers.add(normalized_row)
        self.notify_runtime_change()
        return normalized_row, True

    def wait_for_joint_sample(
        self,
        sample_count: int,
        *,
        thread_name: Optional[str] = None,
        stop_signal: Optional[threading.Event] = None,
        timeout_seconds: float = 0.5,
    ) -> Optional[int]:
        while True:
            reserved = self.reserve_joint_sample(sample_count, thread_name=thread_name)
            if reserved is not None:
                return reserved
            if stop_signal is not None and stop_signal.is_set():
                return None
            if self.wait_for_runtime_change(stop_signal=stop_signal, timeout=timeout_seconds):
                return None

    def wait_for_reverse_fill_sample(
        self,
        *,
        thread_name: Optional[str] = None,
        stop_signal: Optional[threading.Event] = None,
        timeout_seconds: float = 0.5,
    ) -> ReverseFillAcquireResult:
        while True:
            result = self.acquire_reverse_fill_sample(thread_name)
            if result.status != "waiting":
                return result
            if stop_signal is not None and stop_signal.is_set():
                return ReverseFillAcquireResult(status="waiting", message="stopped")
            if self.wait_for_runtime_change(stop_signal=stop_signal, timeout=timeout_seconds):
                return ReverseFillAcquireResult(status="waiting", message="stopped")

    def get_reverse_fill_answer(self, question_num: int, thread_name: Optional[str] = None) -> Optional[ReverseFillAnswer]:
        key = self._reverse_fill_thread_key(thread_name)
        try:
            normalized_question_num = int(question_num)
        except Exception:
            return None
        with self.lock:
            runtime = self.reverse_fill_runtime
            if runtime is None:
                return None
            row_number = runtime.reserved_row_by_thread.get(key)
            if row_number is None:
                return None
            sample = runtime.samples_by_row_number.get(int(row_number))
            if sample is None:
                return None
            return (sample.answers or {}).get(normalized_question_num)

    def is_reverse_fill_target_unreachable(self) -> bool:
        with self.lock:
            runtime = self.reverse_fill_runtime
            if runtime is None:
                return False
            target_num = max(0, int(getattr(self.config, "target_num", 0) or 0))
            if target_num <= 0:
                return False
            return self._reverse_fill_possible_total_locked() < target_num

    def snapshot_thread_progress(self) -> List[Dict[str, Any]]:
        with self.lock:
            rows = []
            for state in self.thread_progress.values():
                total = max(0, int(state.step_total or 0))
                current = max(0, int(state.step_current or 0))
                if total > 0:
                    current = min(current, total)
                    step_percent = int(min(100, (current / float(total)) * 100))
                else:
                    step_percent = 0
                rows.append(
                    {
                        "thread_name": state.thread_name,
                        "thread_display_name": self._format_thread_display_name(
                            state.thread_name,
                            int(state.thread_index or 0),
                        ),
                        "thread_index": int(state.thread_index or 0),
                        "success_count": int(state.success_count or 0),
                        "fail_count": int(state.fail_count or 0),
                        "step_current": current,
                        "step_total": total,
                        "step_percent": step_percent,
                        "status_text": str(state.status_text or ""),
                        "running": bool(state.running),
                        "last_update_ts": float(state.last_update_ts or 0.0),
                    }
                )
        rows.sort(
            key=lambda item: (
                item["thread_index"] <= 0,
                item["thread_index"] if item["thread_index"] > 0 else 10**9,
                item["thread_name"],
            )
        )
        return rows


_EXECUTION_CONFIG_FIELD_NAMES = frozenset(ExecutionConfig.__dataclass_fields__.keys())
_EXECUTION_STATE_FIELD_NAMES = frozenset(ExecutionState.__dataclass_fields__.keys())
