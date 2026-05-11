"""浏览器子包的收口公共接口。"""
from __future__ import annotations

from software.network.browser.exceptions import (
    By,
    NoSuchElementException,
    ProxyConnectionError,
    TimeoutException,
)
from software.network.browser.runtime_async import BrowserDriver
from software.network.browser.startup import (
    BrowserStartupErrorInfo,
    BrowserStartupRuntimeError,
    classify_playwright_startup_error,
    describe_playwright_startup_error,
    is_playwright_startup_environment_error,
)

__all__ = [
    "By",
    "BrowserDriver",
    "BrowserStartupErrorInfo",
    "BrowserStartupRuntimeError",
    "NoSuchElementException",
    "ProxyConnectionError",
    "TimeoutException",
    "classify_playwright_startup_error",
    "describe_playwright_startup_error",
    "is_playwright_startup_environment_error",
]
