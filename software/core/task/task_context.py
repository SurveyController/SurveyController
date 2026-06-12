from __future__ import annotations

import threading
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Deque, Dict, List, Optional, Tuple, Union

from software.core.reverse_fill import ReverseFillRuntimeState, ReverseFillSpec
from software.core.task.distribution_state import DistributionRuntimeMixin
from software.core.task.progress_state import ThreadProgressMixin, ThreadProgressState
from software.core.task.proxy_state import ProxyLease, ProxyRuntimeMixin
from software.core.task.reverse_fill_state import ReverseFillRuntimeMixin
from software.providers.contracts import SurveyQuestionMeta


@dataclass
class ExecutionConfig:
    

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
    location_parts: Dict[int, List[str]] = field(default_factory=dict)
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
    provider_question_config_index_map: Dict[str, Tuple[str, int]] = field(default_factory=dict)
    question_dimension_map: Dict[int, Optional[str]] = field(default_factory=dict)
    question_ordinal_score_map: Dict[int, List[int]] = field(default_factory=dict)
    question_strict_ratio_map: Dict[int, bool] = field(default_factory=dict)
    question_psycho_bias_map: Dict[int, Any] = field(default_factory=dict)
    questions_metadata: Dict[int, SurveyQuestionMeta] = field(default_factory=dict)
    provider_question_metadata_map: Dict[str, SurveyQuestionMeta] = field(default_factory=dict)
    joint_psychometric_answer_plan: Optional[Any] = None

    psycho_target_alpha: float = 0.85

    num_threads: int = 1
    target_num: int = 1
    fail_threshold: int = 5
    stop_on_fail_enabled: bool = True

    submit_interval_range_seconds: Tuple[int, int] = (0, 0)
    answer_duration_range_seconds: Tuple[int, int] = (0, 0)
    answer_datetime_window_ms: Tuple[int, int] = (0, 0)

    random_proxy_ip_enabled: bool = False
    proxy_source: str = "default"
    proxy_ip_pool: Union[List[ProxyLease], Deque[ProxyLease]] = field(default_factory=deque)
    random_user_agent_enabled: bool = False
    user_agent_ratios: Dict[str, int] = field(
        default_factory=lambda: {"wechat": 33, "mobile": 33, "pc": 34}
    )
    pause_on_aliyun_captcha: bool = True
    ai_mode: str = "free"
    ai_system_prompt: str = ""


@dataclass
class ExecutionState(
    ThreadProgressMixin,
    ProxyRuntimeMixin,
    DistributionRuntimeMixin,
    ReverseFillRuntimeMixin,
):
    

    config: ExecutionConfig = field(default_factory=ExecutionConfig)

    cur_num: int = 0
    cur_fail: int = 0
    proxy_unavailable_fail_count: int = 0
    device_quota_fail_count: int = 0
    terminal_stop_category: str = ""
    terminal_failure_reason: str = ""
    terminal_stop_message: str = ""
    thread_progress: Dict[str, ThreadProgressState] = field(default_factory=dict)
    distribution_runtime_stats: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    distribution_pending_by_thread: Dict[str, List[Tuple[str, int, int]]] = field(default_factory=dict)
    free_ai_prefill_by_thread: Dict[str, Dict[int, Tuple[str, ...]]] = field(default_factory=dict)
    free_ai_option_fill_prefill_by_thread: Dict[str, Dict[Tuple[int, int], str]] = field(default_factory=dict)
    free_ai_request_timestamps: Deque[float] = field(default_factory=deque)
    joint_reserved_sample_by_thread: Dict[str, int] = field(default_factory=dict)
    joint_reserved_sample_started_at_by_thread: Dict[str, float] = field(default_factory=dict)
    joint_committed_sample_indexes: set[int] = field(default_factory=set)
    joint_answering_threads: set[str] = field(default_factory=set)

    proxy_waiting_threads: int = 0
    proxy_in_use_by_thread: Dict[str, ProxyLease] = field(default_factory=dict)
    successful_proxy_addresses: set[str] = field(default_factory=set)
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
    _free_ai_rate_limit_async_lock: Any = field(default=None, init=False, repr=False)
    _free_ai_rate_limit_async_lock_loop: Any = field(default=None, init=False, repr=False)
    _runtime_condition: threading.Condition = field(default_factory=threading.Condition, repr=False)
    _runtime_async_event: Any = field(default=None, init=False, repr=False)
    _runtime_async_event_loop: Any = field(default=None, init=False, repr=False)
    _runtime_change_seq: int = field(default=0, init=False, repr=False)

    def __setattr__(self, name: str, value: Any) -> None:
        
        if name in _EXECUTION_STATE_FIELD_NAMES:
            object.__setattr__(self, name, value)
            return
        if name in _EXECUTION_CONFIG_FIELD_NAMES:
            raise AttributeError(f"ExecutionState 不允许直接设置配置字段 '{name}'，请改用 state.config.{name}")
        object.__setattr__(self, name, value)

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
    def _normalize_free_ai_thread_key(thread_name: str) -> str:
        return str(thread_name or "").strip() or "__default__"

    def set_free_ai_prefill_answers(
        self,
        thread_name: str,
        answers_by_question_num: Dict[int, Tuple[str, ...]],
    ) -> None:
        normalized: Dict[int, Tuple[str, ...]] = {}
        for question_num, answers in dict(answers_by_question_num or {}).items():
            try:
                normalized_question_num = int(question_num)
            except Exception:
                continue
            normalized_answers = tuple(
                str(item or "").strip()
                for item in tuple(answers or ())
                if str(item or "").strip()
            )
            if normalized_question_num > 0 and normalized_answers:
                normalized[normalized_question_num] = normalized_answers
        key = self._normalize_free_ai_thread_key(thread_name)
        with self.lock:
            if normalized:
                self.free_ai_prefill_by_thread[key] = normalized
            else:
                self.free_ai_prefill_by_thread.pop(key, None)

    def get_free_ai_prefill_answer(
        self,
        thread_name: str,
        question_num: int,
    ) -> Optional[Tuple[str, ...]]:
        try:
            normalized_question_num = int(question_num)
        except Exception:
            return None
        if normalized_question_num <= 0:
            return None
        key = self._normalize_free_ai_thread_key(thread_name)
        with self.lock:
            answers_by_question_num = self.free_ai_prefill_by_thread.get(key) or {}
            result = answers_by_question_num.get(normalized_question_num)
            return tuple(result) if result else None

    def clear_free_ai_prefill_answers(self, thread_name: str) -> None:
        key = self._normalize_free_ai_thread_key(thread_name)
        with self.lock:
            self.free_ai_prefill_by_thread.pop(key, None)
            self.free_ai_option_fill_prefill_by_thread.pop(key, None)

    def set_free_ai_option_fill_prefill_answers(
        self,
        thread_name: str,
        answers_by_option: Dict[Tuple[int, int], str],
    ) -> None:
        normalized: Dict[Tuple[int, int], str] = {}
        for raw_key, raw_value in dict(answers_by_option or {}).items():
            try:
                question_num, option_index = raw_key
                normalized_question_num = int(question_num)
                normalized_option_index = int(option_index)
            except Exception:
                continue
            normalized_value = str(raw_value or "").strip()
            if normalized_question_num <= 0 or normalized_option_index < 0 or not normalized_value:
                continue
            normalized[(normalized_question_num, normalized_option_index)] = normalized_value
        key = self._normalize_free_ai_thread_key(thread_name)
        with self.lock:
            if normalized:
                self.free_ai_option_fill_prefill_by_thread[key] = normalized
            else:
                self.free_ai_option_fill_prefill_by_thread.pop(key, None)

    def get_free_ai_option_fill_prefill_answer(
        self,
        thread_name: str,
        question_num: int,
        option_index: int,
    ) -> Optional[str]:
        try:
            normalized_question_num = int(question_num)
            normalized_option_index = int(option_index)
        except Exception:
            return None
        if normalized_question_num <= 0 or normalized_option_index < 0:
            return None
        key = self._normalize_free_ai_thread_key(thread_name)
        with self.lock:
            answers_by_option = self.free_ai_option_fill_prefill_by_thread.get(key) or {}
            result = answers_by_option.get((normalized_question_num, normalized_option_index))
            return str(result or "").strip() or None


_EXECUTION_CONFIG_FIELD_NAMES = frozenset(ExecutionConfig.__dataclass_fields__.keys())
_EXECUTION_STATE_FIELD_NAMES = frozenset(ExecutionState.__dataclass_fields__.keys())
