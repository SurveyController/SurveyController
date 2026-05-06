"""心理测量方向推断工具。

核心原则：
1. 先看最终目标配比长什么样，再判断题目更偏左、偏右还是居中。
2. 维度主方向按偏斜强度累计决定，不再按题目数量硬猜。
3. 反向题只从最终配比推断，不把快捷预设当题目语义真相。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Dict, List, Set

_LEFT_DIRECTION_THRESHOLD = 0.4
_RIGHT_DIRECTION_THRESHOLD = 0.6
_ANCHOR_DOMINANCE_MULTIPLIER = 1.15
_MIN_ANCHOR_STRENGTH = 0.2


def normalize_probability_list(values: List[float]) -> List[float]:
    cleaned: List[float] = []
    for raw in values:
        try:
            value = max(0.0, float(raw))
        except Exception:
            value = 0.0
        if math.isnan(value) or math.isinf(value):
            value = 0.0
        cleaned.append(value)

    total = sum(cleaned)
    if total <= 0.0:
        if not cleaned:
            return []
        return [1.0 / len(cleaned)] * len(cleaned)
    return [item / total for item in cleaned]


def build_bias_target_probabilities(option_count: int, bias: str) -> List[float]:
    """根据预设方向生成默认目标配比。

    这里只是“快捷生成配比”的工具，不代表题目语义。
    """
    count = max(2, int(option_count or 2))
    if count == 2:
        if bias == "left":
            return [0.75, 0.25]
        if bias == "right":
            return [0.25, 0.75]
        return [0.5, 0.5]

    if bias == "left":
        linear = [1.0 - i / (count - 1) for i in range(count)]
    elif bias == "right":
        linear = [i / (count - 1) for i in range(count)]
    else:
        center = (count - 1) / 2.0
        linear = [1.0 - abs(i - center) / max(center, 1.0) for i in range(count)]

    power = 3 if bias == "center" else 8
    raw = [math.pow(max(value, 0.0), power) for value in linear]
    return normalize_probability_list(raw)


def _resolve_choice_key(item: Any) -> str:
    try:
        key = str(getattr(item, "choice_key", "") or "").strip()
    except Exception:
        key = ""
    return key


def _resolve_option_count(item: Any) -> int:
    try:
        option_count = int(getattr(item, "option_count", 0) or 0)
    except Exception:
        option_count = 0
    return max(2, option_count)


def _resolve_target_probabilities(item: Any) -> List[float]:
    raw_values = getattr(item, "target_probabilities", None)
    if isinstance(raw_values, list) and raw_values:
        return normalize_probability_list(raw_values)

    bias = str(getattr(item, "bias", "center") or "center").strip().lower()
    if bias not in {"left", "center", "right"}:
        bias = "center"
    return build_bias_target_probabilities(_resolve_option_count(item), bias)


def _compute_mean_ratio(probabilities: List[float], option_count: int) -> float:
    if not probabilities:
        return 0.5
    denom = max(1, int(option_count) - 1)
    weighted_mean = sum(index * weight for index, weight in enumerate(probabilities))
    return max(0.0, min(1.0, weighted_mean / denom))


def _direction_from_ratio(mean_ratio: float) -> str:
    if mean_ratio <= _LEFT_DIRECTION_THRESHOLD:
        return "left"
    if mean_ratio >= _RIGHT_DIRECTION_THRESHOLD:
        return "right"
    return "center"


@dataclass(frozen=True)
class PsychometricItemOrientation:
    choice_key: str
    mean_ratio: float
    direction: str
    skew_strength: float
    option_count: int


@dataclass(frozen=True)
class PsychometricDimensionOrientation:
    item_orientations: Dict[str, PsychometricItemOrientation]
    anchor_direction: str
    anchor_strength: float
    left_strength: float
    right_strength: float
    reversed_keys: Set[str]
    ambiguous_anchor: bool


def infer_item_orientation(item: Any) -> PsychometricItemOrientation:
    option_count = _resolve_option_count(item)
    probabilities = _resolve_target_probabilities(item)
    mean_ratio = _compute_mean_ratio(probabilities, option_count)
    direction = _direction_from_ratio(mean_ratio)
    return PsychometricItemOrientation(
        choice_key=_resolve_choice_key(item),
        mean_ratio=mean_ratio,
        direction=direction,
        skew_strength=abs(mean_ratio - 0.5),
        option_count=option_count,
    )


def infer_dimension_orientation(items: List[Any]) -> PsychometricDimensionOrientation:
    item_orientations: Dict[str, PsychometricItemOrientation] = {}
    left_strength = 0.0
    right_strength = 0.0

    for item in items or []:
        orientation = infer_item_orientation(item)
        item_orientations[orientation.choice_key] = orientation
        if orientation.direction == "left":
            left_strength += orientation.skew_strength
        elif orientation.direction == "right":
            right_strength += orientation.skew_strength

    if left_strength > right_strength:
        anchor_direction = "left"
        anchor_strength = left_strength
        weaker_strength = right_strength
    elif right_strength > left_strength:
        anchor_direction = "right"
        anchor_strength = right_strength
        weaker_strength = left_strength
    else:
        anchor_direction = "center"
        anchor_strength = left_strength
        weaker_strength = right_strength

    ambiguous_anchor = (
        anchor_direction == "center"
        or anchor_strength < _MIN_ANCHOR_STRENGTH
        or anchor_strength <= weaker_strength * _ANCHOR_DOMINANCE_MULTIPLIER
    )

    reversed_keys: Set[str] = set()
    if not ambiguous_anchor:
        reversed_keys = {
            orientation.choice_key
            for orientation in item_orientations.values()
            if orientation.direction in {"left", "right"} and orientation.direction != anchor_direction
        }

    return PsychometricDimensionOrientation(
        item_orientations=item_orientations,
        anchor_direction=anchor_direction,
        anchor_strength=anchor_strength,
        left_strength=left_strength,
        right_strength=right_strength,
        reversed_keys=reversed_keys,
        ambiguous_anchor=ambiguous_anchor,
    )


__all__ = [
    "PsychometricDimensionOrientation",
    "PsychometricItemOrientation",
    "build_bias_target_probabilities",
    "infer_dimension_orientation",
    "infer_item_orientation",
    "normalize_probability_list",
]
