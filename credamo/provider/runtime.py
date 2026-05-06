"""Credamo 见数问卷运行时作答主流程。"""

from __future__ import annotations

import logging
import random
import threading
import time
from typing import Any, Optional

from software.app.config import DEFAULT_FILL_TEXT
from software.core.modes.duration_control import has_configured_answer_duration, simulate_answer_duration_delay
from software.core.questions.utils import normalize_droplist_probs, weighted_index
from software.core.task import ExecutionConfig, ExecutionState
from software.network.browser import BrowserDriver

from . import runtime_answerers as _runtime_answerers
from . import runtime_dom as _runtime_dom

_DOM_CLICK_SUBMIT = _runtime_dom._click_submit
_DOM_UNANSWERED_QUESTION_ROOTS = _runtime_dom._unanswered_question_roots
_DOM_WAIT_FOR_DYNAMIC_QUESTION_ROOTS = _runtime_dom._wait_for_dynamic_question_roots
_DOM_WAIT_FOR_PAGE_CHANGE = _runtime_dom._wait_for_page_change
_DOM_WAIT_FOR_QUESTION_ROOTS = _runtime_dom._wait_for_question_roots
_ANSWER_DROPDOWN = _runtime_answerers._answer_dropdown
_ANSWER_MATRIX = _runtime_answerers._answer_matrix
_ANSWER_MULTIPLE = _runtime_answerers._answer_multiple
_ANSWER_ORDER = _runtime_answerers._answer_order
_ANSWER_SCALE = _runtime_answerers._answer_scale
_ANSWER_SINGLE_LIKE = _runtime_answerers._answer_single_like
_ANSWER_TEXT = _runtime_answerers._answer_text

_abort_requested = _runtime_dom._abort_requested
_click_element = _runtime_dom._click_element
_click_navigation = _runtime_dom._click_navigation
_click_submit_once = _runtime_dom._click_submit_once
_collect_question_root_snapshot = _runtime_dom._collect_question_root_snapshot
_element_text = _runtime_dom._element_text
_input_value = _runtime_dom._input_value
_is_checked = _runtime_dom._is_checked
_locator_is_visible = _runtime_dom._locator_is_visible
_looks_like_loading_shell = _runtime_dom._looks_like_loading_shell
_navigation_action = _runtime_dom._navigation_action
_option_click_targets = _runtime_dom._option_click_targets
_option_inputs = _runtime_dom._option_inputs
_page = _runtime_dom._page
_page_loading_snapshot = _runtime_dom._page_loading_snapshot
_question_kind_from_root = _runtime_dom._question_kind_from_root
_question_number_from_root = _runtime_dom._question_number_from_root
_question_roots = _runtime_dom._question_roots
_question_signature = _runtime_dom._question_signature
_question_title_text = _runtime_dom._question_title_text
_root_text = _runtime_dom._root_text
_text_inputs = _runtime_dom._text_inputs
_resolve_forced_choice_index = _runtime_answerers._resolve_forced_choice_index


_DOM_SYNC_NAMES = [
    "_abort_requested",
    "_click_navigation",
    "_click_submit_once",
    "_locator_is_visible",
    "_looks_like_loading_shell",
    "_navigation_action",
    "_page_loading_snapshot",
    "_question_number_from_root",
    "_question_roots",
    "_question_signature",
    "_root_text",
]

_ANSWERER_SYNC_NAMES = [
    "_click_element",
    "_element_text",
    "_input_value",
    "_is_checked",
    "_option_click_targets",
    "_option_inputs",
    "_question_title_text",
    "_resolve_forced_choice_index",
    "_root_text",
    "_text_inputs",
    "normalize_droplist_probs",
    "weighted_index",
]


def _sync_runtime_dom_patch_points() -> None:
    """让 runtime.py 上的补丁同步到底层 DOM 模块。"""
    _mod = __import__(__name__, fromlist=["_"])
    for name in _DOM_SYNC_NAMES:
        setattr(_runtime_dom, name, getattr(_mod, name))


def _sync_runtime_answerer_patch_points() -> None:
    """让 runtime.py 上的补丁同步到底层题型作答模块。"""
    _mod = __import__(__name__, fromlist=["_"])
    for name in _ANSWERER_SYNC_NAMES:
        setattr(_runtime_answerers, name, getattr(_mod, name))


def _wait_for_question_roots(page: Any, stop_signal: Optional[threading.Event], **kwargs: Any):
    _sync_runtime_dom_patch_points()
    return _DOM_WAIT_FOR_QUESTION_ROOTS(page, stop_signal, **kwargs)


def _unanswered_question_roots(page: Any, roots: list[Any], answered_keys: set[str], **kwargs: Any):
    _sync_runtime_dom_patch_points()
    return _DOM_UNANSWERED_QUESTION_ROOTS(page, roots, answered_keys, **kwargs)


def _wait_for_dynamic_question_roots(page: Any, answered_keys: set[str], stop_signal: Optional[threading.Event], **kwargs: Any):
    _sync_runtime_dom_patch_points()
    return _DOM_WAIT_FOR_DYNAMIC_QUESTION_ROOTS(page, answered_keys, stop_signal, **kwargs)


def _wait_for_page_change(page: Any, previous_signature: Any, stop_signal: Optional[threading.Event], **kwargs: Any) -> bool:
    _sync_runtime_dom_patch_points()
    return _DOM_WAIT_FOR_PAGE_CHANGE(page, previous_signature, stop_signal, **kwargs)


def _click_submit(page: Any, stop_signal: Optional[threading.Event] = None, **kwargs: Any) -> bool:
    _sync_runtime_dom_patch_points()
    return _DOM_CLICK_SUBMIT(page, stop_signal, **kwargs)


def _answer_single_like(page: Any, root: Any, weights: Any, option_count: int) -> bool:
    _sync_runtime_answerer_patch_points()
    return _ANSWER_SINGLE_LIKE(page, root, weights, option_count)


def _answer_multiple(
    page: Any,
    root: Any,
    weights: Any,
    *,
    min_limit: Optional[int] = None,
    max_limit: Optional[int] = None,
) -> bool:
    _sync_runtime_answerer_patch_points()
    return _ANSWER_MULTIPLE(
        page,
        root,
        weights,
        min_limit=min_limit,
        max_limit=max_limit,
    )


def _answer_text(
    page: Any,
    root: Any,
    text_config: Any,
    *,
    question_num: int = 0,
    ai_enabled: bool = False,
    question_title: str = "",
) -> bool:
    _sync_runtime_answerer_patch_points()
    return _ANSWER_TEXT(
        page,
        root,
        text_config,
        question_num=question_num,
        ai_enabled=ai_enabled,
        question_title=question_title,
    )


def _answer_dropdown(page: Any, root: Any, weights: Any) -> bool:
    _sync_runtime_answerer_patch_points()
    return _ANSWER_DROPDOWN(page, root, weights)


def _answer_scale(page: Any, root: Any, weights: Any) -> bool:
    _sync_runtime_answerer_patch_points()
    return _ANSWER_SCALE(page, root, weights)


def _answer_matrix(page: Any, root: Any, weights: Any, start_index: int = 0) -> bool:
    _sync_runtime_answerer_patch_points()
    return _ANSWER_MATRIX(page, root, weights, start_index)


def _answer_order(page: Any, root: Any, weights: Any = None) -> bool:
    _sync_runtime_answerer_patch_points()
    return _ANSWER_ORDER(page, root, weights)


def _try_fix_unanswered_questions(
    page: Any,
    question_ids: list[str],
    config: ExecutionConfig,
    stop_signal: Optional[threading.Event],
) -> None:
    """Try to scroll to and answer unanswered questions after a failed submit."""
    for q_id in question_ids:
        if _abort_requested(stop_signal):
            break
        # Find the question element by ID
        try:
            root = page.evaluate_handle(
                """(id) => {
                    const el = document.getElementById(id) || document.querySelector(`[data-id="${id}"]`);
                    if (el) el.scrollIntoView({ behavior: 'smooth', block: 'center' });
                    return el;
                }""",
                q_id,
            ).as_element()
        except Exception:
            root = None
        if root is None:
            # Try to find by question number text (e.g., "Q10")
            try:
                root = page.evaluate_handle(
                    """(num) => {
                        const qstNos = document.querySelectorAll('.qstNo');
                        for (const el of qstNos) {
                            if (el.textContent.trim() === num) {
                                const question = el.closest('.question');
                                if (question) question.scrollIntoView({ behavior: 'smooth', block: 'center' });
                                return question;
                            }
                        }
                        return null;
                    }""",
                    q_id,
                ).as_element()
            except Exception:
                root = None
        if root is None:
            logging.info("Credamo 补答：未找到题目元素 %s", q_id)
            continue
        # Detect question kind and try to answer
        kind = _question_kind_from_root(page, root)
        if not kind:
            logging.info("Credamo 补答：题目 %s 无法识别题型", q_id)
            continue
        logging.info("Credamo 补答：尝试回答题目 %s (type=%s)", q_id, kind)
        option_count = len(root.query_selector_all(".choice-text")) if kind in {"single", "multiple", "order"} else 0
        weights = [100.0 / max(1, option_count)] * max(1, option_count)
        if kind == "single":
            _answer_single_like(page, root, weights, option_count)
        elif kind == "multiple":
            _answer_multiple(page, root, weights)
        elif kind in {"scale", "score"}:
            _answer_scale(page, root, weights)
        elif kind == "dropdown":
            _answer_dropdown(page, root, weights)
        elif kind == "matrix":
            _answer_matrix(page, root, weights)
        elif kind == "order":
            _answer_order(page, root)
        elif kind in {"text", "multi_text"}:
            _answer_text(page, root, [DEFAULT_FILL_TEXT])
        time.sleep(random.uniform(0.1, 0.3))


def brush_credamo(
    driver: BrowserDriver,
    config: ExecutionConfig,
    state: ExecutionState,
    *,
    stop_signal: Optional[threading.Event],
    thread_name: str,
    psycho_plan: Optional[Any] = None,
) -> bool:
    del psycho_plan
    active_stop = stop_signal or state.stop_event
    page = _page(driver)
    total_steps = max(1, len(config.question_config_index_map))
    answered_steps = 0
    run_started_at = time.perf_counter()
    try:
        state.update_thread_step(thread_name, 0, total_steps, status_text="答题中", running=True)
    except Exception:
        logging.info("初始化 Credamo 线程进度失败", exc_info=True)

    while not _abort_requested(active_stop):
        page_scan_started_at = time.perf_counter()
        roots = _wait_for_question_roots(page, active_stop)
        if not roots:
            raise RuntimeError("Credamo 当前页未识别到题目")
        logging.info(
            "Credamo 当前页题目快照完成：count=%s elapsed=%.3fs",
            len(_collect_question_root_snapshot(page)),
            time.perf_counter() - page_scan_started_at,
        )

        answered_keys: set[str] = set()
        page_fallback_start = answered_steps
        while not _abort_requested(active_stop):
            pending_roots = _unanswered_question_roots(page, roots, answered_keys, fallback_start=page_fallback_start)
            if not pending_roots:
                break

            for root, question_num, question_key in pending_roots:
                if _abort_requested(active_stop):
                    try:
                        state.update_thread_status(thread_name, "已中断", running=False)
                    except Exception:
                        pass
                    return False

                answered_keys.add(question_key)
                config_entry = config.question_config_index_map.get(question_num)
                if config_entry is None:
                    fallback_kind = _question_kind_from_root(page, root)
                    logging.info("Credamo 第%s题未匹配到配置，页面题型=%s，题面=%s", question_num, fallback_kind, _root_text(page, root))
                    answered_steps = min(total_steps, answered_steps + 1)
                    continue

                entry_type, config_index = config_entry
                try:
                    state.update_thread_step(
                        thread_name,
                        min(total_steps, answered_steps + 1),
                        total_steps,
                        status_text="答题中",
                        running=True,
                    )
                except Exception:
                    logging.info("更新 Credamo 线程进度失败", exc_info=True)

                question_started_at = time.perf_counter()
                if entry_type == "single":
                    weights = config.single_prob[config_index] if config_index < len(config.single_prob) else -1
                    _answer_single_like(page, root, weights, 0)
                elif entry_type in {"scale", "score"}:
                    weights = config.scale_prob[config_index] if config_index < len(config.scale_prob) else -1
                    _answer_scale(page, root, weights)
                elif entry_type == "matrix":
                    question_meta = config.questions_metadata.get(question_num) if hasattr(config, "questions_metadata") else None
                    row_count = max(1, int(getattr(question_meta, "rows", 1) or 1))
                    row_weights = []
                    for row_offset in range(row_count):
                        matrix_index = config_index + row_offset
                        row_weights.append(config.matrix_prob[matrix_index] if matrix_index < len(config.matrix_prob) else -1)
                    _answer_matrix(page, root, row_weights, config_index)
                elif entry_type == "dropdown":
                    weights = config.droplist_prob[config_index] if config_index < len(config.droplist_prob) else -1
                    _answer_dropdown(page, root, weights)
                elif entry_type == "multiple":
                    weights = config.multiple_prob[config_index] if config_index < len(config.multiple_prob) else []
                    question_meta = config.questions_metadata.get(question_num)
                    min_limit = getattr(question_meta, "multi_min_limit", None) if question_meta is not None else None
                    max_limit = getattr(question_meta, "multi_max_limit", None) if question_meta is not None else None
                    _answer_multiple(
                        page,
                        root,
                        weights,
                        min_limit=min_limit,
                        max_limit=max_limit,
                    )
                elif entry_type == "order":
                    _answer_order(page, root)
                elif entry_type in {"text", "multi_text"}:
                    text_config = config.texts[config_index] if config_index < len(config.texts) else [DEFAULT_FILL_TEXT]
                    ai_enabled = bool(config.text_ai_flags[config_index]) if config_index < len(config.text_ai_flags) else False
                    question_title = str(config.text_titles[config_index] or "") if config_index < len(config.text_titles) else ""
                    _answer_text(
                        page,
                        root,
                        text_config,
                        question_num=question_num,
                        ai_enabled=ai_enabled,
                        question_title=question_title,
                    )
                else:
                    logging.info("Credamo 第%s题暂未接入题型：%s", question_num, entry_type)
                logging.info(
                    "Credamo 题目处理耗时：question=%s type=%s elapsed=%.3fs",
                    question_num,
                    entry_type,
                    time.perf_counter() - question_started_at,
                )
                answered_steps = min(total_steps, answered_steps + 1)
                time.sleep(random.uniform(0.03, 0.08))

            dynamic_wait_started_at = time.perf_counter()
            roots = _wait_for_dynamic_question_roots(
                page,
                answered_keys,
                active_stop,
                fallback_start=page_fallback_start,
            )
            logging.info(
                "Credamo 动态显题等待完成：elapsed=%.3fs roots=%s",
                time.perf_counter() - dynamic_wait_started_at,
                len(roots or []),
            )
        navigation_action = _navigation_action(page)
        if navigation_action != "next":
            break
        previous_signature = _question_signature(page)
        try:
            state.update_thread_status(thread_name, "翻到下一页", running=True)
        except Exception:
            logging.info("更新 Credamo 线程状态失败：翻到下一页", exc_info=True)
        transition_started_at = time.perf_counter()
        if not _click_navigation(page, "next"):
            raise RuntimeError("Credamo 下一页按钮未找到")
        if not _wait_for_page_change(page, previous_signature, active_stop):
            raise RuntimeError("Credamo 点击下一页后页面没有变化")
        logging.info("Credamo 翻页耗时：elapsed=%.3fs", time.perf_counter() - transition_started_at)

    if has_configured_answer_duration(config.answer_duration_range_seconds):
        try:
            state.update_thread_status(thread_name, "等待时长中", running=True)
        except Exception:
            logging.info("更新 Credamo 线程状态失败：等待时长中", exc_info=True)
    if simulate_answer_duration_delay(active_stop, config.answer_duration_range_seconds):
        return False
    try:
        state.update_thread_status(thread_name, "提交中", running=True)
    except Exception:
        logging.info("更新 Credamo 线程状态失败：提交中", exc_info=True)
    if not _click_submit(page, active_stop):
        raise RuntimeError("Credamo 提交按钮未找到")
    try:
        state.update_thread_status(thread_name, "等待结果确认", running=True)
    except Exception:
        logging.info("更新 Credamo 线程状态失败：等待结果确认", exc_info=True)

    # Post-submit validation: check for error messages like "请回答此问题"
    from credamo.provider.submission import detect_post_submit_errors
    time.sleep(random.uniform(0.8, 1.5))
    submit_error = detect_post_submit_errors(driver)
    if submit_error is not None:
        q_ids = submit_error.unanswered_question_ids
        # If we detected toasts but no question IDs, wait and retry (error class may be applied later)
        if not q_ids:
            time.sleep(random.uniform(1.5, 2.5))
            submit_error = detect_post_submit_errors(driver)
            if submit_error is not None:
                q_ids = submit_error.unanswered_question_ids
        if submit_error is not None:
            logging.warning(
                "Credamo 提交后检测到验证错误：%s | 未答题ID=%s",
                submit_error.error_text.replace("\n", " | "),
                q_ids if q_ids else "未知",
            )
            # Try to scroll to the first error and answer it
            if q_ids:
                _try_fix_unanswered_questions(page, q_ids, config, active_stop)
                time.sleep(random.uniform(0.5, 1.0))
                # Re-check for errors
                retry_error = detect_post_submit_errors(driver)
                if retry_error is None:
                    logging.info("Credamo 补答后错误消除，重新提交成功")
                    logging.info("Credamo 整体答题耗时：elapsed=%.3fs", time.perf_counter() - run_started_at)
                    return True
                else:
                    logging.warning("Credamo 补答后仍存在错误：%s", retry_error.error_text.replace("\n", " | "))
            try:
                state.update_thread_status(thread_name, f"提交失败：有未答题", running=False)
            except Exception:
                pass
            return False

    logging.info("Credamo 整体答题耗时：elapsed=%.3fs", time.perf_counter() - run_started_at)
    return True
