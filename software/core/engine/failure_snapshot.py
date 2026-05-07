"""Submission failure snapshot capture."""

from __future__ import annotations

import json
import logging
import os
import re
import time
from typing import Any, Optional

from software.app.user_paths import get_user_logs_directory
from software.logging.log_utils import log_suppressed_exception
from software.network.browser import BrowserDriver


_MAX_NAME_PART_LENGTH = 48


def _safe_name_part(value: Any, fallback: str) -> str:
    text = str(value or "").strip() or fallback
    text = re.sub(r"[^0-9A-Za-z._-]+", "_", text)
    text = text.strip("._-") or fallback
    return text[:_MAX_NAME_PART_LENGTH]


def _ensure_unique_directory(path: str) -> str:
    candidate = path
    index = 2
    while os.path.exists(candidate):
        candidate = f"{path}_{index}"
        index += 1
    os.makedirs(candidate, exist_ok=False)
    return candidate


def _safe_driver_attr(driver: BrowserDriver, attr_name: str) -> str:
    try:
        return str(getattr(driver, attr_name, "") or "")
    except Exception:
        return ""


def _write_text(path: str, value: Any) -> None:
    with open(path, "w", encoding="utf-8", errors="replace") as handle:
        handle.write("" if value is None else str(value))


def _write_json(path: str, value: Any) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, default=str)


def _run_script(driver: BrowserDriver, script: str) -> Any:
    try:
        return driver.execute_script(script)
    except Exception as exc:
        log_suppressed_exception("failure_snapshot.execute_script", exc, level=logging.WARNING)
        return None


def _capture_screenshot(driver: BrowserDriver, screenshot_path: str) -> Optional[str]:
    page = None
    try:
        page = getattr(driver, "page", None)
    except Exception as exc:
        log_suppressed_exception("failure_snapshot.get_page", exc, level=logging.WARNING)

    if page is not None:
        screenshot = getattr(page, "screenshot", None)
        if callable(screenshot):
            try:
                screenshot(path=screenshot_path, full_page=True, timeout=15000)
                return screenshot_path
            except TypeError:
                try:
                    screenshot(path=screenshot_path, full_page=True)
                    return screenshot_path
                except Exception as exc:
                    log_suppressed_exception("failure_snapshot.page_screenshot_fallback", exc, level=logging.WARNING)
            except Exception as exc:
                log_suppressed_exception("failure_snapshot.page_screenshot", exc, level=logging.WARNING)

    save_screenshot = getattr(driver, "save_screenshot", None)
    if callable(save_screenshot):
        try:
            if save_screenshot(screenshot_path):
                return screenshot_path
        except Exception as exc:
            log_suppressed_exception("failure_snapshot.driver_save_screenshot", exc, level=logging.WARNING)

    return None


_VISIBLE_TEXT_SCRIPT = """
return document.body ? document.body.innerText : "";
"""


_ERROR_STATE_SCRIPT = r"""
return (() => {
  const clean = (value, limit = 1000) => String(value || "")
    .replace(/\s+/g, " ")
    .trim()
    .slice(0, limit);

  const isVisible = (el) => {
    if (!el) return false;
    const style = window.getComputedStyle ? window.getComputedStyle(el) : null;
    if (style && (style.display === "none" || style.visibility === "hidden" || Number(style.opacity) === 0)) {
      return false;
    }
    return !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length);
  };

  const fieldFor = (el) => el && el.closest
    ? el.closest(".field[topic], [topic][id^='div'], .field")
    : null;

  const titleFor = (field) => {
    if (!field) return "";
    const title = field.querySelector(".topichtml") || field.querySelector(".field-label");
    return clean(title ? title.innerText : field.innerText, 600);
  };

  const fieldIdFor = (field) => {
    if (!field) return "";
    const topic = field.getAttribute("topic") || "";
    if (topic) return topic;
    const id = field.id || "";
    const match = /^div(\d+)$/i.exec(id);
    return match ? match[1] : id;
  };

  const valueFor = (el) => {
    if (!el) return "";
    const tag = String(el.tagName || "").toLowerCase();
    const type = String(el.type || "").toLowerCase();
    if (tag === "select") {
      return clean(Array.from(el.selectedOptions || []).map((opt) => opt.textContent || opt.value).join("|"), 500);
    }
    if (type === "checkbox" || type === "radio") {
      return el.checked ? "checked" : "";
    }
    return clean(el.value || el.getAttribute("value") || "", 500);
  };

  const inputInfo = (input) => ({
    id: input.id || "",
    name: input.name || "",
    type: input.type || input.tagName || "",
    rel: input.getAttribute("rel") || "",
    visible: isVisible(input),
    checked: !!input.checked,
    value: valueFor(input),
  });

  const selectedLabelsFor = (field) => Array.from(field.querySelectorAll(
    ".jqchecked, .jqradioed, .on, .cur, .rate-on, .rate-onlarge, input:checked"
  )).map((el) => {
    if (el.matches && el.matches("input")) {
      const label = field.querySelector(`[for='${el.id}']`);
      return clean(label ? label.innerText : el.value, 300);
    }
    return clean(el.innerText || el.getAttribute("title") || el.getAttribute("val") || el.value, 300);
  }).filter(Boolean);

  const visibleErrorNodes = Array.from(document.querySelectorAll(
    ".errorMessage, .layui-layer-content, .ui-dialog-content, .validate-error, .error, [role='alert']"
  )).filter(isVisible);

  const visibleErrors = visibleErrorNodes.map((el) => {
    const field = fieldFor(el);
    return {
      text: clean(el.innerText || el.textContent, 1200),
      selector: el.id ? `#${el.id}` : clean(el.className || el.tagName, 200),
      fieldTopic: fieldIdFor(field),
      fieldId: field ? field.id || "" : "",
      fieldType: field ? field.getAttribute("type") || "" : "",
      fieldTitle: titleFor(field),
    };
  }).filter((item) => item.text);

  const allFields = Array.from(document.querySelectorAll(".field[topic], [topic][id^='div']"));
  const markedFields = allFields.map((field) => {
    const styleText = `${field.getAttribute("style") || ""} ${field.style ? field.style.cssText || "" : ""}`.toLowerCase();
    const errors = Array.from(field.querySelectorAll(".errorMessage, .validate-error, [role='alert']"))
      .filter(isVisible)
      .map((el) => clean(el.innerText || el.textContent, 1000))
      .filter(Boolean);
    const borderRed = styleText.includes("255, 64, 64")
      || styleText.includes("255,64,64")
      || styleText.includes("#ff4040")
      || styleText.includes("red");
    const inputs = Array.from(field.querySelectorAll("textarea, input, select")).map(inputInfo);
    const selectedLabels = selectedLabelsFor(field);
    return {
      topic: fieldIdFor(field),
      id: field.id || "",
      type: field.getAttribute("type") || "",
      required: field.getAttribute("req") === "1" || !!field.querySelector(".req"),
      visible: isVisible(field),
      borderRed,
      title: titleFor(field),
      errors,
      selectedLabels,
      inputs,
    };
  }).filter((field) => field.borderRed || field.errors.length > 0);

  return {
    href: window.location.href,
    title: document.title,
    viewport: {
      width: window.innerWidth,
      height: window.innerHeight,
      scrollX: window.scrollX,
      scrollY: window.scrollY,
      documentHeight: Math.max(
        document.body ? document.body.scrollHeight : 0,
        document.documentElement ? document.documentElement.scrollHeight : 0
      ),
    },
    visibleErrors,
    markedFields,
  };
})();
"""


def capture_submission_failure_snapshot(
    driver: BrowserDriver,
    *,
    thread_name: str = "",
    provider: str = "",
    reason: str = "submission_failure",
) -> Optional[str]:
    """Capture page artifacts that help diagnose a failed submission."""

    try:
        root_dir = os.path.join(get_user_logs_directory(), "submission_snapshots")
        os.makedirs(root_dir, exist_ok=True)
        timestamp = time.strftime("%Y%m%d-%H%M%S")
        directory_name = "_".join(
            (
                timestamp,
                _safe_name_part(thread_name, "thread"),
                _safe_name_part(provider, "provider"),
                _safe_name_part(reason, "failure"),
            )
        )
        snapshot_dir = _ensure_unique_directory(os.path.join(root_dir, directory_name))
    except Exception as exc:
        log_suppressed_exception("failure_snapshot.prepare_directory", exc, level=logging.WARNING)
        return None

    meta: dict[str, Any] = {
        "captured_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "thread_name": thread_name,
        "provider": provider,
        "reason": reason,
        "current_url": _safe_driver_attr(driver, "current_url"),
        "title": _safe_driver_attr(driver, "title"),
        "files": {},
        "capture_errors": [],
    }

    def capture_step(label: str, callback: Any) -> None:
        try:
            callback()
        except Exception as exc:
            meta["capture_errors"].append({"step": label, "error": str(exc)})
            log_suppressed_exception(f"failure_snapshot.{label}", exc, level=logging.WARNING)

    def save_html() -> None:
        path = os.path.join(snapshot_dir, "page.html")
        _write_text(path, _safe_driver_attr(driver, "page_source"))
        meta["files"]["html"] = path

    def save_visible_text() -> None:
        path = os.path.join(snapshot_dir, "visible_text.txt")
        _write_text(path, _run_script(driver, _VISIBLE_TEXT_SCRIPT))
        meta["files"]["visible_text"] = path

    def save_errors() -> None:
        path = os.path.join(snapshot_dir, "errors.json")
        _write_json(path, _run_script(driver, _ERROR_STATE_SCRIPT) or {})
        meta["files"]["errors"] = path

    def save_screenshot() -> None:
        path = os.path.join(snapshot_dir, "full_page.png")
        saved_path = _capture_screenshot(driver, path)
        if saved_path:
            meta["files"]["screenshot"] = saved_path
        else:
            meta["capture_errors"].append({"step": "screenshot", "error": "screenshot_not_available"})

    capture_step("html", save_html)
    capture_step("visible_text", save_visible_text)
    capture_step("errors", save_errors)
    capture_step("screenshot", save_screenshot)

    try:
        _write_json(os.path.join(snapshot_dir, "meta.json"), meta)
    except Exception as exc:
        log_suppressed_exception("failure_snapshot.meta", exc, level=logging.WARNING)

    return snapshot_dir


__all__ = ["capture_submission_failure_snapshot"]
