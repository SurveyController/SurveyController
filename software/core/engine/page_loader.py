"""Questionnaire page loading strategies."""

from __future__ import annotations

import logging
import time
from typing import Any, Callable

from software.core.engine.page_load_probe import (
    PAGE_LOAD_PROBE_ANSWERABLE,
    PAGE_LOAD_PROBE_BUSINESS_PAGE,
    wait_for_page_probe,
)
from software.core.task import ExecutionConfig
from software.network.browser import ProxyConnectionError
from software.providers.common import SURVEY_PROVIDER_CREDAMO, normalize_survey_provider

DEFAULT_PAGE_LOAD_TIMEOUT_MS = 20000
DEFAULT_PAGE_LOAD_TIMEOUT_RETRY_MS = 35000
CREDAMO_PAGE_LOAD_TIMEOUT_MS = 45000
RANDOM_PROXY_FAST_COMMIT_TIMEOUT_MS = 8000
RANDOM_PROXY_FAST_PROBE_TIMEOUT_MS = 2500
RANDOM_PROXY_FAST_PROBE_INTERVAL_SECONDS = 0.25
RANDOM_PROXY_FALLBACK_DOM_TIMEOUT_MS = 6000
RANDOM_PROXY_FALLBACK_PROBE_TIMEOUT_MS = 1500
PAGE_LOAD_RETRY_DELAYS_SECONDS = (0.4, 1.0)
PAGE_LOAD_PROXY_ERROR_MARKERS = (
    "ERR_TUNNEL_CONNECTION_FAILED",
    "ERR_PROXY_CONNECTION_FAILED",
    "ERR_NO_SUPPORTED_PROXIES",
    "ERR_CONNECTION_TIMED_OUT",
    "ERR_TIMED_OUT",
    "ERR_CONNECTION_RESET",
    "ERR_CONNECTION_CLOSED",
    "ERR_ADDRESS_UNREACHABLE",
    "ERR_NAME_NOT_RESOLVED",
)


def exception_summary(exc: BaseException) -> str:
    text = str(exc or "").strip()
    if text:
        return text
    return type(exc).__name__


def looks_like_proxy_page_load_failure(exc: BaseException) -> bool:
    message = exception_summary(exc)
    return any(marker in message for marker in PAGE_LOAD_PROXY_ERROR_MARKERS)


def build_page_load_attempts(config: ExecutionConfig) -> tuple[tuple[int, str], ...]:
    provider = normalize_survey_provider(getattr(config, "survey_provider", None))
    if provider == SURVEY_PROVIDER_CREDAMO:
        return (
            (CREDAMO_PAGE_LOAD_TIMEOUT_MS, "domcontentloaded"),
            (CREDAMO_PAGE_LOAD_TIMEOUT_MS, "commit"),
        )
    return (
        (DEFAULT_PAGE_LOAD_TIMEOUT_MS, "domcontentloaded"),
        (DEFAULT_PAGE_LOAD_TIMEOUT_RETRY_MS, "domcontentloaded"),
    )


def notify_page_load_phase(phase_updater: Callable[[str], None] | None, status_text: str) -> None:
    if not callable(phase_updater):
        return
    try:
        phase_updater(str(status_text or ""))
    except Exception:
        logging.info("更新页面加载阶段失败：%s", status_text, exc_info=True)


def random_proxy_probe_succeeded(status: str) -> bool:
    return status in {PAGE_LOAD_PROBE_ANSWERABLE, PAGE_LOAD_PROBE_BUSINESS_PAGE}


def load_survey_page_with_random_proxy(
    driver: Any,
    config: ExecutionConfig,
    *,
    phase_updater: Callable[[str], None] | None = None,
    probe_waiter: Callable[..., Any] = wait_for_page_probe,
) -> None:
    provider = normalize_survey_provider(getattr(config, "survey_provider", None))
    first_probe_detail = ""
    last_exc: Exception | None = None

    notify_page_load_phase(phase_updater, "加载问卷")
    logging.info(
        "随机代理首载：快速提交导航 wait_until=commit timeout=%sms",
        RANDOM_PROXY_FAST_COMMIT_TIMEOUT_MS,
    )
    try:
        driver.get(
            config.url,
            timeout=RANDOM_PROXY_FAST_COMMIT_TIMEOUT_MS,
            wait_until="commit",
        )
        notify_page_load_phase(phase_updater, "探测页面")
        logging.info(
            "随机代理首载：探测页面可用性 timeout=%sms interval=%.2fs",
            RANDOM_PROXY_FAST_PROBE_TIMEOUT_MS,
            RANDOM_PROXY_FAST_PROBE_INTERVAL_SECONDS,
        )
        first_probe = probe_waiter(
            driver,
            provider=provider,
            timeout_ms=RANDOM_PROXY_FAST_PROBE_TIMEOUT_MS,
            poll_interval_seconds=RANDOM_PROXY_FAST_PROBE_INTERVAL_SECONDS,
        )
        first_probe_detail = str(first_probe.detail or "")
        if random_proxy_probe_succeeded(first_probe.status):
            logging.info("随机代理首载探测成功：status=%s detail=%s", first_probe.status, first_probe.detail or "-")
            return
        logging.warning(
            "随机代理首载探测未命中可答题页面：status=%s detail=%s，转入短重载补救",
            first_probe.status,
            first_probe.detail or "-",
        )
    except Exception as exc:
        last_exc = exc
        logging.warning(
            "快速提交导航失败：wait_until=commit timeout=%sms error=%s，转入短重载补救",
            RANDOM_PROXY_FAST_COMMIT_TIMEOUT_MS,
            exception_summary(exc),
        )

    notify_page_load_phase(phase_updater, "加载问卷")
    logging.info(
        "随机代理首载：短重载补救 wait_until=domcontentloaded timeout=%sms",
        RANDOM_PROXY_FALLBACK_DOM_TIMEOUT_MS,
    )
    try:
        driver.get(
            config.url,
            timeout=RANDOM_PROXY_FALLBACK_DOM_TIMEOUT_MS,
            wait_until="domcontentloaded",
        )
    except Exception as exc:
        last_exc = exc
        logging.warning(
            "短重载补救失败：wait_until=domcontentloaded timeout=%sms error=%s",
            RANDOM_PROXY_FALLBACK_DOM_TIMEOUT_MS,
            exception_summary(exc),
        )

    notify_page_load_phase(phase_updater, "探测页面")
    logging.info(
        "随机代理首载：补救后再次探测 timeout=%sms interval=%.2fs",
        RANDOM_PROXY_FALLBACK_PROBE_TIMEOUT_MS,
        RANDOM_PROXY_FAST_PROBE_INTERVAL_SECONDS,
    )
    second_probe = probe_waiter(
        driver,
        provider=provider,
        timeout_ms=RANDOM_PROXY_FALLBACK_PROBE_TIMEOUT_MS,
        poll_interval_seconds=RANDOM_PROXY_FAST_PROBE_INTERVAL_SECONDS,
    )
    if random_proxy_probe_succeeded(second_probe.status):
        logging.info("随机代理补救后探测成功：status=%s detail=%s", second_probe.status, second_probe.detail or "-")
        return

    failure_detail = str(second_probe.detail or first_probe_detail or "")
    if not failure_detail and last_exc is not None:
        failure_detail = exception_summary(last_exc)
    if not failure_detail:
        failure_detail = "页面长时间没有可答题信号"
    logging.warning(
        "随机代理页面探测失败，判定当前代理不可用：detail=%s",
        failure_detail,
    )
    raise ProxyConnectionError(failure_detail)


def load_survey_page(
    driver: Any,
    config: ExecutionConfig,
    *,
    phase_updater: Callable[[str], None] | None = None,
    probe_waiter: Callable[..., Any] = wait_for_page_probe,
) -> None:
    provider = normalize_survey_provider(getattr(config, "survey_provider", None))
    if bool(getattr(config, "random_proxy_ip_enabled", False)) and provider != SURVEY_PROVIDER_CREDAMO:
        load_survey_page_with_random_proxy(
            driver,
            config,
            phase_updater=phase_updater,
            probe_waiter=probe_waiter,
        )
        return

    last_exc: Exception | None = None
    attempts = build_page_load_attempts(config)
    for attempt_index, (timeout_ms, wait_until) in enumerate(attempts, start=1):
        try:
            driver.get(config.url, timeout=timeout_ms, wait_until=wait_until)
            if attempt_index > 1:
                logging.info("问卷加载重试成功：wait_until=%s timeout=%sms", wait_until, timeout_ms)
            return
        except Exception as exc:
            last_exc = exc
            logging.warning(
                "问卷加载第%s次失败：wait_until=%s timeout=%sms error=%s，准备%s",
                attempt_index,
                wait_until,
                timeout_ms,
                exception_summary(exc),
                "重试" if attempt_index < len(attempts) else "结束",
            )
            if attempt_index < len(attempts):
                delay_index = min(attempt_index - 1, len(PAGE_LOAD_RETRY_DELAYS_SECONDS) - 1)
                time.sleep(PAGE_LOAD_RETRY_DELAYS_SECONDS[delay_index])
    if last_exc is not None:
        if bool(getattr(config, "random_proxy_ip_enabled", False)) and looks_like_proxy_page_load_failure(last_exc):
            raise ProxyConnectionError(exception_summary(last_exc)) from last_exc
        raise last_exc
    raise RuntimeError("问卷加载失败")


__all__ = [
    "DEFAULT_PAGE_LOAD_TIMEOUT_MS",
    "DEFAULT_PAGE_LOAD_TIMEOUT_RETRY_MS",
    "CREDAMO_PAGE_LOAD_TIMEOUT_MS",
    "RANDOM_PROXY_FAST_COMMIT_TIMEOUT_MS",
    "RANDOM_PROXY_FAST_PROBE_TIMEOUT_MS",
    "RANDOM_PROXY_FAST_PROBE_INTERVAL_SECONDS",
    "RANDOM_PROXY_FALLBACK_DOM_TIMEOUT_MS",
    "RANDOM_PROXY_FALLBACK_PROBE_TIMEOUT_MS",
    "PAGE_LOAD_RETRY_DELAYS_SECONDS",
    "PAGE_LOAD_PROXY_ERROR_MARKERS",
    "build_page_load_attempts",
    "exception_summary",
    "load_survey_page",
    "load_survey_page_with_random_proxy",
    "looks_like_proxy_page_load_failure",
    "notify_page_load_phase",
    "random_proxy_probe_succeeded",
]
