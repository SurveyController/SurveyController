import json
import re
from typing import Any, Optional, Tuple

from software.app.config import (
    _CHINESE_MULTI_EXACT_PATTERNS,
    _CHINESE_MULTI_LIMIT_PATTERNS,
    _CHINESE_MULTI_MIN_PATTERNS,
    _CHINESE_MULTI_RANGE_PATTERNS,
    _ENGLISH_MULTI_EXACT_PATTERNS,
    _ENGLISH_MULTI_LIMIT_PATTERNS,
    _ENGLISH_MULTI_MIN_PATTERNS,
    _ENGLISH_MULTI_RANGE_PATTERNS,
    _MULTI_LIMIT_ATTRIBUTE_NAMES,
    _MULTI_LIMIT_VALUE_KEYSET,
    _MULTI_MIN_LIMIT_ATTRIBUTE_NAMES,
    _MULTI_MIN_LIMIT_VALUE_KEYSET,
    _SELECTION_KEYWORDS_CN,
    _SELECTION_KEYWORDS_EN,
)
from software.providers.match_utils import get_element_attribute, normalize_match_text


def _compile_key_value_patterns(keys) -> tuple[re.Pattern[str], ...]:
    return tuple(
        re.compile(rf"{re.escape(str(key))}\s*[:=]\s*(\d+)", re.IGNORECASE)
        for key in sorted(keys)
    )


_MULTI_MIN_VALUE_PATTERNS = _compile_key_value_patterns(_MULTI_MIN_LIMIT_VALUE_KEYSET)
_MULTI_MAX_VALUE_PATTERNS = _compile_key_value_patterns(_MULTI_LIMIT_VALUE_KEYSET)

def _safe_positive_int(value: Any) -> Optional[int]:
    
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        int_value = int(value)
        return int_value if int_value > 0 else None
    text = normalize_match_text(value)
    if not text:
        return None
    if text.isdigit():
        int_value = int(text)
        return int_value if int_value > 0 else None
    match = re.search(r"(\d+)", text)
    if match:
        int_value = int(match.group(1))
        return int_value if int_value > 0 else None
    return None

def _extract_range_from_json_obj(obj: Any) -> Tuple[Optional[int], Optional[int]]:
    
    min_limit: Optional[int] = None
    max_limit: Optional[int] = None
    if isinstance(obj, dict):
        for key, value in obj.items():
            normalized_key = str(key).lower()
            if normalized_key in _MULTI_MIN_LIMIT_VALUE_KEYSET:
                candidate = _safe_positive_int(value)
                if candidate:
                    min_limit = min_limit or candidate
            if normalized_key in _MULTI_LIMIT_VALUE_KEYSET:
                candidate = _safe_positive_int(value)
                if candidate:
                    max_limit = max_limit or candidate
            nested_min, nested_max = _extract_range_from_json_obj(value)
            if min_limit is None and nested_min is not None:
                min_limit = nested_min
            if max_limit is None and nested_max is not None:
                max_limit = nested_max
            if min_limit is not None and max_limit is not None:
                break
    elif isinstance(obj, list):
        for item in obj:
            nested_min, nested_max = _extract_range_from_json_obj(item)
            if min_limit is None and nested_min is not None:
                min_limit = nested_min
            if max_limit is None and nested_max is not None:
                max_limit = nested_max
            if min_limit is not None and max_limit is not None:
                break
    return min_limit, max_limit

def _extract_range_from_possible_json(text: Optional[str]) -> Tuple[Optional[int], Optional[int]]:
    
    min_limit: Optional[int] = None
    max_limit: Optional[int] = None
    if not text:
        return min_limit, max_limit
    normalized = normalize_match_text(text)
    if not normalized:
        return min_limit, max_limit
    candidates = [normalized]
    if normalized.startswith("{") and "'" in normalized and '"' not in normalized:
        candidates.append(normalized.replace("'", '"'))
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except Exception:
            continue
        cand_min, cand_max = _extract_range_from_json_obj(parsed)
        if min_limit is None and cand_min is not None:
            min_limit = cand_min
        if max_limit is None and cand_max is not None:
            max_limit = cand_max
        if min_limit is not None and max_limit is not None:
            return min_limit, max_limit
    for pattern in _MULTI_MIN_VALUE_PATTERNS:
        match = pattern.search(normalized)
        if match:
            candidate = _safe_positive_int(match.group(1))
            if candidate:
                min_limit = min_limit or candidate
                if max_limit is not None:
                    return min_limit, max_limit
    for pattern in _MULTI_MAX_VALUE_PATTERNS:
        match = pattern.search(normalized)
        if match:
            candidate = _safe_positive_int(match.group(1))
            if candidate:
                max_limit = max_limit or candidate
                if min_limit is not None:
                    return min_limit, max_limit
    return min_limit, max_limit

def _extract_min_max_from_attributes(element) -> Tuple[Optional[int], Optional[int]]:
    
    min_limit = None
    max_limit = None
    for attr in _MULTI_MIN_LIMIT_ATTRIBUTE_NAMES:
        raw_value = get_element_attribute(element, attr)
        candidate = _safe_positive_int(raw_value)
        if candidate:
            min_limit = candidate
            break
    for attr in _MULTI_LIMIT_ATTRIBUTE_NAMES:
        raw_value = get_element_attribute(element, attr)
        candidate = _safe_positive_int(raw_value)
        if candidate:
            max_limit = candidate
            break
    return min_limit, max_limit

def _extract_multi_limit_range_from_text(text: Optional[str]) -> Tuple[Optional[int], Optional[int]]:
    
    if not text:
        return None, None
    normalized = normalize_match_text(text)
    if not normalized:
        return None, None
    normalized_lower = normalized.lower()
    min_limit: Optional[int] = None
    max_limit: Optional[int] = None
    contains_cn_keyword = any(keyword in normalized for keyword in _SELECTION_KEYWORDS_CN)
    contains_en_keyword = any(keyword in normalized_lower for keyword in _SELECTION_KEYWORDS_EN)
    contains_cn_min_hint = any(keyword in normalized for keyword in ("至少", "最少", "不少于"))
    contains_cn_max_hint = any(keyword in normalized for keyword in ("最多", "至多", "不超过", "不超過", "限选", "限選"))
    contains_en_min_hint = any(keyword in normalized_lower for keyword in ("at least", "minimum"))
    contains_en_max_hint = any(keyword in normalized_lower for keyword in ("up to", "at most", "no more than"))
    if contains_cn_keyword:
        for pattern in _CHINESE_MULTI_RANGE_PATTERNS:
            match = pattern.search(normalized)
            if match:
                first = _safe_positive_int(match.group(1))
                second = _safe_positive_int(match.group(2))
                if first and second:
                    min_limit = min(first, second)
                    max_limit = max(first, second)
                    break
    if min_limit is None and max_limit is None and contains_cn_keyword and not contains_cn_min_hint and not contains_cn_max_hint:
        for pattern in _CHINESE_MULTI_EXACT_PATTERNS:
            match = pattern.search(normalized)
            if match:
                candidate = _safe_positive_int(match.group(1))
                if candidate:
                    min_limit = candidate
                    max_limit = candidate
                    break
    if min_limit is None and max_limit is None and contains_en_keyword:
        for pattern in _ENGLISH_MULTI_RANGE_PATTERNS:
            match = pattern.search(normalized)
            if match:
                first = _safe_positive_int(match.group(1))
                second = _safe_positive_int(match.group(2))
                if first and second:
                    min_limit = min(first, second)
                    max_limit = max(first, second)
                    break
    if min_limit is None and max_limit is None and contains_en_keyword and not contains_en_min_hint and not contains_en_max_hint:
        for pattern in _ENGLISH_MULTI_EXACT_PATTERNS:
            match = pattern.search(normalized_lower)
            if match:
                candidate = _safe_positive_int(match.group(1))
                if candidate:
                    min_limit = candidate
                    max_limit = candidate
                    break
    if min_limit is None and contains_cn_keyword:
        for pattern in _CHINESE_MULTI_MIN_PATTERNS:
            match = pattern.search(normalized)
            if match:
                candidate = _safe_positive_int(match.group(1))
                if candidate:
                    min_limit = candidate
                    break
    if max_limit is None and contains_cn_keyword:
        for pattern in _CHINESE_MULTI_LIMIT_PATTERNS:
            match = pattern.search(normalized)
            if match:
                candidate = _safe_positive_int(match.group(1))
                if candidate:
                    max_limit = candidate
                    break
    if min_limit is None and contains_en_keyword:
        for pattern in _ENGLISH_MULTI_MIN_PATTERNS:
            match = pattern.search(normalized_lower)
            if match:
                candidate = _safe_positive_int(match.group(1))
                if candidate:
                    min_limit = candidate
                    break
    if max_limit is None and contains_en_keyword:
        for pattern in _ENGLISH_MULTI_LIMIT_PATTERNS:
            match = pattern.search(normalized_lower)
            if match:
                candidate = _safe_positive_int(match.group(1))
                if candidate:
                    max_limit = candidate
                    break
    if min_limit is not None and max_limit is not None and min_limit > max_limit:
        min_limit, max_limit = max_limit, min_limit
    return min_limit, max_limit
