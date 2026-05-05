"""代理预取服务 - 封装代理池初始化逻辑"""
from __future__ import annotations

import threading
from typing import List, Optional

from software.core.task import ProxyLease
from software.network.proxy.sidecar_manager import get_proxy_sidecar_client


def prefetch_proxy_pool(
    expected_count: int,
    proxy_api_url: Optional[str] = None,
    stop_signal: Optional[threading.Event] = None,
) -> List[ProxyLease]:
    """预取一批代理 IP。"""
    del proxy_api_url, stop_signal
    get_proxy_sidecar_client().prefetch(max(1, expected_count))
    return []

