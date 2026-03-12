"""工具类模块的懒加载导出。"""

from importlib import import_module
from typing import Any, Dict, Tuple


_EXPORTS: Dict[str, Tuple[str, str]] = {
    "DEFAULT_HTTP_HEADERS": ("wjx.utils.app.config", "DEFAULT_HTTP_HEADERS"),
    "BROWSER_PREFERENCE": ("wjx.utils.app.config", "BROWSER_PREFERENCE"),
    "QUESTION_TYPE_LABELS": ("wjx.utils.app.config", "QUESTION_TYPE_LABELS"),
    "DEFAULT_FILL_TEXT": ("wjx.utils.app.config", "DEFAULT_FILL_TEXT"),
    "__VERSION__": ("wjx.utils.app.version", "__VERSION__"),
    "GITHUB_OWNER": ("wjx.utils.app.version", "GITHUB_OWNER"),
    "GITHUB_REPO": ("wjx.utils.app.version", "GITHUB_REPO"),
    "setup_logging": ("wjx.utils.logging.log_utils", "setup_logging"),
    "log_popup_info": ("wjx.utils.logging.log_utils", "log_popup_info"),
    "log_popup_error": ("wjx.utils.logging.log_utils", "log_popup_error"),
    "log_popup_warning": ("wjx.utils.logging.log_utils", "log_popup_warning"),
    "log_popup_confirm": ("wjx.utils.logging.log_utils", "log_popup_confirm"),
    "LOG_BUFFER_HANDLER": ("wjx.utils.logging.log_utils", "LOG_BUFFER_HANDLER"),
    "register_popup_handler": ("wjx.utils.logging.log_utils", "register_popup_handler"),
    "save_log_records_to_file": ("wjx.utils.logging.log_utils", "save_log_records_to_file"),
    "check_for_updates": ("wjx.utils.update.updater", "check_for_updates"),
    "perform_update": ("wjx.utils.update.updater", "perform_update"),
    "RegistryManager": ("wjx.utils.system.registry_manager", "RegistryManager"),
    "event_bus": ("wjx.utils.event_bus", "bus"),
    "EventBus": ("wjx.utils.event_bus", "EventBus"),
    "EVENT_TASK_STARTED": ("wjx.utils.event_bus", "EVENT_TASK_STARTED"),
    "EVENT_TASK_STOPPED": ("wjx.utils.event_bus", "EVENT_TASK_STOPPED"),
    "EVENT_TASK_PAUSED": ("wjx.utils.event_bus", "EVENT_TASK_PAUSED"),
    "EVENT_TASK_RESUMED": ("wjx.utils.event_bus", "EVENT_TASK_RESUMED"),
    "EVENT_TARGET_REACHED": ("wjx.utils.event_bus", "EVENT_TARGET_REACHED"),
    "EVENT_CAPTCHA_DETECTED": ("wjx.utils.event_bus", "EVENT_CAPTCHA_DETECTED"),
    "EVENT_SUBMIT_SUCCESS": ("wjx.utils.event_bus", "EVENT_SUBMIT_SUCCESS"),
    "EVENT_SUBMIT_FAILURE": ("wjx.utils.event_bus", "EVENT_SUBMIT_FAILURE"),
}


def __getattr__(name: str) -> Any:
    target = _EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attr_name = target
    value = getattr(import_module(module_name), attr_name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(list(globals().keys()) + list(_EXPORTS.keys()))


__all__ = list(_EXPORTS.keys())
