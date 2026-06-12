from __future__ import annotations

from typing import Any, Mapping, Optional, Sequence

from software.app.config import DEFAULT_FILL_TEXT
from software.core.questions.utils import (
    OPTION_FILL_AI_TOKEN,
    get_fill_text_from_config,
    resolve_dynamic_text_token,
)


def option_requires_fill(question: Any, option_index: int) -> bool:
    try:
        fillable_indices = list(getattr(question, "fillable_options", None) or question.get("fillable_options") or [])
    except Exception:
        fillable_indices = []
    for raw_index in fillable_indices:
        try:
            if int(raw_index) == int(option_index):
                return True
        except Exception:
            continue
    return False


def default_missing_option_fill(question: Any, option_index: int, fill_value: Optional[str]) -> Optional[str]:
    if str(fill_value or "").strip():
        return str(fill_value or "").strip()
    if option_requires_fill(question, option_index):
        return DEFAULT_FILL_TEXT
    return None


def option_fill_text_map(option_fill_texts: Sequence[tuple[int, str]] | None) -> dict[int, str]:
    result: dict[int, str] = {}
    for raw_index, raw_value in tuple(option_fill_texts or ()):
        try:
            option_index = int(raw_index)
        except Exception:
            continue
        value = str(raw_value or "").strip()
        if value:
            result[option_index] = value
    return result


def resolve_static_option_fill_text(
    fill_entries: Optional[Sequence[Optional[str]]],
    option_index: int,
    *,
    question: Any = None,
) -> Optional[str]:
    raw_value = get_fill_text_from_config(fill_entries, option_index)
    if raw_value is None:
        return default_missing_option_fill(question, option_index, None)
    text = str(raw_value).strip()
    if not text:
        return default_missing_option_fill(question, option_index, None)
    if text == OPTION_FILL_AI_TOKEN:
        return DEFAULT_FILL_TEXT
    return resolve_dynamic_text_token(text)


def mapping_contains_fillblank(value: Mapping[str, Any], *keys: str) -> bool:
    for key in keys:
        raw = value.get(key)
        if raw is not None and str(raw).strip():
            return True
    return False

