"""问卷星平台包导出入口。"""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Any, Dict, Tuple

from software.app.version import __VERSION__

if TYPE_CHECKING:
    from wjx.provider.detection import detect
    from wjx.provider.parser import (
        PAUSED_SURVEY_ERROR_MESSAGE,
        SurveyPausedError,
        is_paused_survey_page,
        parse_wjx_survey,
    )
    from wjx.provider.runtime import brush_wjx, fill_survey

_EXPORTS: Dict[str, Tuple[str, str]] = {
    "PAUSED_SURVEY_ERROR_MESSAGE": ("wjx.provider.parser", "PAUSED_SURVEY_ERROR_MESSAGE"),
    "SurveyPausedError": ("wjx.provider.parser", "SurveyPausedError"),
    "is_paused_survey_page": ("wjx.provider.parser", "is_paused_survey_page"),
    "parse_wjx_survey": ("wjx.provider.parser", "parse_wjx_survey"),
    "detect": ("wjx.provider.detection", "detect"),
    "brush_wjx": ("wjx.provider.runtime", "brush_wjx"),
    "fill_survey": ("wjx.provider.runtime", "fill_survey"),
}

__all__ = [
    "__VERSION__",
    "PAUSED_SURVEY_ERROR_MESSAGE",
    "SurveyPausedError",
    "is_paused_survey_page",
    "parse_wjx_survey",
    "detect",
    "brush_wjx",
    "fill_survey",
]


def __getattr__(name: str) -> Any:
    target = _EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attr_name = target
    module = import_module(module_name)
    value = getattr(module, attr_name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(list(globals().keys()) + __all__)


