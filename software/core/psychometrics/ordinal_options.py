from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, List, Optional


@dataclass(frozen=True)
class OrdinalOptionMapping:
    score_by_choice_index: List[int]

    @property
    def option_count(self) -> int:
        return len(self.score_by_choice_index)


_NUMERIC_RE = re.compile(r"^\s*(\d+)(?:\s*(?:分|点|级|星))?\s*$")
_CHINESE_NUMBERS = {
    "一": 1,
    "二": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "十": 10,
}

_ORDINAL_GROUPS = [
    ["非常不满意", "不满意", "一般", "满意", "非常满意"],
    ["很不满意", "不满意", "一般", "满意", "很满意"],
    ["非常不同意", "不同意", "一般", "同意", "非常同意"],
    ["很不同意", "不同意", "一般", "同意", "很同意"],
    ["很差", "较差", "一般", "较好", "很好"],
    ["非常差", "差", "一般", "好", "非常好"],
    ["从不", "偶尔", "有时", "经常", "总是"],
    ["完全没有", "较少", "一般", "较多", "非常多"],
]

_ATTITUDE_NEUTRAL_TEXTS = frozenset({"一般", "中立", "没意见", "无意见", "普通", "不好说", "说不清", "不确定"})
_ATTITUDE_EXTREME_MARKERS = ("非常", "很", "极其", "十分", "完全", "特别", "强烈")
_ATTITUDE_MILD_MARKERS = ("比较", "较", "不太", "有点", "稍微", "略", "有些")
_ATTITUDE_NEGATIVE_CORES = (
    "不同意",
    "不满意",
    "不认可",
    "不支持",
    "不愿意",
    "不赞成",
    "不太同意",
    "不太满意",
    "不太认可",
    "不太支持",
    "不太愿意",
    "不太赞成",
    "不太好",
    "反对",
    "不好",
    "不佳",
    "差",
    "没有",
    "少",
    "较少",
    "很少",
    "从不",
)
_ATTITUDE_POSITIVE_CORES = (
    "同意",
    "满意",
    "认可",
    "支持",
    "愿意",
    "赞成",
    "好",
    "多",
    "经常",
    "总是",
)


def _normalize_option_text(value: object) -> str:
    text = str(value or "").strip()
    return re.sub(r"\s+", "", text)


def _parse_numeric_options(texts: List[str]) -> Optional[List[int]]:
    values: List[int] = []
    for text in texts:
        match = _NUMERIC_RE.match(text)
        if not match:
            return None
        values.append(int(match.group(1)))
    if len(values) < 2:
        return None
    if values == list(range(values[0], values[0] + len(values))):
        return [value - min(values) for value in values]
    if values == list(range(values[0], values[0] - len(values), -1)):
        max_value = max(values)
        return [max_value - value for value in values]
    return None


def _parse_chinese_numeric_options(texts: List[str]) -> Optional[List[int]]:
    values: List[int] = []
    for text in texts:
        value = text.removesuffix("分").removesuffix("点").removesuffix("级").removesuffix("星")
        if value not in _CHINESE_NUMBERS:
            return None
        values.append(_CHINESE_NUMBERS[value])
    if len(values) < 2:
        return None
    if values == list(range(values[0], values[0] + len(values))):
        return [value - min(values) for value in values]
    if values == list(range(values[0], values[0] - len(values), -1)):
        max_value = max(values)
        return [max_value - value for value in values]
    return None


def _match_text_group(texts: List[str]) -> Optional[List[int]]:
    if len(texts) < 2:
        return None
    for group in _ORDINAL_GROUPS:
        normalized_group = [_normalize_option_text(item) for item in group]
        if texts == normalized_group[: len(texts)]:
            return list(range(len(texts)))
        if texts == list(reversed(normalized_group[-len(texts) :])):
            return list(reversed(range(len(texts))))
        if len(texts) == len(normalized_group) and texts == list(reversed(normalized_group)):
            return list(reversed(range(len(texts))))
    return None


def _match_attitude_scale(texts: List[str]) -> Optional[List[int]]:
    if len(texts) != 5:
        return None

    scores: List[int] = []
    for text in texts:
        score = _score_attitude_option(text)
        if score is None:
            return None
        scores.append(score)
    if sorted(scores) != list(range(5)):
        return None
    return scores


def _score_attitude_option(text: str) -> Optional[int]:
    if text in _ATTITUDE_NEUTRAL_TEXTS:
        return 2

    is_negative = any(core in text for core in _ATTITUDE_NEGATIVE_CORES)
    is_positive = (not is_negative) and any(core in text for core in _ATTITUDE_POSITIVE_CORES)
    if not is_negative and not is_positive:
        return None

    is_extreme = any(marker in text for marker in _ATTITUDE_EXTREME_MARKERS)
    is_mild = any(marker in text for marker in _ATTITUDE_MILD_MARKERS)
    if is_negative:
        return 0 if is_extreme and not is_mild else 1
    return 4 if is_extreme and not is_mild else 3


def infer_ordinal_option_mapping(option_texts: Iterable[object]) -> Optional[OrdinalOptionMapping]:
    texts = [_normalize_option_text(item) for item in list(option_texts or [])]
    texts = [text for text in texts if text]
    if len(texts) < 2:
        return None

    score_by_choice_index = (
        _parse_numeric_options(texts)
        or _parse_chinese_numeric_options(texts)
        or _match_text_group(texts)
        or _match_attitude_scale(texts)
    )
    if score_by_choice_index is None:
        return None
    if len(score_by_choice_index) != len(texts):
        return None
    if sorted(score_by_choice_index) != list(range(len(texts))):
        return None
    return OrdinalOptionMapping(score_by_choice_index=score_by_choice_index)


__all__ = ["OrdinalOptionMapping", "infer_ordinal_option_mapping"]
