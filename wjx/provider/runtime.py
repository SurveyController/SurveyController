"""答题核心逻辑 - 按配置策略自动填写问卷。"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Dict, Iterable, Optional

from software.app.config import HEADLESS_PAGE_BUFFER_DELAY, HEADLESS_PAGE_CLICK_DELAY
from software.core.engine.dom_helpers import (
    _count_choice_inputs_driver,
    _driver_question_looks_like_description,
    _driver_question_looks_like_slider_matrix,
)
from software.core.engine.runtime_control import _is_headless_mode
from software.core.modes.duration_control import has_configured_answer_duration, simulate_answer_duration_delay
from software.core.questions.utils import _should_treat_question_as_text_like
from software.core.reverse_fill.runtime import resolve_current_reverse_fill_answer
from software.core.task import ExecutionConfig, ExecutionState
from software.network.browser import BrowserDriver, By, NoSuchElementException
from software.providers.contracts import SurveyQuestionMeta
from software.providers.registry import parse_survey_sync
from wjx.provider.detection import detect as _wjx_detect
from wjx.provider.navigation import (
    _click_next_page_button,
    _human_scroll_after_question,
    dismiss_resume_dialog_if_present,
    try_click_start_answer_button,
)
from wjx.provider.questions.multiple import multiple as _multiple_impl
from wjx.provider.questions.single import single as _single_impl
from wjx.provider.questions.text import (
    count_visible_text_inputs as _count_visible_text_inputs_driver,
    text as _text_impl,
)
from wjx.provider.runtime_dispatch import _dispatcher, _question_title_for_log
from wjx.provider.runtime_state import get_wjx_runtime_state
from wjx.provider.submission import submit


def _build_initial_indices() -> Dict[str, int]:
    return {
        "single": 0,
        "text": 0,
        "dropdown": 0,
        "multiple": 0,
        "matrix": 0,
        "scale": 0,
        "slider": 0,
    }


def _build_runtime_page_question_plan(
    page_questions: Iterable[SurveyQuestionMeta],
) -> list[dict[str, Any]]:
    plan: list[dict[str, Any]] = []
    for meta in page_questions:
        if meta is None:
            continue
        try:
            question_num = int(getattr(meta, "num", 0) or 0)
        except Exception:
            question_num = 0
        if question_num <= 0:
            continue
        plan.append(
            {
                "question_num": question_num,
                "type_code": str(getattr(meta, "type_code", "") or "").strip(),
                "required": bool(getattr(meta, "required", False)),
            }
        )
    return plan


def _store_runtime_page_context(
    driver: BrowserDriver,
    *,
    page_number: int,
    page_questions: Iterable[SurveyQuestionMeta],
    indices: Dict[str, int],
) -> None:
    state = get_wjx_runtime_state(driver)
    state.page_number = int(page_number or 0)
    state.page_questions = _build_runtime_page_question_plan(page_questions)
    state.indices_snapshot = dict(indices or {})


def _store_runtime_psycho_plan(driver: BrowserDriver, psycho_plan: Optional[Any]) -> None:
    state = get_wjx_runtime_state(driver)
    state.psycho_plan = psycho_plan


def _collect_visible_question_snapshot(driver: BrowserDriver) -> Dict[int, Dict[str, Any]]:
    try:
        payload = driver.execute_script(
            r"""
            return (() => {
                const visible = (el) => {
                    if (!el) return false;
                    const style = window.getComputedStyle(el);
                    if (!style || style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') return false;
                    const rect = el.getBoundingClientRect();
                    return rect.width > 0 && rect.height > 0;
                };
                const normalize = (text) => String(text || '').replace(/\s+/g, ' ').trim();
                const result = {};
                const nodes = Array.from(document.querySelectorAll('#divQuestion [topic], #divQuestion div[id^="div"]'));
                nodes.forEach((node) => {
                    const rawTopic = String(node.getAttribute('topic') || '').trim();
                    const idMatch = String(node.getAttribute('id') || '').trim().match(/^div(\d+)$/);
                    const questionNum = rawTopic && /^\d+$/.test(rawTopic)
                        ? Number.parseInt(rawTopic, 10)
                        : (idMatch ? Number.parseInt(idMatch[1], 10) : 0);
                    if (!questionNum || !visible(node)) return;
                    result[String(questionNum)] = {
                        visible: true,
                        type: String(node.getAttribute('type') || '').trim(),
                        title: normalize(node.innerText || node.textContent || '').slice(0, 180),
                    };
                });
                return result;
            })();
            """
        ) or {}
    except Exception:
        return {}
    snapshot: Dict[int, Dict[str, Any]] = {}
    if not isinstance(payload, dict):
        return snapshot
    for raw_key, value in payload.items():
        try:
            question_num = int(raw_key)
        except Exception:
            continue
        if question_num <= 0 or not isinstance(value, dict):
            continue
        snapshot[question_num] = {
            "visible": bool(value.get("visible")),
            "type": str(value.get("type") or "").strip(),
            "title": str(value.get("title") or "").strip(),
        }
    return snapshot


def _refresh_visible_question_snapshot(driver: BrowserDriver, *, reason: str) -> Dict[int, Dict[str, Any]]:
    return _collect_visible_question_snapshot(driver)


def _snapshot_visible_numbers(snapshot: Dict[int, Dict[str, Any]]) -> set[int]:
    return {
        int(question_num)
        for question_num, payload in dict(snapshot or {}).items()
        if isinstance(payload, dict) and bool(payload.get("visible"))
    }


def _question_metadata_map(ctx: ExecutionState) -> Dict[int, SurveyQuestionMeta]:
    metadata = getattr(getattr(ctx, "config", ctx), "questions_metadata", {}) or {}
    normalized: Dict[int, SurveyQuestionMeta] = {}
    if isinstance(metadata, dict):
        for raw_num, meta in metadata.items():
            try:
                question_num = int(raw_num)
            except Exception:
                continue
            if question_num <= 0 or meta is None:
                continue
            normalized[question_num] = meta
    return normalized


def _build_metadata_page_plan(ctx: ExecutionState) -> list[tuple[int, list[SurveyQuestionMeta]]]:
    metadata = _question_metadata_map(ctx)
    by_page: dict[int, list[SurveyQuestionMeta]] = {}
    for meta in metadata.values():
        try:
            page_number = max(1, int(getattr(meta, "page", 1) or 1))
        except Exception:
            page_number = 1
        by_page.setdefault(page_number, []).append(meta)
    page_plan: list[tuple[int, list[SurveyQuestionMeta]]] = []
    for page_number in sorted(by_page):
        page_questions = sorted(
            by_page[page_number],
            key=lambda item: (int(getattr(item, "num", 0) or 0), str(getattr(item, "title", "") or "")),
        )
        if page_questions:
            page_plan.append((page_number, page_questions))
    return page_plan


def _question_requires_snapshot_refresh(question_meta: SurveyQuestionMeta | None) -> bool:
    if question_meta is None:
        return False
    return bool(
        getattr(question_meta, "has_jump", False)
        or getattr(question_meta, "has_dependent_display_logic", False)
    )


def _question_refresh_candidate_numbers(
    question_meta: SurveyQuestionMeta | None,
    page_questions: list[SurveyQuestionMeta],
    question_index: int,
) -> list[int]:
    candidates: set[int] = set()
    if question_index + 1 < len(page_questions):
        try:
            next_question_num = int(getattr(page_questions[question_index + 1], "num", 0) or 0)
        except Exception:
            next_question_num = 0
        if next_question_num > 0:
            candidates.add(next_question_num)

    if question_meta is None:
        return sorted(candidates)

    for rule in list(getattr(question_meta, "jump_rules", []) or []):
        if not isinstance(rule, dict):
            continue
        try:
            jumpto_num = int(rule.get("jumpto") or 0)
        except Exception:
            jumpto_num = 0
        if jumpto_num > 0:
            candidates.add(jumpto_num)

    for target in list(getattr(question_meta, "controls_display_targets", []) or []):
        if not isinstance(target, dict):
            continue
        try:
            target_question_num = int(target.get("target_question_num") or 0)
        except Exception:
            target_question_num = 0
        if target_question_num > 0:
            candidates.add(target_question_num)

    return sorted(candidates)


def _refresh_snapshot_if_visibility_changed(
    driver: BrowserDriver,
    snapshot: Dict[int, Dict[str, Any]],
    candidate_numbers: Iterable[int],
    *,
    reason: str,
) -> tuple[Dict[int, Dict[str, Any]], bool]:
    normalized_candidates: list[int] = []
    for raw_num in candidate_numbers:
        try:
            question_num = int(raw_num)
        except Exception:
            continue
        if question_num > 0:
            normalized_candidates.append(question_num)
    if not normalized_candidates:
        return snapshot, False

    changed = False
    for question_num in sorted(set(normalized_candidates)):
        snapshot_item = snapshot.get(question_num) if isinstance(snapshot, dict) else None
        question_div = None
        try:
            question_div = driver.find_element(By.CSS_SELECTOR, f"#div{question_num}")
        except Exception:
            question_div = None
        dom_visible = False
        if question_div is not None:
            for attempt in range(2):
                try:
                    if question_div.is_displayed():
                        dom_visible = True
                        break
                except Exception:
                    dom_visible = False
                    break
                if attempt < 1:
                    time.sleep(0.04)
        snapshot_visible = bool(isinstance(snapshot_item, dict) and bool(snapshot_item.get("visible")))
        if dom_visible == snapshot_visible:
            continue
        changed = True
        break

    if not changed:
        return snapshot, False

    refreshed = _refresh_visible_question_snapshot(driver, reason=reason)
    return refreshed, True


def _update_abort_status(ctx: ExecutionState, thread_name: str) -> None:
    try:
        ctx.update_thread_status(thread_name, "已中断", running=False)
    except Exception:
        logging.info("更新线程状态失败：已中断", exc_info=True)


def _prepare_runtime_entry_gate(
    driver: BrowserDriver,
    active_stop: Optional[threading.Event],
) -> bool:
    """进入问卷运行时前，先处理续答弹窗和开屏说明页。"""
    dismiss_resume_dialog_if_present(driver, timeout=0.2, stop_signal=active_stop)
    start_clicked = try_click_start_answer_button(driver, timeout=0.35, stop_signal=active_stop)
    if not start_clicked:
        return True
    if active_stop:
        return not active_stop.wait(0.15)
    time.sleep(0.15)
    return True


def _fallback_unknown_question(
    driver: BrowserDriver,
    ctx: ExecutionState,
    *,
    question_num: int,
    question_type: str,
    question_div,
    indices: Dict[str, int],
) -> None:
    config = ctx.config
    handled = False
    if question_div is not None:
        checkbox_count, radio_count = _count_choice_inputs_driver(question_div)
        if checkbox_count or radio_count:
            if checkbox_count >= radio_count:
                _multiple_impl(
                    driver,
                    question_num,
                    indices["multiple"],
                    config.multiple_prob,
                    config.multiple_option_fill_texts,
                )
                indices["multiple"] += 1
            else:
                _single_impl(
                    driver,
                    question_num,
                    indices["single"],
                    config.single_prob,
                    config.single_option_fill_texts,
                    config.single_attached_option_selects,
                    task_ctx=ctx,
                )
                indices["single"] += 1
            handled = True

    if handled:
        return

    option_count = 0
    if question_div is not None:
        try:
            option_elements = question_div.find_elements(By.CSS_SELECTOR, ".ui-controlgroup > div")
            option_count = len(option_elements)
        except Exception:
            option_count = 0
    text_input_count = _count_visible_text_inputs_driver(question_div) if question_div is not None else 0
    has_slider_matrix = _driver_question_looks_like_slider_matrix(question_div)
    is_text_like_question = _should_treat_question_as_text_like(
        question_type,
        option_count,
        text_input_count,
        has_slider_matrix=has_slider_matrix,
    )

    if is_text_like_question:
        reverse_fill_answer = resolve_current_reverse_fill_answer(ctx, question_num)
        _text_impl(
            driver,
            question_num,
            indices["text"],
            config.texts,
            config.texts_prob,
            config.text_entry_types,
            config.text_ai_flags,
            config.text_titles,
            config.multi_text_blank_modes,
            config.multi_text_blank_ai_flags,
            config.multi_text_blank_int_ranges,
            task_ctx=ctx,
        )
        if reverse_fill_answer is None:
            indices["text"] += 1
        return

    print(f"第{question_num}题为不支持类型(type={question_type})")


def _refresh_questions_metadata(ctx: ExecutionState) -> bool:
    url = str(getattr(getattr(ctx, "config", ctx), "url", "") or "").strip()
    if not url:
        return False
    try:
        definition = parse_survey_sync(url)
    except Exception as exc:
        logging.warning("WJX 结构漂移后刷新题目结构失败：%s", exc)
        return False
    if not getattr(definition, "questions", None):
        return False
    changed = False
    with getattr(ctx, "lock", threading.Lock()):
        current = dict(getattr(ctx.config, "questions_metadata", {}) or {})
        updated = dict(current)
        for meta in list(definition.questions or []):
            try:
                question_num = int(getattr(meta, "num", 0) or 0)
            except Exception:
                question_num = 0
            if question_num <= 0:
                continue
            previous = updated.get(question_num)
            updated[question_num] = meta
            if previous != meta:
                changed = True
        if changed:
            ctx.config.questions_metadata = updated
    if changed:
        logging.info("WJX 结构漂移刷新完成：questions=%s", len(getattr(definition, "questions", []) or []))
    return changed


def _refresh_metadata_when_snapshot_drifts(
    ctx: ExecutionState,
    snapshot: Dict[int, Dict[str, Any]],
) -> bool:
    metadata = _question_metadata_map(ctx)
    unknown_visible = [num for num in _snapshot_visible_numbers(snapshot) if num not in metadata]
    if not unknown_visible:
        return False
    logging.warning("WJX 检测到缓存外新题目，触发结构刷新：questions=%s", unknown_visible)
    return _refresh_questions_metadata(ctx)


def _question_is_visible(
    question_div,
    snapshot_item: Dict[str, Any] | None,
) -> bool:
    if isinstance(snapshot_item, dict) and bool(snapshot_item.get("visible")):
        return True
    if question_div is None:
        return False
    for attempt in range(2):
        try:
            if question_div.is_displayed():
                return True
        except Exception:
            return False
        if attempt < 1:
            time.sleep(0.04)
    return False


def _finalize_page(
    driver: BrowserDriver,
    active_stop: Optional[threading.Event],
    *,
    headless_mode: bool,
    is_last_page: bool,
    runtime_config: ExecutionConfig,
    thread_name: str,
    ctx: ExecutionState,
) -> bool:
    _human_scroll_after_question(driver)
    if active_stop and active_stop.is_set():
        _update_abort_status(ctx, thread_name)
        return False
    buffer_delay = float(HEADLESS_PAGE_BUFFER_DELAY if headless_mode else 0.5)
    if buffer_delay > 0:
        if active_stop:
            if active_stop.wait(buffer_delay):
                _update_abort_status(ctx, thread_name)
                return False
        else:
            time.sleep(buffer_delay)
    if is_last_page:
        if has_configured_answer_duration(runtime_config.answer_duration_range_seconds):
            try:
                ctx.update_thread_status(thread_name, "等待时长中", running=True)
            except Exception:
                logging.info("更新线程状态失败：等待时长中", exc_info=True)
        if simulate_answer_duration_delay(active_stop, runtime_config.answer_duration_range_seconds):
            _update_abort_status(ctx, thread_name)
            return False
        if active_stop and active_stop.is_set():
            _update_abort_status(ctx, thread_name)
            return False
        return True
    clicked = _click_next_page_button(driver)
    if not clicked:
        raise NoSuchElementException("Next page button not found")
    click_delay = float(HEADLESS_PAGE_CLICK_DELAY if headless_mode else 0.5)
    if click_delay > 0:
        if active_stop:
            if active_stop.wait(click_delay):
                _update_abort_status(ctx, thread_name)
                return False
        else:
            time.sleep(click_delay)
    return True


def _run_question_dispatch(
    driver: BrowserDriver,
    ctx: ExecutionState,
    *,
    question_num: int,
    question_type: str,
    question_div,
    indices: Dict[str, int],
    psycho_plan: Optional[Any],
) -> None:
    config_entry = ctx.config.question_config_index_map.get(question_num)
    dispatch_result = _dispatcher.fill(
        driver=driver,
        question_type=question_type,
        question_num=question_num,
        question_div=question_div,
        config_entry=config_entry,
        indices=indices,
        ctx=ctx,
        psycho_plan=psycho_plan,
    )

    if dispatch_result is False:
        _fallback_unknown_question(
            driver,
            ctx,
            question_num=question_num,
            question_type=question_type,
            question_div=question_div,
            indices=indices,
        )


def refill_required_questions_on_current_page(
    driver: BrowserDriver,
    ctx: ExecutionState,
    *,
    question_numbers: Iterable[int],
    thread_name: str,
    psycho_plan: Optional[Any] = None,
) -> int:
    target_numbers: list[int] = []
    for raw_num in question_numbers:
        try:
            question_num = int(raw_num)
        except Exception:
            continue
        if question_num > 0 and question_num not in target_numbers:
            target_numbers.append(question_num)
    if not target_numbers:
        return 0

    metadata = _question_metadata_map(ctx)
    snapshot = _refresh_visible_question_snapshot(driver, reason="submission_recovery_refill")
    runtime_state = get_wjx_runtime_state(driver)
    indices = dict(runtime_state.indices_snapshot or {})
    if not indices:
        indices = _build_initial_indices()
    filled_count = 0
    for question_num in target_numbers:
        question_meta = metadata.get(question_num)
        if question_meta is None:
            logging.warning("WJX 提交补答跳过：第%s题缺少题目元数据。", question_num)
            continue
        try:
            question_div = driver.find_element(By.CSS_SELECTOR, f"#div{question_num}")
        except Exception:
            logging.warning("WJX 提交补答跳过：第%s题未定位到题目容器。", question_num)
            continue
        snapshot_item = snapshot.get(question_num) if isinstance(snapshot, dict) else None
        if not _question_is_visible(question_div, snapshot_item):
            continue

        question_type = str((snapshot_item or {}).get("type") or "").strip() if isinstance(snapshot_item, dict) else ""
        if not question_type:
            try:
                question_type = str(question_div.get_attribute("type") or "").strip()
            except Exception:
                question_type = str(getattr(question_meta, "type_code", "") or "").strip()
        if not question_type:
            logging.warning("WJX 提交补答跳过：第%s题缺少 type。", question_num)
            continue
        if _driver_question_looks_like_description(question_div, question_type):
            continue

        _run_question_dispatch(
            driver,
            ctx,
            question_num=question_num,
            question_type=question_type,
            question_div=question_div,
            indices=indices,
            psycho_plan=psycho_plan,
        )
        filled_count += 1

    runtime_state.indices_snapshot = dict(indices)
    if filled_count > 0:
        try:
            ctx.update_thread_status(thread_name, "补答必答题", running=True)
        except Exception:
            logging.info("更新线程状态失败：补答必答题", exc_info=True)
    return filled_count


def _ensure_question_snapshot_visibility(
    driver: BrowserDriver,
    snapshot: Dict[int, Dict[str, Any]],
    *,
    question_num: int,
    reason: str,
) -> Dict[int, Dict[str, Any]]:
    snapshot_item = snapshot.get(question_num) if isinstance(snapshot, dict) else None
    question_div = None
    try:
        question_div = driver.find_element(By.CSS_SELECTOR, f"#div{question_num}")
    except Exception:
        question_div = None
    dom_visible = False
    if question_div is not None:
        for attempt in range(2):
            try:
                if question_div.is_displayed():
                    dom_visible = True
                    break
            except Exception:
                dom_visible = False
                break
            if attempt < 1:
                time.sleep(0.04)
    snapshot_visible = bool(isinstance(snapshot_item, dict) and bool(snapshot_item.get("visible")))
    if dom_visible == snapshot_visible:
        return snapshot
    return _refresh_visible_question_snapshot(driver, reason=reason)


def _brush_with_detect_fallback(
    driver: BrowserDriver,
    ctx: ExecutionState,
    stop_signal: Optional[threading.Event] = None,
    *,
    thread_name: str,
    psycho_plan: Optional[Any],
) -> bool:
    questions_per_page = _wjx_detect(driver, stop_signal=stop_signal)
    headless_mode = _is_headless_mode(ctx)
    try:
        total_steps = sum(max(0, int(count or 0)) for count in questions_per_page)
    except Exception:
        total_steps = 0
    try:
        ctx.update_thread_step(thread_name, 0, total_steps, status_text="答题中", running=True)
    except Exception:
        logging.info("初始化线程步骤进度失败", exc_info=True)

    indices = _build_initial_indices()
    current_question_number = 0
    active_stop = stop_signal or ctx.stop_event
    runtime_config = ctx.config
    _store_runtime_psycho_plan(driver, psycho_plan)

    def _abort_requested() -> bool:
        return bool(active_stop and active_stop.is_set())

    if _abort_requested():
        _update_abort_status(ctx, thread_name)
        return False

    total_pages = len(questions_per_page)
    for page_index, questions_count in enumerate(questions_per_page):
        _store_runtime_page_context(
            driver,
            page_number=page_index + 1,
            page_questions=[],
            indices=indices,
        )
        page_snapshot = _refresh_visible_question_snapshot(driver, reason=f"fallback_page_{page_index + 1}")
        for _ in range(1, questions_count + 1):
            if _abort_requested():
                _update_abort_status(ctx, thread_name)
                return False
            current_question_number += 1
            if total_steps > 0:
                try:
                    ctx.update_thread_step(
                        thread_name,
                        current_question_number,
                        total_steps,
                        status_text="答题中",
                        running=True,
                    )
                except Exception:
                    logging.info("更新线程步骤进度失败", exc_info=True)
            question_selector = f"#div{current_question_number}"
            try:
                question_div = driver.find_element(By.CSS_SELECTOR, question_selector)
            except Exception:
                question_div = None
            if question_div is None:
                continue

            snapshot_item = page_snapshot.get(current_question_number) if isinstance(page_snapshot, dict) else None
            question_visible = _question_is_visible(question_div, snapshot_item)
            if not question_visible:
                page_snapshot = _ensure_question_snapshot_visibility(
                    driver,
                    page_snapshot,
                    question_num=current_question_number,
                    reason=f"fallback_question_{current_question_number}_visibility_miss",
                )
                snapshot_item = page_snapshot.get(current_question_number) if isinstance(page_snapshot, dict) else None
                question_visible = _question_is_visible(question_div, snapshot_item)
            question_type = str((snapshot_item or {}).get("type") or "").strip() if isinstance(snapshot_item, dict) else ""
            if not question_type:
                question_type = question_div.get_attribute("type")
            if question_type is None:
                continue
            if _driver_question_looks_like_description(question_div, question_type):
                continue

            if not question_visible:
                continue

            _run_question_dispatch(
                driver,
                ctx,
                question_num=current_question_number,
                question_type=question_type,
                question_div=question_div,
                indices=indices,
                psycho_plan=psycho_plan,
            )

        if not _finalize_page(
            driver,
            active_stop,
            headless_mode=headless_mode,
            is_last_page=(page_index == total_pages - 1),
            runtime_config=runtime_config,
            thread_name=thread_name,
            ctx=ctx,
        ):
            return False

    if active_stop and active_stop.is_set():
        _update_abort_status(ctx, thread_name)
        return False
    try:
        ctx.update_thread_status(thread_name, "提交中", running=True)
    except Exception:
        logging.info("更新线程状态失败：提交中", exc_info=True)
    submit(driver, ctx=ctx, stop_signal=active_stop)
    try:
        ctx.update_thread_status(thread_name, "等待结果确认", running=True)
    except Exception:
        logging.info("更新线程状态失败：等待结果确认", exc_info=True)
    return True


def _brush_with_metadata(
    driver: BrowserDriver,
    ctx: ExecutionState,
    stop_signal: Optional[threading.Event] = None,
    *,
    thread_name: str,
    psycho_plan: Optional[Any],
) -> bool:
    page_plan = _build_metadata_page_plan(ctx)
    if not page_plan:
        return _brush_with_detect_fallback(
            driver,
            ctx,
            stop_signal=stop_signal,
            thread_name=thread_name,
            psycho_plan=psycho_plan,
        )

    headless_mode = _is_headless_mode(ctx)
    active_stop = stop_signal or ctx.stop_event
    runtime_config = ctx.config
    indices = _build_initial_indices()
    progress_step = 0
    total_steps = sum(len(question_list) for _, question_list in page_plan)

    try:
        ctx.update_thread_step(thread_name, 0, total_steps, status_text="答题中", running=True)
    except Exception:
        logging.info("初始化线程步骤进度失败", exc_info=True)

    for page_index, (page_number, _) in enumerate(page_plan):
        if active_stop and active_stop.is_set():
            _update_abort_status(ctx, thread_name)
            return False

        snapshot = _refresh_visible_question_snapshot(driver, reason=f"page_{page_number}_enter")
        if _refresh_metadata_when_snapshot_drifts(ctx, snapshot):
            page_plan = _build_metadata_page_plan(ctx)
        page_questions = [meta for candidate_page, questions in page_plan if candidate_page == page_number for meta in questions]
        _store_runtime_page_context(
            driver,
            page_number=page_number,
            page_questions=page_questions,
            indices=indices,
        )
        question_index = 0

        while question_index < len(page_questions):
            if active_stop and active_stop.is_set():
                _update_abort_status(ctx, thread_name)
                return False

            question_meta = page_questions[question_index]
            question_num = int(getattr(question_meta, "num", 0) or 0)
            if question_num <= 0:
                question_index += 1
                continue

            progress_step += 1
            if total_steps > 0:
                try:
                    ctx.update_thread_step(
                        thread_name,
                        progress_step,
                        total_steps,
                        status_text="答题中",
                        running=True,
                    )
                except Exception:
                    logging.info("更新线程步骤进度失败", exc_info=True)

            question_selector = f"#div{question_num}"
            try:
                question_div = driver.find_element(By.CSS_SELECTOR, question_selector)
            except Exception:
                question_div = None

            snapshot_item = snapshot.get(question_num) if isinstance(snapshot, dict) else None
            question_visible = _question_is_visible(question_div, snapshot_item)
            if not question_visible and (question_index + 1 < len(page_questions) or bool(getattr(question_meta, "has_display_condition", False))):
                refreshed = _refresh_visible_question_snapshot(driver, reason=f"question_{question_num}_expected_visible_miss")
                if _refresh_metadata_when_snapshot_drifts(ctx, refreshed):
                    page_plan = _build_metadata_page_plan(ctx)
                    page_questions = [meta for candidate_page, questions in page_plan if candidate_page == page_number for meta in questions]
                snapshot = refreshed
                snapshot_item = snapshot.get(question_num)
                question_visible = _question_is_visible(question_div, snapshot_item)

            if question_div is None or not question_visible:
                question_index += 1
                continue

            question_type = str((snapshot_item or {}).get("type") or "").strip() if isinstance(snapshot_item, dict) else ""
            if not question_type:
                try:
                    question_type = str(question_div.get_attribute("type") or "").strip()
                except Exception:
                    question_type = str(getattr(question_meta, "type_code", "") or "").strip()
            if not question_type:
                question_index += 1
                continue

            if _driver_question_looks_like_description(question_div, question_type):
                question_index += 1
                continue

            _run_question_dispatch(
                driver,
                ctx,
                question_num=question_num,
                question_type=question_type,
                question_div=question_div,
                indices=indices,
                psycho_plan=psycho_plan,
            )

            if _question_requires_snapshot_refresh(question_meta):
                candidate_numbers = _question_refresh_candidate_numbers(question_meta, page_questions, question_index)
                refreshed, did_refresh = _refresh_snapshot_if_visibility_changed(
                    driver,
                    snapshot,
                    candidate_numbers,
                    reason=f"question_{question_num}_display_logic",
                )
            else:
                refreshed, did_refresh = snapshot, False

            if did_refresh:
                if _refresh_metadata_when_snapshot_drifts(ctx, refreshed):
                    page_plan = _build_metadata_page_plan(ctx)
                    page_questions = [meta for candidate_page, questions in page_plan if candidate_page == page_number for meta in questions]
                snapshot = refreshed

            _store_runtime_page_context(
                driver,
                page_number=page_number,
                page_questions=page_questions,
                indices=indices,
            )
            question_index += 1

        if not _finalize_page(
            driver,
            active_stop,
            headless_mode=headless_mode,
            is_last_page=(page_index == len(page_plan) - 1),
            runtime_config=runtime_config,
            thread_name=thread_name,
            ctx=ctx,
        ):
            return False

    if active_stop and active_stop.is_set():
        _update_abort_status(ctx, thread_name)
        return False
    try:
        ctx.update_thread_status(thread_name, "提交中", running=True)
    except Exception:
        logging.info("更新线程状态失败：提交中", exc_info=True)
    submit(driver, ctx=ctx, stop_signal=active_stop)
    try:
        ctx.update_thread_status(thread_name, "等待结果确认", running=True)
    except Exception:
        logging.info("更新线程状态失败：等待结果确认", exc_info=True)
    return True


def brush(
    driver: BrowserDriver,
    ctx: ExecutionState,
    stop_signal: Optional[threading.Event] = None,
    *,
    thread_name: Optional[str] = None,
    psycho_plan: Optional[Any] = None,
) -> bool:
    """批量填写一份问卷；返回 True 代表完整提交，False 代表过程中被用户打断。"""
    normalized_thread_name = str(thread_name or threading.current_thread().name or "Worker-?").strip() or "Worker-?"
    active_stop = stop_signal or ctx.stop_event
    if active_stop and active_stop.is_set():
        _update_abort_status(ctx, normalized_thread_name)
        return False
    if not _prepare_runtime_entry_gate(driver, active_stop):
        _update_abort_status(ctx, normalized_thread_name)
        return False
    return _brush_with_metadata(
        driver,
        ctx,
        stop_signal=active_stop,
        thread_name=normalized_thread_name,
        psycho_plan=psycho_plan,
    )


def brush_wjx(
    driver: BrowserDriver,
    config: ExecutionConfig,
    ctx: ExecutionState,
    *,
    stop_signal: Optional[threading.Event],
    thread_name: str,
    psycho_plan: Optional[Any],
) -> bool:
    del config
    return brush(
        driver,
        ctx,
        stop_signal=stop_signal,
        thread_name=thread_name,
        psycho_plan=psycho_plan,
    )
