from typing import Any, List

from software.core.psychometrics.ordinal_options import infer_ordinal_option_mapping



PSYCHO_SUPPORTED_TYPES = {"scale", "score", "dropdown", "matrix"}


BIAS_PRESET_CHOICES = [
    ("left", "偏左"),
    ("center", "居中"),
    ("right", "偏右"),
    ("custom", "自定义"),
]


def build_bias_weights(option_count: int, bias: str) -> List[float]:
    
    import math

    count = max(1, int(option_count or 1))
    if count == 1:
        return [100.0]
    
    if bias == "left":
        linear = [1.0 - i / (count - 1) for i in range(count)]
    elif bias == "right":
        linear = [i / (count - 1) for i in range(count)]
    else:
        
        center = (count - 1) / 2.0
        linear = [1.0 - abs(i - center) / center for i in range(count)]
    
    power = 3 if bias == "center" else 8
    raw = [math.pow(v, power) for v in linear]
    max_val = max(raw)
    if not max_val:
        return [round(100 / count)] * count
    return [round(v / max_val * 100) for v in raw]


def entry_supports_psycho_presets(entry: Any, option_texts: List[str] | None = None) -> bool:
    question_type = str(getattr(entry, "question_type", "") or "").strip().lower()
    if question_type in PSYCHO_SUPPORTED_TYPES:
        return True
    if question_type != "single":
        return False
    return infer_ordinal_option_mapping(option_texts or []) is not None
