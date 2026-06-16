from __future__ import annotations

import copy
import logging
import random
from dataclasses import asdict, dataclass, fields
from typing import Any, Dict, List, Optional, Tuple

from software.core.reverse_fill import REVERSE_FILL_FORMAT_AUTO, REVERSE_FILL_FORMAT_WJX_SCORE, REVERSE_FILL_FORMAT_WJX_SEQUENCE, REVERSE_FILL_FORMAT_WJX_TEXT
from software.core.config.answer_datetime_window import normalize_answer_datetime_window
from software.core.config.schema import RuntimeConfig
from software.core.psychometrics.psychometric import normalize_target_alpha
from software.core.questions.consistency import normalize_rule_dict, sanitize_answer_rules
from software.core.questions.utils import serialize_random_int_range
from software.providers.common import (
    SURVEY_PROVIDER_WJX,
    detect_survey_provider,
    ensure_questions_provider_fields,
    normalize_survey_provider,
)
from software.providers.contracts import (
    SurveyQuestionMeta,
    clone_survey_question_metas,
    ensure_survey_question_metas,
    serialize_survey_question_metas,
)
from software.logging.log_utils import log_suppressed_exception
from software.app.config import USER_AGENT_PRESETS

_TEXT_RANDOM_MODES = {"none", "name", "mobile", "id_card", "integer"}
_REVERSE_FILL_FORMATS = {
    REVERSE_FILL_FORMAT_AUTO,
    REVERSE_FILL_FORMAT_WJX_SEQUENCE,
    REVERSE_FILL_FORMAT_WJX_SCORE,
    REVERSE_FILL_FORMAT_WJX_TEXT,
}
DEFAULT_ANSWER_DURATION_RANGE_SECONDS = (60, 120)
MAX_ANSWER_DURATION_SECONDS = 30 * 60
_DEFAULT_RANDOM_UA_RATIOS = {"wechat": 33, "mobile": 33, "pc": 34}
_USER_AGENT_DEVICE_TO_PRESET_KEYS = {
    "wechat": ["wechat_android"],
    "mobile": ["mobile_android"],
    "pc": ["pc_web"],
}


@dataclass(frozen=True)
class UserAgentProfile:
    category: str
    preset_key: str
    ua: str
    label: str

__all__ = [
    "CURRENT_CONFIG_SCHEMA_VERSION",
    "UserAgentProfile",
    "_select_user_agent_from_ratios",
    "serialize_question_entry",
    "deserialize_question_entry",
    "clone_question_entries",
    "clone_questions_info",
    "build_runtime_config_snapshot",
    "normalize_runtime_config_payload",
    "serialize_runtime_config",
    "deserialize_runtime_config",
    "_ensure_supported_config_payload",
]

_CONFIG_CORRUPTED_MESSAGE = "该配置文件损坏，请输入问卷链接/二维码重新配置"
CURRENT_CONFIG_SCHEMA_VERSION = 6

_QUESTION_ENTRY_FIELDS = {
    "question_type",
    "probabilities",
    "texts",
    "rows",
    "option_count",
    "distribution_mode",
    "custom_weights",
    "question_num",
    "question_title",
    "survey_provider",
    "provider_question_id",
    "provider_page_id",
    "ai_enabled",
    "multi_text_blank_modes",
    "multi_text_blank_ai_flags",
    "multi_text_blank_int_ranges",
    "text_random_mode",
    "text_random_int_range",
    "option_fill_texts",
    "fillable_option_indices",
    "attached_option_selects",
    "is_location",
    "location_parts",
    "dimension",
    "psycho_bias",
}

_SURVEY_QUESTION_META_FIELDS = {
    "num",
    "title",
    "display_num",
    "description",
    "type_code",
    "options",
    "rows",
    "row_texts",
    "page",
    "option_texts",
    "forced_option_index",
    "forced_option_text",
    "forced_texts",
    "fillable_options",
    "attached_option_selects",
    "has_attached_option_select",
    "is_location",
    "is_rating",
    "is_description",
    "rating_max",
    "text_inputs",
    "text_input_labels",
    "is_multi_text",
    "is_text_like",
    "is_slider_matrix",
    "has_jump",
    "jump_rules",
    "has_display_condition",
    "display_conditions",
    "has_dependent_display_logic",
    "controls_display_targets",
    "logic_parse_status",
    "question_media",
    "slider_min",
    "slider_max",
    "slider_step",
    "multi_min_limit",
    "multi_max_limit",
    "provider",
    "provider_question_id",
    "provider_page_id",
    "provider_type",
    "provider_page_raw",
    "unsupported",
    "unsupported_reason",
    "required",
}

_RUNTIME_CONFIG_FIELDS = {
    field.name for field in fields(RuntimeConfig) if not field.name.startswith("_")
}
_RUNTIME_CONFIG_FIELDS.update({"question_entries", "questions_info"})


def _coerce_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _normalize_user_agent_ratios(raw_ratios: Any) -> Dict[str, int]:
    if not isinstance(raw_ratios, dict):
        return dict(_DEFAULT_RANDOM_UA_RATIOS)

    ratios: Dict[str, int] = {}
    for device_type in _DEFAULT_RANDOM_UA_RATIOS:
        value = _coerce_int(raw_ratios.get(device_type), 0)
        if value < 0 or value > 100:
            return dict(_DEFAULT_RANDOM_UA_RATIOS)
        ratios[device_type] = value

    if sum(ratios.values()) != 100:
        return dict(_DEFAULT_RANDOM_UA_RATIOS)
    return ratios


def _select_user_agent_from_ratios(
    ratios: Dict[str, int],
    *,
    rng: Any = None,
) -> Optional[UserAgentProfile]:
    chooser = rng or random
    devices: List[str] = []
    weights: List[int] = []
    for device_type, ua_keys in _USER_AGENT_DEVICE_TO_PRESET_KEYS.items():
        if not ua_keys:
            continue
        weight = max(0, _coerce_int((ratios or {}).get(device_type), 0))
        if weight > 0:
            devices.append(device_type)
            weights.append(weight)
    if not devices:
        return None

    device_type = chooser.choices(devices, weights=weights, k=1)[0]
    ua_keys = _USER_AGENT_DEVICE_TO_PRESET_KEYS.get(device_type, [])
    if not ua_keys:
        return None

    key = chooser.choice(ua_keys)
    preset = USER_AGENT_PRESETS.get(key) or {}
    ua = str(preset.get("ua") or "").strip()
    label = str(preset.get("label") or "").strip()
    if not ua:
        return None
    return UserAgentProfile(
        category=str(device_type or "").strip(),
        preset_key=str(key or "").strip(),
        ua=ua,
        label=label,
    )


def _prob_config_is_unset(value: Any) -> bool:
    if value is None:
        return True
    if value == -1:
        return True
    if isinstance(value, (list, tuple)):
        if not value:
            return True
        for item in value:
            try:
                if float(item) > 0:
                    return False
            except Exception:
                continue
        return True
    return False


def _custom_weights_has_positive(weights: Any) -> bool:
    if not isinstance(weights, list) or not weights:
        return False
    stack: List[Any] = list(weights)
    while stack:
        item = stack.pop()
        if isinstance(item, list):
            stack.extend(item)
            continue
        try:
            if float(item) > 0:
                return True
        except Exception:
            continue
    return False


def _normalize_psycho_bias(data: Dict[str, Any]) -> str:
    bias = str(data.get("psycho_bias") or "custom")
    if bias in ("left", "center", "right"):
        return bias
    return "custom"


def _normalize_multi_text_blank_modes(raw: Any) -> List[str]:
    if not isinstance(raw, list):
        return []
    normalized: List[str] = []
    for item in raw:
        mode = str(item or "none").strip().lower()
        normalized.append(mode if mode in _TEXT_RANDOM_MODES else "none")
    return normalized


def _normalize_multi_text_blank_ai_flags(raw: Any) -> List[bool]:
    if not isinstance(raw, list):
        return []
    return [bool(item) for item in raw]


def _normalize_random_int_range(raw: Any) -> List[int]:
    if raw in (None, "", []):
        return []
    return serialize_random_int_range(raw)


def _normalize_multi_text_blank_int_ranges(raw: Any) -> List[List[int]]:
    if not isinstance(raw, list):
        return []
    return [_normalize_random_int_range(item) for item in raw]


def _legacy_answer_duration_to_range(value: int) -> Tuple[int, int]:
    normalized = min(MAX_ANSWER_DURATION_SECONDS, max(0, int(value or 0)))
    if normalized <= 0:
        return DEFAULT_ANSWER_DURATION_RANGE_SECONDS
    low = max(0, int(round(normalized * 0.9)))
    high = min(MAX_ANSWER_DURATION_SECONDS, max(low, int(round(normalized * 1.1))))
    return low, high


def _normalize_answer_duration_range(value: Any) -> Tuple[int, int]:
    if value in (None, "", []):
        return DEFAULT_ANSWER_DURATION_RANGE_SECONDS
    try:
        if isinstance(value, (list, tuple)):
            if len(value) >= 2:
                low = min(MAX_ANSWER_DURATION_SECONDS, max(0, int(value[0])))
                high = min(MAX_ANSWER_DURATION_SECONDS, max(low, int(value[1])))
                if low == 0 and high == 0:
                    return DEFAULT_ANSWER_DURATION_RANGE_SECONDS
                if low == high:
                    return _legacy_answer_duration_to_range(low)
                return low, high
            if len(value) == 1:
                return _legacy_answer_duration_to_range(int(value[0]))
            return DEFAULT_ANSWER_DURATION_RANGE_SECONDS
        return _legacy_answer_duration_to_range(int(value))
    except Exception as exc:
        log_suppressed_exception(
            "_normalize_answer_duration_range failure",
            exc,
            level=logging.WARNING,
        )
        return DEFAULT_ANSWER_DURATION_RANGE_SECONDS


def _normalize_dimension_value(raw: Any) -> Optional[str]:
    try:
        text = str(raw or "").strip()
    except Exception:
        text = ""
    if not text or text == "未分组":
        return None
    return text


def _normalize_dimension_groups(raw: Any) -> List[str]:
    if not isinstance(raw, list):
        return []
    groups: List[str] = []
    seen = set()
    for item in raw:
        normalized = _normalize_dimension_value(item)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        groups.append(normalized)
    return groups


def serialize_question_entry(entry) -> Dict[str, Any]:
    probabilities = entry.probabilities
    if (
        getattr(entry, "distribution_mode", None) == "custom"
        and _prob_config_is_unset(probabilities)
        and _custom_weights_has_positive(entry.custom_weights)
    ):
        probabilities = entry.custom_weights
    return {
        "question_type": entry.question_type,
        "probabilities": probabilities,
        "texts": entry.texts,
        "rows": entry.rows,
        "option_count": entry.option_count,
        "distribution_mode": entry.distribution_mode,
        "custom_weights": entry.custom_weights,
        "question_num": entry.question_num,
        "question_title": getattr(entry, "question_title", None),
        "survey_provider": normalize_survey_provider(getattr(entry, "survey_provider", None)),
        "provider_question_id": str(getattr(entry, "provider_question_id", None) or ""),
        "provider_page_id": str(getattr(entry, "provider_page_id", None) or ""),
        "ai_enabled": bool(getattr(entry, "ai_enabled", False)),
        "multi_text_blank_modes": _normalize_multi_text_blank_modes(getattr(entry, "multi_text_blank_modes", [])),
        "multi_text_blank_ai_flags": _normalize_multi_text_blank_ai_flags(getattr(entry, "multi_text_blank_ai_flags", [])),
        "multi_text_blank_int_ranges": _normalize_multi_text_blank_int_ranges(getattr(entry, "multi_text_blank_int_ranges", [])),
        "text_random_mode": str(getattr(entry, "text_random_mode", "none") or "none"),
        "text_random_int_range": _normalize_random_int_range(getattr(entry, "text_random_int_range", [])),
        "option_fill_texts": entry.option_fill_texts,
        "fillable_option_indices": entry.fillable_option_indices,
        "attached_option_selects": list(getattr(entry, "attached_option_selects", []) or []),
        "is_location": getattr(entry, "is_location", False),
        "location_parts": list(getattr(entry, "location_parts", []) or []),
        "dimension": _normalize_dimension_value(getattr(entry, "dimension", None)),
        "psycho_bias": str(getattr(entry, "psycho_bias", "custom") or "custom"),
    }


def deserialize_question_entry(data: Dict[str, Any]):
    from software.core.questions.config import QuestionEntry

    def _as_int(value: Any, default: int = 0) -> int:
        try:
            return int(value)
        except Exception:
            return default

    unknown_keys = set(data or {}) - _QUESTION_ENTRY_FIELDS
    if unknown_keys:
        raise ValueError(f"{_CONFIG_CORRUPTED_MESSAGE}：题目配置包含不支持的字段（{', '.join(sorted(unknown_keys))}）")
    mode_raw = data.get("distribution_mode") or "random"
    probabilities = data.get("probabilities")
    custom_weights = data.get("custom_weights")
    if mode_raw == "custom" and _prob_config_is_unset(probabilities) and _custom_weights_has_positive(custom_weights):
        probabilities = custom_weights
    if mode_raw == "custom" and (custom_weights is None or custom_weights == []) and isinstance(probabilities, list):
        custom_weights = list(probabilities)
    return QuestionEntry(
        question_type=data.get("question_type") or "text",
        probabilities=probabilities,
        texts=data.get("texts"),
        rows=_as_int(data.get("rows"), 1),
        option_count=_as_int(data.get("option_count"), 0),
        distribution_mode=mode_raw,
        custom_weights=custom_weights,
        question_num=data.get("question_num"),
        question_title=data.get("question_title"),
        survey_provider=normalize_survey_provider(
            data.get("survey_provider"),
            default=SURVEY_PROVIDER_WJX,
        ),
        provider_question_id=str(data.get("provider_question_id") or "").strip() or None,
        provider_page_id=str(data.get("provider_page_id") or "").strip() or None,
        ai_enabled=bool(data.get("ai_enabled", False)),
        multi_text_blank_modes=_normalize_multi_text_blank_modes(data.get("multi_text_blank_modes")),
        multi_text_blank_ai_flags=_normalize_multi_text_blank_ai_flags(data.get("multi_text_blank_ai_flags")),
        multi_text_blank_int_ranges=_normalize_multi_text_blank_int_ranges(data.get("multi_text_blank_int_ranges")),
        text_random_mode=str(data.get("text_random_mode") or "none"),
        text_random_int_range=_normalize_random_int_range(data.get("text_random_int_range")),
        option_fill_texts=data.get("option_fill_texts"),
        fillable_option_indices=data.get("fillable_option_indices"),
        attached_option_selects=list(data.get("attached_option_selects") or []),
        is_location=bool(data.get("is_location")),
        location_parts=list(data.get("location_parts") or []),
        dimension=_normalize_dimension_value(data.get("dimension")),
        psycho_bias=_normalize_psycho_bias(data),
    )


def clone_question_entries(entries: Any) -> List[Any]:
    cloned: List[Any] = []
    for item in list(entries or []):
        try:
            cloned.append(deserialize_question_entry(serialize_question_entry(item)))
        except Exception as exc:
            logging.info("跳过无法复制的题目配置: %s", exc)
    return cloned


def clone_questions_info(questions: Any, *, default_provider: str = SURVEY_PROVIDER_WJX) -> List[SurveyQuestionMeta]:
    return clone_survey_question_metas(questions or [], default_provider=default_provider)


def build_runtime_config_snapshot(
    config: RuntimeConfig,
    *,
    question_entries: Any = None,
    questions_info: Any = None,
) -> RuntimeConfig:
    snapshot = copy.deepcopy(config)
    default_provider = normalize_survey_provider(
        getattr(snapshot, "survey_provider", None),
        default=detect_survey_provider(getattr(snapshot, "url", "")),
    )
    snapshot.survey_provider = default_provider
    entry_source = question_entries if question_entries is not None else getattr(snapshot, "question_entries", [])
    info_source = questions_info if questions_info is not None else getattr(snapshot, "questions_info", [])
    snapshot.question_entries = clone_question_entries(entry_source)
    snapshot.questions_info = clone_questions_info(info_source, default_provider=default_provider)
    snapshot.answer_rules = copy.deepcopy(list(getattr(snapshot, "answer_rules", []) or []))
    snapshot.dimension_groups = copy.deepcopy(list(getattr(snapshot, "dimension_groups", []) or []))
    snapshot.random_ua_ratios = copy.deepcopy(dict(getattr(snapshot, "random_ua_ratios", {}) or {}))
    return snapshot


def normalize_runtime_config_payload(raw: Dict[str, Any]) -> RuntimeConfig:
    

    def _as_int(value: Any, default: int = 0) -> int:
        try:
            return int(value)
        except Exception:
            return default

    def _as_float(value: Any, default: float = 0.0) -> float:
        try:
            return float(value)
        except Exception:
            return default

    def _as_bool(value: Any, default: bool = False) -> bool:
        if value is None:
            return default
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)
        if isinstance(value, str):
            text = value.strip().lower()
            if text in {"1", "true", "yes", "on"}:
                return True
            if text in {"0", "false", "no", "off", ""}:
                return False
            return default
        return bool(value)

    def _tuple_pair(value: Any) -> Tuple[int, int]:
        try:
            if isinstance(value, (list, tuple)) and len(value) >= 2:
                return int(value[0]), int(value[1])
        except Exception as exc:
            log_suppressed_exception("_tuple_pair failure", exc, level=logging.WARNING)
        return 0, 0

    def _reverse_fill_format(value: Any) -> str:
        normalized = str(value or REVERSE_FILL_FORMAT_AUTO).strip().lower()
        return normalized if normalized in _REVERSE_FILL_FORMATS else REVERSE_FILL_FORMAT_AUTO

    config = RuntimeConfig()
    unknown_keys = set(raw or {}) - _RUNTIME_CONFIG_FIELDS
    if unknown_keys:
        raise ValueError(f"{_CONFIG_CORRUPTED_MESSAGE}：配置包含不支持的字段（{', '.join(sorted(unknown_keys))}）")
    config.url = str(raw.get("url") or "")
    config.survey_title = str(raw.get("survey_title") or "")
    config.survey_provider = normalize_survey_provider(
        raw.get("survey_provider"),
        default=detect_survey_provider(config.url),
    )
    config.target = _as_int(raw.get("target"), 1)
    config.threads = _as_int(raw.get("threads"), 1)
    config.submit_interval = _tuple_pair(raw.get("submit_interval"))
    config.answer_duration = _normalize_answer_duration_range(raw.get("answer_duration"))
    config.answer_datetime_window = normalize_answer_datetime_window(
        raw.get("answer_datetime_window")
    )
    custom_proxy_api = str(raw.get("custom_proxy_api") or "").strip()
    proxy_source = str(raw.get("proxy_source") or "default").strip().lower()
    if proxy_source not in ("default", "benefit", "custom"):
        proxy_source = "default"
    config.proxy_source = proxy_source
    config.custom_proxy_api = custom_proxy_api
    config.random_ip_enabled = _as_bool(raw.get("random_ip_enabled"), False)
    raw_area_code = raw.get("proxy_area_code")
    config.proxy_area_code = None if raw_area_code is None else str(raw_area_code)
    config.random_ua_enabled = _as_bool(raw.get("random_ua_enabled"), False)
    config.random_ua_ratios = _normalize_user_agent_ratios(raw.get("random_ua_ratios"))

    config.fail_stop_enabled = bool(raw.get("fail_stop_enabled", True))
    config.pause_on_aliyun_captcha = bool(raw.get("pause_on_aliyun_captcha", True))
    config.reliability_mode_enabled = bool(raw.get("reliability_mode_enabled", True))
    config.psycho_target_alpha = normalize_target_alpha(raw.get("psycho_target_alpha"))
    config.reverse_fill_enabled = _as_bool(raw.get("reverse_fill_enabled", False), False)
    config.reverse_fill_source_path = str(raw.get("reverse_fill_source_path") or "")
    config.reverse_fill_format = _reverse_fill_format(raw.get("reverse_fill_format"))
    config.reverse_fill_start_row = max(1, _as_int(raw.get("reverse_fill_start_row"), 1))
    config.reverse_fill_threads = max(1, _as_int(raw.get("reverse_fill_threads"), config.threads or 1))
    config.answer_rules = []
    config.dimension_groups = _normalize_dimension_groups(raw.get("dimension_groups"))
    raw_rules = raw.get("answer_rules")
    if isinstance(raw_rules, list):
        for item in raw_rules:
            normalized_rule = normalize_rule_dict(item)
            if normalized_rule:
                config.answer_rules.append(normalized_rule)

    ai_keys = {
        "ai_mode",
        "ai_provider",
        "ai_api_key",
        "ai_base_url",
        "ai_api_protocol",
        "ai_model",
        "ai_system_prompt",
    }
    has_ai_keys = any(key in raw for key in ai_keys)
    config._ai_config_present = has_ai_keys
    if has_ai_keys:
        config.ai_mode = str(raw.get("ai_mode") or "free").strip().lower()
        if config.ai_mode not in {"free", "provider"}:
            config.ai_mode = "free"
        config.ai_provider = str(raw.get("ai_provider") or "deepseek")
        config.ai_api_key = str(raw.get("ai_api_key") or "")
        config.ai_base_url = str(raw.get("ai_base_url") or "")
        config.ai_api_protocol = str(raw.get("ai_api_protocol") or "auto")
        config.ai_model = str(raw.get("ai_model") or "")
        config.ai_system_prompt = str(raw.get("ai_system_prompt") or "")

    entries_data = raw.get("question_entries") or []
    config.question_entries = []
    for item in entries_data:
        entry = deserialize_question_entry(item)
        if (
            config.survey_provider != SURVEY_PROVIDER_WJX
            and getattr(entry, "provider_question_id", None)
            and normalize_survey_provider(getattr(entry, "survey_provider", None)) == SURVEY_PROVIDER_WJX
        ):
            entry.survey_provider = config.survey_provider
        config.question_entries.append(entry)

    questions_info_data = raw.get("questions_info") or []
    if isinstance(questions_info_data, list):
        for item in questions_info_data:
            if isinstance(item, dict):
                unknown_question_keys = set(item) - _SURVEY_QUESTION_META_FIELDS
                if unknown_question_keys:
                    raise ValueError(
                        f"{_CONFIG_CORRUPTED_MESSAGE}：题目元数据包含不支持的字段（{', '.join(sorted(unknown_question_keys))}）"
                    )
        normalized_questions = ensure_questions_provider_fields(
            questions_info_data,
            default_provider=config.survey_provider,
        )
        config.questions_info = ensure_survey_question_metas(
            normalized_questions,
            default_provider=config.survey_provider,
        )
    else:
        config.questions_info = []
    config.answer_rules, _ = sanitize_answer_rules(config.answer_rules, config.questions_info or [])
    return config


def _ensure_supported_config_payload(payload: Dict[str, Any], *, config_path: str) -> Dict[str, Any]:
    del config_path
    return dict(payload)


def serialize_runtime_config(config: RuntimeConfig) -> Dict[str, Any]:
    payload: Dict[str, Any] = asdict(config)
    payload["question_entries"] = [
        serialize_question_entry(entry) for entry in list(config.question_entries or [])
    ]
    payload["questions_info"] = serialize_survey_question_metas(config.questions_info or [])
    payload.pop("_ai_config_present", None)
    return payload


def deserialize_runtime_config(payload: Dict[str, Any]) -> RuntimeConfig:
    return normalize_runtime_config_payload(payload)


