"""网络相关模块的懒加载导出。"""

from importlib import import_module
from typing import Any, Dict, Tuple


_EXPORTS: Dict[str, Tuple[str, str]] = {
    "By": ("wjx.network.browser", "By"),
    "BrowserDriver": ("wjx.network.browser", "BrowserDriver"),
    "NoSuchElementException": ("wjx.network.browser", "NoSuchElementException"),
    "PlaywrightDriver": ("wjx.network.browser", "PlaywrightDriver"),
    "PlaywrightElement": ("wjx.network.browser", "PlaywrightElement"),
    "ProxyConnectionError": ("wjx.network.browser", "ProxyConnectionError"),
    "TimeoutException": ("wjx.network.browser", "TimeoutException"),
    "create_playwright_driver": ("wjx.network.browser", "create_playwright_driver"),
    "on_random_ip_toggle": ("wjx.network.proxy", "on_random_ip_toggle"),
    "handle_random_ip_submission": ("wjx.network.proxy", "handle_random_ip_submission"),
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
