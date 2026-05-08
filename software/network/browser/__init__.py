"""浏览器子包的收口公共接口。

对业务层只暴露常用的 Selenium 风格常量/异常、浏览器驱动协议，
以及少量启动诊断与临时浏览器创建能力。
更底层的 manager / session / transient / owner_pool 请按需直连真实模块。
"""
from __future__ import annotations

from software.network.browser.exceptions import (
    By,
    NoSuchElementException,
    ProxyConnectionError,
    TimeoutException,
)
from software.network.browser.session import BrowserDriver
from software.network.browser.startup import (
    BrowserStartupErrorInfo,
    BrowserStartupRuntimeError,
    classify_playwright_startup_error,
    describe_playwright_startup_error,
    is_playwright_startup_environment_error,
)
from software.network.browser.transient import create_playwright_driver

__all__ = [
    "By",
    "BrowserDriver",
    "BrowserStartupErrorInfo",
    "BrowserStartupRuntimeError",
    "NoSuchElementException",
    "ProxyConnectionError",
    "TimeoutException",
    "classify_playwright_startup_error",
    "create_playwright_driver",
    "describe_playwright_startup_error",
    "is_playwright_startup_environment_error",
]
