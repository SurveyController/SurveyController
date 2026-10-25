from __future__ import annotations

from typing import Any, TypedDict


class RuntimeProgress(TypedDict, total=False):
    current: int
    target: int
    consecutive_failures: int
    device_quota_fail_count: int


class RuntimeThreads(TypedDict, total=False):
    rows: list[dict[str, Any]]
    num_threads: int
    per_thread_target: int


class RuntimeInitialization(TypedDict, total=False):
    active: bool
    stage: str


class RuntimeRandomIp(TypedDict, total=False):
    enabled: bool
    loading: bool
    loading_stage: str
    used_quota: float
    total_quota: float
    custom_api: bool


class RuntimeTerminalStop(TypedDict, total=False):
    category: str
    failure_reason: str
    message: str


class RuntimeSnapshot(TypedDict, total=False):
    phase: str
    running: bool
    paused: bool
    pause_reason: str
    stopping: bool
    progress: RuntimeProgress
    threads: RuntimeThreads
    initialization: RuntimeInitialization
    settings: dict[str, Any]
    random_ip: RuntimeRandomIp
    terminal_stop: RuntimeTerminalStop


class SurveySnapshot(TypedDict, total=False):
    phase: str
    url: str
    survey_title: str
    survey_provider: str
    questions_info: list[Any]
    question_entries: list[Any]
    error_code: str
    parse_error: str
    has_question_entries: bool
