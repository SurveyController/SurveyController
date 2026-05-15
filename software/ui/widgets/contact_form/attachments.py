"""联系表单附件工具。"""

import os
from typing import Callable, Optional


def cleanup_pending_temp_files(
    paths: list[str],
    *,
    on_error: Callable[[str, Exception], None],
) -> list[str]:
    for path in list(paths):
        try:
            if path and os.path.exists(path):
                os.remove(path)
        except Exception as exc:
            on_error(path, exc)
    return []


def read_file_bytes(path: str) -> bytes:
    with open(path, "rb") as file:
        return file.read()


def remove_temp_file(
    path: str,
    *,
    on_error: Callable[[str, Exception], None],
) -> None:
    if not path:
        return
    try:
        if os.path.exists(path):
            os.remove(path)
    except Exception as exc:
        on_error(path, exc)


def fatal_crash_log_payload(path: str) -> Optional[tuple[str, tuple[str, bytes, str]]]:
    if not os.path.exists(path) or os.path.getsize(path) <= 0:
        return None
    with open(path, "rb") as file:
        data = file.read()
    return "fatal_crash.log", ("fatal_crash.log", data, "text/plain")


def renumber_files_payload(
    items: list[tuple[str, tuple[str, bytes, str]]],
) -> list[tuple[str, tuple[str, bytes, str]]]:
    payload: list[tuple[str, tuple[str, bytes, str]]] = []
    for index, (_, file_tuple) in enumerate(items, start=1):
        payload.append((f"file{index}", file_tuple))
    return payload


def build_bug_report_auto_files_payload(
    *,
    auto_attach_config: bool,
    auto_attach_log: bool,
    export_config_snapshot: Callable[[], tuple[str, tuple[str, bytes, str]]],
    export_log_snapshot: Callable[[], tuple[str, tuple[str, bytes, str]]],
    get_fatal_payload: Callable[[], Optional[tuple[str, tuple[str, bytes, str]]]],
) -> tuple[list[tuple[str, tuple[str, bytes, str]]], list[str]]:
    auto_files: list[tuple[str, tuple[str, bytes, str]]] = []
    config_status = "已附带" if auto_attach_config else "未附带"
    log_status = "已附带" if auto_attach_log else "未附带"
    summary_lines = [
        f"当前运行配置快照：{config_status}",
        f"当前日志快照：{log_status}",
    ]

    if auto_attach_config:
        auto_files.append(export_config_snapshot())

    if auto_attach_log:
        auto_files.append(export_log_snapshot())
        fatal_payload = get_fatal_payload()
        if fatal_payload is not None:
            auto_files.append(fatal_payload)
            summary_lines.append("fatal_crash.log：已附带")
        else:
            summary_lines.append("fatal_crash.log：未发现")
    else:
        summary_lines.append("fatal_crash.log：未附带")

    return auto_files, summary_lines
