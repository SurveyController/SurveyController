"""Proxy prefetch service."""
from __future__ import annotations

import threading
from typing import List, Optional

from software.core.task import ProxyLease
from software.network.proxy.policy import get_effective_proxy_api_url, get_proxy_source
from software.network.proxy.policy.source import PROXY_SOURCE_FREE_POOL, PROXY_SOURCE_IPLIST


def prefetch_proxy_pool(
    expected_count: int,
    proxy_api_url: Optional[str] = None,
    stop_signal: Optional[threading.Event] = None,
    progress_callback=None,
    max_workers: Optional[int] = None,
    candidate_count: Optional[int] = None,
    fetch_workers: Optional[int] = None,
    probe_timeout_ms: Optional[int] = None,
    force_refresh: bool = False,
    target_url: Optional[str] = None,
) -> List[ProxyLease]:
    """Prefetch a batch of proxy leases for the active source."""
    current_source = get_proxy_source()
    if current_source == PROXY_SOURCE_FREE_POOL:
        from software.network.proxy.pool.free_pool import fetch_free_proxy_batch

        return fetch_free_proxy_batch(
            expected_count=max(1, expected_count),
            stop_signal=stop_signal,
            progress_callback=progress_callback,
            max_workers=max_workers,
            candidate_count=candidate_count,
            fetch_workers=fetch_workers,
            probe_timeout_ms=probe_timeout_ms,
            force_refresh=force_refresh,
            target_url=target_url,
        )
    if current_source == PROXY_SOURCE_IPLIST:
        from software.network.proxy.pool.iplist_pool import fetch_iplist_proxy_batch

        effective_url = proxy_api_url or get_effective_proxy_api_url()
        return fetch_iplist_proxy_batch(
            expected_count=max(1, expected_count),
            proxy_url=effective_url,
            stop_signal=stop_signal,
            target_url=target_url,
        )

    from software.network.proxy.api import fetch_proxy_batch

    effective_url = proxy_api_url or get_effective_proxy_api_url()
    return fetch_proxy_batch(
        expected_count=max(1, expected_count),
        proxy_url=effective_url,
        notify_on_area_error=False,
        stop_signal=stop_signal,
    )
