from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path
from typing import List, Optional

from software.core.config.codec import (
    deserialize_runtime_config,
    serialize_runtime_config,
)
from software.core.config.schema import RuntimeConfig
from software.io.runtime_environment import (
    default_config_path as get_default_runtime_config_path,
    legacy_config_path as get_legacy_runtime_config_path,
)

__all__ = [
    "_sanitize_filename",
    "build_default_config_filename",
    "load_config",
    "save_config",
]


def _sanitize_filename(value: Optional[str], max_length: int = 80) -> str:
    normalized = "".join(ch for ch in (value or "") if ch.isprintable())
    normalized = normalized.strip().replace(" ", "_")
    sanitized = "".join(ch for ch in normalized if ch not in '\\/:*?"<>|')
    if not sanitized:
        return "wjx_config"
    return sanitized[:max_length]


def _default_config_path() -> str:
    return get_default_runtime_config_path()


def _default_config_read_path() -> str:
    current_path = _default_config_path()
    if os.path.exists(current_path):
        return current_path
    legacy_path = get_legacy_runtime_config_path()
    if legacy_path and os.path.exists(legacy_path):
        return legacy_path
    return current_path


def build_default_config_filename(survey_title: Optional[str] = None) -> str:
    title = _sanitize_filename(survey_title or "")
    if title:
        return f"{title}.json"
    return "wjx_config.json"


def _strip_json_comments(raw_text: str) -> str:
    text = str(raw_text or "").lstrip("\ufeff")
    if not text:
        return ""

    out: List[str] = []
    in_string = False
    escaped = False
    in_line_comment = False
    in_block_comment = False
    quote = '"'
    i = 0
    n = len(text)

    while i < n:
        ch = text[i]
        nxt = text[i + 1] if i + 1 < n else ""

        if in_line_comment:
            if ch == "\n":
                in_line_comment = False
                out.append(ch)
            i += 1
            continue

        if in_block_comment:
            if ch == "*" and nxt == "/":
                in_block_comment = False
                i += 2
            else:
                i += 1
            continue

        if in_string:
            out.append(ch)
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == quote:
                in_string = False
            i += 1
            continue

        if ch == '"':
            in_string = True
            quote = ch
            out.append(ch)
            i += 1
            continue

        if ch == "/" and nxt == "/":
            in_line_comment = True
            i += 2
            continue

        if ch == "/" and nxt == "*":
            in_block_comment = True
            i += 2
            continue

        out.append(ch)
        i += 1
    return "".join(out)


def load_config(path: Optional[str] = None, *, strict: bool = False) -> RuntimeConfig:

    config_path = os.fspath(path or _default_config_read_path())
    if not os.path.exists(config_path):
        return RuntimeConfig()
    try:
        with open(config_path, "r", encoding="utf-8") as fp:
            raw_text = fp.read()
        clean_text = _strip_json_comments(raw_text)
        if not clean_text.strip():
            default_path = os.path.abspath(_default_config_path())
            current_path = os.path.abspath(config_path)
            if not strict and current_path == default_path:
                try:
                    with open(config_path, "w", encoding="utf-8") as fp:
                        fp.write("{}\n")
                except Exception as repair_exc:
                    logging.info("自动修复空配置失败: %s -> %s", config_path, repair_exc)
            raise ValueError("配置文件为空")
        payload = json.loads(clean_text)
    except Exception as exc:
        error_message = f"读取配置失败: {config_path} -> {exc}"
        if strict:
            logging.error(error_message)
            raise ValueError(error_message) from exc
        logging.warning(error_message)
        return RuntimeConfig()

    if not isinstance(payload, dict):
        error_message = f"读取配置失败: {config_path} -> JSON 顶层必须是对象"
        if strict:
            raise ValueError(error_message)
        logging.warning(error_message)
        return RuntimeConfig()

    try:
        return deserialize_runtime_config(payload)
    except Exception as exc:
        error_message = f"配置不兼容: {config_path} -> {exc}"
        if strict:
            raise ValueError(error_message) from exc
        logging.warning(error_message)
        return RuntimeConfig()


def save_config(
    config: RuntimeConfig,
    path: Optional[str] = None,
    *,
    include_secrets: bool = False,
) -> str:

    config_path = os.fspath(path or _default_config_path())
    os.makedirs(os.path.dirname(config_path) or ".", exist_ok=True)
    payload = serialize_runtime_config(config, include_secrets=include_secrets)
    parent = os.path.dirname(config_path) or "."
    file_name = Path(config_path).name
    descriptor, temporary_path = tempfile.mkstemp(
        prefix=f".{file_name}.",
        suffix=".tmp",
        dir=parent,
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as fp:
            json.dump(payload, fp, ensure_ascii=False, indent=2)
            fp.write("\n")
            fp.flush()
            os.fsync(fp.fileno())
        os.replace(temporary_path, config_path)
    except BaseException:
        try:
            os.close(descriptor)
        except OSError:
            pass
        try:
            os.unlink(temporary_path)
        except FileNotFoundError:
            pass
        raise
    return config_path
