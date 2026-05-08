"""User-managed IPList/proxy-pool fetcher."""
from __future__ import annotations

import logging
import random
import threading
from typing import List, Optional

import software.network.http as http_client
from software.app.config import DEFAULT_HTTP_HEADERS, PROXY_MAX_PROXIES
from software.core.task import ProxyLease
from software.network.proxy.pool.free_pool import (
    FREE_POOL_ALLOWED_SCHEMES,
    PROXY_SOURCE_IPLIST,
    _build_proxy_leases,
    _dedupe,
    validate_proxy_leases_concurrently,
)
from software.network.proxy.pool.parsing import parse_proxy_payload

_IPLIST_FETCH_TIMEOUT_SECONDS = 10
_IPLIST_VALIDATE_WORKERS = 64
_IPLIST_VALIDATE_TIMEOUT_SECONDS = 3


def _fetch_iplist_source(url: str) -> List[str]:
    response = http_client.get(
        url,
        timeout=_IPLIST_FETCH_TIMEOUT_SECONDS,
        headers=DEFAULT_HTTP_HEADERS,
        proxies={},
    )
    response.raise_for_status()
    return parse_proxy_payload(response.text, allowed_schemes=FREE_POOL_ALLOWED_SCHEMES)


def fetch_iplist_proxy_batch(
    expected_count: int = 1,
    *,
    proxy_url: Optional[str] = None,
    validate: bool = True,
    stop_signal: Optional[threading.Event] = None,
    target_url: Optional[str] = None,
) -> List[ProxyLease]:
    """Fetch and validate proxies from a user-provided IPList/proxy-pool endpoint."""
    expected = max(1, min(PROXY_MAX_PROXIES, int(expected_count or 1)))
    url = str(proxy_url or "").strip()
    if not url:
        raise RuntimeError("IPList proxy endpoint is not configured")
    if not (url.lower().startswith("http://") or url.lower().startswith("https://")):
        raise RuntimeError("IPList proxy endpoint must start with http:// or https://")

    try:
        addresses = _dedupe(_fetch_iplist_source(url))
        logging.info("IPList proxy source fetched: count=%s url=%s", len(addresses), url)
    except Exception as exc:
        logging.info("IPList proxy source fetch failed: url=%s error=%s", url, exc)
        raise RuntimeError(f"IPList proxy endpoint fetch failed: {exc}") from exc

    random.shuffle(addresses)
    if not addresses:
        raise RuntimeError("IPList proxy endpoint returned no parseable proxies")

    leases = _build_proxy_leases(addresses, limit=len(addresses), source=PROXY_SOURCE_IPLIST)
    if not validate:
        return leases[:expected]

    healthy = validate_proxy_leases_concurrently(
        leases,
        expected_count=expected,
        timeout_seconds=_IPLIST_VALIDATE_TIMEOUT_SECONDS,
        max_workers=_IPLIST_VALIDATE_WORKERS,
        source_label="IPList",
        stop_signal=stop_signal,
        validate_all=True,
        return_limit=PROXY_MAX_PROXIES,
        quiet=True,
        target_url=target_url,
    )
    if healthy:
        return healthy
    raise RuntimeError("No usable IPList proxy after validation; check endpoint or proxy quality")


__all__ = ["fetch_iplist_proxy_batch"]
