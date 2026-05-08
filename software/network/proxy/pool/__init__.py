"""代理池与预取。"""

from software.network.proxy.pool.pool import (
    coerce_proxy_lease,
    get_proxy_required_ttl_seconds,
    is_http_proxy_connect_responsive,
    is_proxy_responsive,
    mask_proxy_for_log,
    normalize_proxy_address,
    proxy_lease_has_sufficient_ttl,
)
from software.network.proxy.pool.free_pool import PROXY_SOURCE_FREE_POOL, PROXY_SOURCE_IPLIST, fetch_free_proxy_batch
from software.network.proxy.pool.iplist_pool import fetch_iplist_proxy_batch
from software.network.proxy.pool.prefetch import prefetch_proxy_pool

__all__ = [
    "PROXY_SOURCE_FREE_POOL",
    "PROXY_SOURCE_IPLIST",
    "coerce_proxy_lease",
    "fetch_free_proxy_batch",
    "fetch_iplist_proxy_batch",
    "get_proxy_required_ttl_seconds",
    "is_http_proxy_connect_responsive",
    "is_proxy_responsive",
    "mask_proxy_for_log",
    "normalize_proxy_address",
    "prefetch_proxy_pool",
    "proxy_lease_has_sufficient_ttl",
]

