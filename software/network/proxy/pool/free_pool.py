"""Public free-proxy pool fetcher backed by multiple public sources."""
from __future__ import annotations

import logging
import os
import random
import re
import threading
import time
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence
from urllib.parse import urlsplit

import software.network.http as http_client
from software.app.config import DEFAULT_HTTP_HEADERS
from software.core.task import ProxyLease
from software.logging.log_utils import log_suppressed_exception
from software.network.proxy.pool.pool import _build_proxy_lease, is_http_proxy_connect_responsive
from software.network.proxy.pool.parsing import parse_proxy_payload

PROXY_SOURCE_FREE_POOL = "free_pool"
PROXY_SOURCE_IPLIST = "iplist"

_SCDN_PAGE_ENDPOINT = "https://proxy.scdn.io/get_proxies.php"
_SCDN_PAGE_PROTOCOLS = ("HTTP", "HTTPS")
_SCDN_PAGE_SIZE = 100
_SCDN_MAX_PAGE_ROUNDS = 12
_SCDN_PAGE_HEADERS = {
    **DEFAULT_HTTP_HEADERS,
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Referer": "https://proxy.scdn.io/",
    "X-Requested-With": "XMLHttpRequest",
}
_TEXT_SOURCE_HEADERS = {
    **DEFAULT_HTTP_HEADERS,
    "Accept": "text/plain, application/json, */*",
}
_EXTRA_TEXT_SOURCES = (
    (
        "ProxyScrape HTTP",
        "https://api.proxyscrape.com/v3/free-proxy-list/get?request=displayproxies&protocol=http",
        "http",
    ),
    (
        "ProxyScrape",
        "https://api.proxyscrape.com/v2/?request=getproxies&protocol=http&timeout=8000&country=all&ssl=all&anonymity=all",
        "http",
    ),
    (
        "OpenProxyList HTTP",
        "https://openproxylist.xyz/http.txt",
        "http",
    ),
    (
        "ProxyListDownload HTTP",
        "https://www.proxy-list.download/api/v1/get?type=http",
        "http",
    ),
    (
        "ProxyListDownload HTTPS",
        "https://www.proxy-list.download/api/v1/get?type=https",
        "http",
    ),
    (
        "GeoNode HTTP",
        "https://proxylist.geonode.com/api/proxy-list?limit=500&page=1&sort_by=lastChecked&sort_type=desc&protocols=http",
        "http",
    ),
    (
        "ProxyScan HTTP",
        "https://www.proxyscan.io/api/proxy?type=http&format=txt",
        "http",
    ),
    (
        "Proxifly",
        "https://cdn.jsdelivr.net/gh/proxifly/free-proxy-list@main/proxies/protocols/http/data.txt",
        "http",
    ),
    (
        "TheSpeedX",
        "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt",
        "http",
    ),
    (
        "monosans",
        "https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/http.txt",
        "http",
    ),
    (
        "monosans JSON",
        "https://raw.githubusercontent.com/monosans/proxy-list/main/proxies.json",
        "http",
    ),
    (
        "clarketm",
        "https://raw.githubusercontent.com/clarketm/proxy-list/master/proxy-list-raw.txt",
        "http",
    ),
    (
        "fate0 proxylist",
        "https://raw.githubusercontent.com/fate0/proxylist/master/proxy.list",
        "http",
    ),
    (
        "ProxyScrape SOCKS5",
        "https://api.proxyscrape.com/v3/free-proxy-list/get?request=displayproxies&protocol=socks5",
        "socks5",
    ),
    (
        "OpenProxyList SOCKS5",
        "https://openproxylist.xyz/socks5.txt",
        "socks5",
    ),
    (
        "TheSpeedX SOCKS5",
        "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/socks5.txt",
        "socks5",
    ),
    (
        "hookzof SOCKS5",
        "https://raw.githubusercontent.com/hookzof/socks5_list/master/proxy.txt",
        "socks5",
    ),
    (
        "ProxyScraper SOCKS5",
        "https://raw.githubusercontent.com/ProxyScraper/ProxyScraper/main/socks5.txt",
        "socks5",
    ),
    (
        "zloi-user SOCKS5",
        "https://raw.githubusercontent.com/zloi-user/hideip.me/master/socks5.txt",
        "socks5",
    ),
    (
        "gfpcom SOCKS5",
        "https://raw.githubusercontent.com/gfpcom/free-proxy-list/main/list/socks5.txt",
        "socks5",
    ),
)
_LOCAL_SEED_ENV_VAR = "SURVEYCONTROLLER_FREE_PROXY_SEED_DIR"
_LOCAL_SEED_DEFAULT_ROOTS = (Path(r"D:\fir-proxy-main\fir-proxy-main"),)
_LOCAL_SEED_MAX_FILES = 80
_LOCAL_SEED_MAX_FILE_BYTES = 5 * 1024 * 1024
_SCDN_DEFAULT_CANDIDATE_COUNT = 10000
_SCDN_DEFAULT_PAGE_ROUNDS = max(
    1,
    (_SCDN_DEFAULT_CANDIDATE_COUNT + (_SCDN_PAGE_SIZE * len(_SCDN_PAGE_PROTOCOLS)) - 1)
    // (_SCDN_PAGE_SIZE * len(_SCDN_PAGE_PROTOCOLS)),
)
_SCDN_FETCH_WORKERS = 3
_SCDN_FETCH_WORKER_HARD_LIMIT = 50
_FREE_POOL_VALIDATE_WORKER_HARD_LIMIT = 1000
_FREE_POOL_DEFAULT_TARGET_COUNT = 80
_FREE_POOL_MAX_TARGET_COUNT = 100000

_FREE_POOL_ALLOWED_SCHEMES = ("http", "https", "socks5")
FREE_POOL_ALLOWED_SCHEMES = _FREE_POOL_ALLOWED_SCHEMES
FREE_POOL_DEFAULT_CANDIDATE_COUNT = _SCDN_DEFAULT_CANDIDATE_COUNT
FREE_POOL_DEFAULT_FETCH_WORKERS = _SCDN_FETCH_WORKERS
FREE_POOL_MAX_FETCH_WORKERS = _SCDN_FETCH_WORKER_HARD_LIMIT
_FREE_POOL_FETCH_TIMEOUT_SECONDS = 8
_FREE_POOL_EXTRA_SOURCE_TIMEOUT_SECONDS = 8
_FREE_POOL_CACHE_TTL_SECONDS = 180
_FREE_POOL_CACHE_MAX_ITEMS = 1000000
FREE_POOL_MAX_CANDIDATE_COUNT = _FREE_POOL_CACHE_MAX_ITEMS
FREE_POOL_DEFAULT_TARGET_COUNT = _FREE_POOL_DEFAULT_TARGET_COUNT
FREE_POOL_MAX_TARGET_COUNT = _FREE_POOL_MAX_TARGET_COUNT
_FREE_POOL_VALIDATE_WORKERS = 200
FREE_POOL_DEFAULT_VALIDATE_WORKERS = _FREE_POOL_VALIDATE_WORKERS
FREE_POOL_MAX_VALIDATE_WORKERS = _FREE_POOL_VALIDATE_WORKER_HARD_LIMIT
FREE_POOL_DEFAULT_PROBE_TIMEOUT_MS = 5000
_FREE_POOL_VALIDATE_TIMEOUT_SECONDS = FREE_POOL_DEFAULT_PROBE_TIMEOUT_MS / 1000.0
_FREE_POOL_INITIAL_VALIDATE_ROUNDS = 3
FREE_POOL_INITIAL_VALIDATE_ROUNDS = _FREE_POOL_INITIAL_VALIDATE_ROUNDS
_FREE_POOL_VALIDATE_BATCH_MULTIPLIER = 3
_FREE_POOL_MAX_ADDRESSES_PER_HOST = 2

ProxyPoolProgressCallback = Callable[[Dict[str, Any]], None]

_cache_lock = threading.RLock()
_cache_expires_at = 0.0
_cache_items: List[str] = []
_cache_requested_count = 0


def _emit_progress(progress_callback: Optional[ProxyPoolProgressCallback], **payload: Any) -> None:
    if not callable(progress_callback):
        return
    try:
        progress_callback(dict(payload))
    except Exception as exc:
        log_suppressed_exception("free proxy progress callback", exc, level=logging.INFO)


def _dedupe(items: Iterable[str]) -> List[str]:
    seen = set()
    unique: List[str] = []
    for item in items:
        address = str(item or "").strip()
        if not address or address in seen:
            continue
        seen.add(address)
        unique.append(address)
    return unique


def _proxy_host_key(address: str) -> str:
    text = str(address or "").strip()
    if not text:
        return ""
    candidate = text if "://" in text else f"http://{text}"
    try:
        parsed = urlsplit(candidate)
        return str(parsed.hostname or "").strip().lower()
    except Exception:
        return ""


def _limit_addresses_per_host(addresses: Iterable[str], *, per_host: int = _FREE_POOL_MAX_ADDRESSES_PER_HOST) -> List[str]:
    limit = max(1, int(per_host or 1))
    counts: dict[str, int] = {}
    limited: List[str] = []
    for address in addresses:
        normalized = str(address or "").strip()
        if not normalized:
            continue
        host_key = _proxy_host_key(normalized) or normalized
        count = counts.get(host_key, 0)
        if count >= limit:
            continue
        counts[host_key] = count + 1
        limited.append(normalized)
    return limited


def _scdn_page_url(protocol: str, page: int, per_page: int = _SCDN_PAGE_SIZE) -> str:
    safe_protocol = str(protocol or "HTTP").strip().upper()
    if safe_protocol not in _SCDN_PAGE_PROTOCOLS:
        safe_protocol = "HTTP"
    safe_page = max(1, int(page or 1))
    safe_per_page = max(1, min(_SCDN_PAGE_SIZE, int(per_page or _SCDN_PAGE_SIZE)))
    return f"{_SCDN_PAGE_ENDPOINT}?protocol={safe_protocol}&per_page={safe_per_page}&page={safe_page}"


def _normalize_source_name(source_name: str) -> str:
    return str(source_name or "source").strip() or "source"


def _coerce_positive_int(value: Optional[int], default: int) -> int:
    try:
        number = int(value if value is not None else default)
    except Exception:
        number = int(default)
    return max(1, number)


def _coerce_probe_timeout_ms(value: Optional[int]) -> int:
    return _coerce_positive_int(value, FREE_POOL_DEFAULT_PROBE_TIMEOUT_MS)


def _probe_timeout_seconds(value: Optional[int]) -> float:
    return max(0.001, _coerce_probe_timeout_ms(value) / 1000.0)


def _rounds_for_candidate_count(candidate_count: Optional[int]) -> int:
    target = min(_FREE_POOL_CACHE_MAX_ITEMS, _coerce_positive_int(candidate_count, _SCDN_DEFAULT_CANDIDATE_COUNT))
    per_round = max(1, _SCDN_PAGE_SIZE * len(_SCDN_PAGE_PROTOCOLS))
    return max(1, (target + per_round - 1) // per_round)


def _force_proxy_scheme(address: str, scheme: str = "http") -> str:
    target_scheme = str(scheme or "http").strip().lower()
    if target_scheme not in _FREE_POOL_ALLOWED_SCHEMES:
        target_scheme = "http"
    text = str(address or "").strip()
    if not text:
        return ""
    candidate = text if "://" in text else f"{target_scheme}://{text}"
    try:
        parsed = urlsplit(candidate)
        if parsed.netloc:
            return f"{target_scheme}://{parsed.netloc}"
    except Exception:
        pass
    if "://" in text:
        text = text.split("://", 1)[1]
    return f"{target_scheme}://{text}"


class _ScdnTableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: List[List[str]] = []
        self._current_row: Optional[List[str]] = None
        self._current_cell: Optional[List[str]] = None

    def handle_starttag(self, tag: str, attrs: Sequence[tuple[str, Optional[str]]]) -> None:
        lower_tag = tag.lower()
        if lower_tag == "tr":
            self._current_row = []
        elif lower_tag == "td" and self._current_row is not None:
            self._current_cell = []

    def handle_endtag(self, tag: str) -> None:
        lower_tag = tag.lower()
        if lower_tag == "td" and self._current_row is not None and self._current_cell is not None:
            self._current_row.append(" ".join("".join(self._current_cell).split()))
            self._current_cell = None
        elif lower_tag == "tr" and self._current_row is not None:
            if self._current_row:
                self.rows.append(self._current_row)
            self._current_row = None
            self._current_cell = None

    def handle_data(self, data: str) -> None:
        if self._current_cell is not None:
            self._current_cell.append(data)


def _coerce_scdn_payload(payload: Any) -> Dict[str, Any]:
    if isinstance(payload, dict):
        return payload
    text = str(payload or "")
    if not text.strip():
        return {}
    try:
        import json

        parsed = json.loads(text)
    except Exception:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _parse_scdn_table_payload(payload: Any, requested_protocol: str) -> List[str]:
    protocol = str(requested_protocol or "HTTP").strip().upper()
    if protocol not in _SCDN_PAGE_PROTOCOLS:
        protocol = "HTTP"
    data = _coerce_scdn_payload(payload)
    table_html = str(data.get("table_html") or "")
    if not table_html.strip():
        return []

    parser = _ScdnTableParser()
    parser.feed(table_html)
    parser.close()

    addresses: List[str] = []
    for row in parser.rows:
        if len(row) < 3:
            continue
        ip = str(row[0] or "").strip()
        port = str(row[1] or "").strip()
        protocols = {item.upper() for item in re.findall(r"\bHTTPS?\b", str(row[2] or ""), flags=re.IGNORECASE)}
        if not ip or not port or protocol not in protocols:
            continue
        if not re.fullmatch(r"\d{1,5}", port):
            continue
        addresses.append(_force_proxy_scheme(f"{ip}:{port}"))
    return _dedupe(addresses)


def _fetch_scdn_page_payload(url: str) -> Dict[str, Any]:
    response = http_client.get(
        url,
        timeout=_FREE_POOL_FETCH_TIMEOUT_SECONDS,
        headers=_SCDN_PAGE_HEADERS,
    )
    response.raise_for_status()
    try:
        data = response.json()
    except Exception:
        data = _coerce_scdn_payload(getattr(response, "text", ""))
    return data if isinstance(data, dict) else {}


def _fetch_text_source_addresses(name: str, url: str, default_scheme: str = "http") -> List[str]:
    response = http_client.get(
        url,
        timeout=_FREE_POOL_EXTRA_SOURCE_TIMEOUT_SECONDS,
        headers=_TEXT_SOURCE_HEADERS,
    )
    response.raise_for_status()
    return parse_proxy_payload(
        getattr(response, "text", ""),
        allowed_schemes=_FREE_POOL_ALLOWED_SCHEMES,
        default_scheme=default_scheme,
    )


def _iter_local_seed_files() -> List[Path]:
    roots: List[Path] = []
    env_value = str(os.environ.get(_LOCAL_SEED_ENV_VAR, "") or "").strip()
    if env_value:
        for part in re.split(r"[;,\n]", env_value):
            text = part.strip().strip('"')
            if text:
                roots.append(Path(text))
    roots.extend(_LOCAL_SEED_DEFAULT_ROOTS)

    files: list[Path] = []
    seen: set[str] = set()
    for root in roots:
        try:
            if not root.exists():
                continue
            candidates = [root] if root.is_file() else list(root.rglob("*.txt"))
        except Exception as exc:
            log_suppressed_exception(f"scan local free proxy seed {root}", exc, level=logging.INFO)
            continue
        for path in candidates:
            try:
                resolved = str(path.resolve()).lower()
                if resolved in seen or not path.is_file():
                    continue
                if path.stat().st_size > _LOCAL_SEED_MAX_FILE_BYTES:
                    continue
            except Exception:
                continue
            seen.add(resolved)
            files.append(path)
    files.sort(key=lambda item: item.stat().st_mtime if item.exists() else 0.0, reverse=True)
    return files[:_LOCAL_SEED_MAX_FILES]


def _load_local_seed_addresses() -> List[str]:
    addresses: List[str] = []
    for path in _iter_local_seed_files():
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except Exception as exc:
            log_suppressed_exception(f"read local free proxy seed {path}", exc, level=logging.INFO)
            continue
        addresses.extend(
            parse_proxy_payload(
                text,
                allowed_schemes=_FREE_POOL_ALLOWED_SCHEMES,
                default_scheme="socks5" if "socks" in text[:512].lower() else "http",
            )
        )
    return _dedupe(addresses)


def _fetch_public_source_addresses(
    *,
    candidate_count: Optional[int] = _SCDN_DEFAULT_CANDIDATE_COUNT,
    rounds: Optional[int] = None,
    fetch_workers: Optional[int] = _SCDN_FETCH_WORKERS,
    stop_signal: Optional[threading.Event] = None,
    progress_callback: Optional[ProxyPoolProgressCallback] = None,
) -> List[str]:
    target_candidates = min(_FREE_POOL_CACHE_MAX_ITEMS, _coerce_positive_int(candidate_count, _SCDN_DEFAULT_CANDIDATE_COUNT))
    requested_scdn_rounds = _coerce_positive_int(rounds, _rounds_for_candidate_count(candidate_count))
    scdn_rounds = min(requested_scdn_rounds, _SCDN_MAX_PAGE_ROUNDS)
    if requested_scdn_rounds > scdn_rounds:
        logging.info(
            "Public proxy SCDN pages capped: requested_rounds=%s used_rounds=%s; text/local sources provide the wider scan",
            requested_scdn_rounds,
            scdn_rounds,
        )
    scdn_tasks = [
        ("SCDN", protocol, page, _scdn_page_url(protocol, page))
        for round_index in range(scdn_rounds)
        for page in (round_index + 1,)
        for protocol in _SCDN_PAGE_PROTOCOLS
    ]
    text_tasks = [
        (_normalize_source_name(name), default_scheme, None, url)
        for name, url, default_scheme in _EXTRA_TEXT_SOURCES
    ]
    tasks = text_tasks + scdn_tasks
    requested_workers = _coerce_positive_int(fetch_workers, _SCDN_FETCH_WORKERS)
    worker_count = min(requested_workers, _SCDN_FETCH_WORKER_HARD_LIMIT, len(tasks))
    addresses: List[str] = []
    seen_addresses: set[str] = set()
    completed = 0
    errors = 0
    error_samples: List[str] = []

    local_seed_addresses = _load_local_seed_addresses()
    for seed_address in local_seed_addresses:
        address = str(seed_address or "").strip()
        if not address or address in seen_addresses:
            continue
        seen_addresses.add(address)
        addresses.append(address)
        if len(addresses) >= target_candidates:
            break

    _emit_progress(
        progress_callback,
        stage="fetch",
        total=len(tasks),
        completed=0,
        candidates=len(addresses),
        local_seed_count=len(local_seed_addresses),
        target_candidates=target_candidates,
        workers=worker_count,
        message=f"正在读取公共代理源：{len(addresses)}/{target_candidates}",
    )
    if len(addresses) >= target_candidates:
        return list(addresses)

    def _fetch(task: tuple[str, str, Optional[int], str]) -> List[str]:
        source_name, protocol, _page, url = task
        if stop_signal is not None and stop_signal.is_set():
            return []
        if source_name == "SCDN":
            payload = _fetch_scdn_page_payload(url)
            return _parse_scdn_table_payload(payload, protocol)
        return _fetch_text_source_addresses(source_name, url, default_scheme=str(protocol or "http"))

    executor = ThreadPoolExecutor(max_workers=worker_count, thread_name_prefix="PublicProxyFetch")
    pending: set[Future] = set()
    next_index = 0

    def _submit_next() -> bool:
        nonlocal next_index
        if next_index >= len(tasks):
            return False
        if stop_signal is not None and stop_signal.is_set():
            return False
        pending.add(executor.submit(_fetch, tasks[next_index]))
        next_index += 1
        return True

    for _ in range(worker_count):
        if not _submit_next():
            break

    try:
        while pending:
            if stop_signal is not None and stop_signal.is_set():
                break
            done, pending = wait(pending, return_when=FIRST_COMPLETED)
            for future in done:
                completed += 1
                try:
                    parsed = future.result()
                    for parsed_address in parsed:
                        address = str(parsed_address or "").strip()
                        if not address or address in seen_addresses:
                            continue
                        seen_addresses.add(address)
                        addresses.append(address)
                        if len(addresses) >= target_candidates:
                            break
                except Exception as exc:
                    errors += 1
                    if len(error_samples) < 5:
                        error_samples.append(str(exc))
                unique_count = len(addresses)
                _emit_progress(
                    progress_callback,
                    stage="fetch",
                    total=len(tasks),
                    completed=completed,
                    candidates=unique_count,
                    errors=errors,
                    target_candidates=target_candidates,
                    workers=worker_count,
                    message=f"正在读取公共代理源：{unique_count}/{target_candidates}",
                )
                if unique_count >= target_candidates:
                    break
            if len(addresses) >= target_candidates:
                break
            while len(pending) < worker_count and _submit_next():
                pass
    finally:
        for future in pending:
            if not future.done():
                future.cancel()
        executor.shutdown(wait=False, cancel_futures=True)

    unique = list(addresses)
    if errors:
        logging.info(
            "Public proxy source fetch completed with errors: errors=%s candidates=%s samples=%s",
            errors,
            len(unique),
            " | ".join(error_samples),
        )
    if not unique and errors:
        raise RuntimeError(f"公共代理源读取失败：{error_samples[0]}")
    return unique


def _fetch_scdn_page_addresses(
    *,
    candidate_count: Optional[int] = _SCDN_DEFAULT_CANDIDATE_COUNT,
    rounds: Optional[int] = None,
    fetch_workers: Optional[int] = _SCDN_FETCH_WORKERS,
    stop_signal: Optional[threading.Event] = None,
    progress_callback: Optional[ProxyPoolProgressCallback] = None,
) -> List[str]:
    rounds = _coerce_positive_int(rounds, _rounds_for_candidate_count(candidate_count))
    target_candidates = min(
        _FREE_POOL_CACHE_MAX_ITEMS,
        max(1, rounds * _SCDN_PAGE_SIZE * len(_SCDN_PAGE_PROTOCOLS)),
    )
    tasks = [
        (protocol, page, _scdn_page_url(protocol, page))
        for round_index in range(rounds)
        for page in (round_index + 1,)
        for protocol in _SCDN_PAGE_PROTOCOLS
    ]
    requested_workers = _coerce_positive_int(fetch_workers, _SCDN_FETCH_WORKERS)
    worker_count = min(requested_workers, _SCDN_FETCH_WORKER_HARD_LIMIT, len(tasks))
    addresses: List[str] = []
    seen_addresses: set[str] = set()
    completed = 0
    errors = 0
    error_samples: List[str] = []

    _emit_progress(
        progress_callback,
        stage="fetch",
        total=len(tasks),
        completed=0,
        candidates=0,
        target_candidates=target_candidates,
        workers=worker_count,
        message=f"正在读取 SCDN 页面列表：0/{target_candidates}",
    )

    def _fetch(task: tuple[str, int, str]) -> List[str]:
        protocol, _page, url = task
        if stop_signal is not None and stop_signal.is_set():
            return []
        payload = _fetch_scdn_page_payload(url)
        return _parse_scdn_table_payload(payload, protocol)

    executor = ThreadPoolExecutor(max_workers=worker_count, thread_name_prefix="SCDNProxyFetch")
    pending: set[Future] = set()
    next_index = 0

    def _submit_next() -> bool:
        nonlocal next_index
        if next_index >= len(tasks):
            return False
        if stop_signal is not None and stop_signal.is_set():
            return False
        pending.add(executor.submit(_fetch, tasks[next_index]))
        next_index += 1
        return True

    for _ in range(worker_count):
        if not _submit_next():
            break

    try:
        while pending:
            if stop_signal is not None and stop_signal.is_set():
                break
            done, pending = wait(pending, return_when=FIRST_COMPLETED)
            for future in done:
                completed += 1
                try:
                    parsed = future.result()
                    for parsed_address in parsed:
                        address = str(parsed_address or "").strip()
                        if not address or address in seen_addresses:
                            continue
                        seen_addresses.add(address)
                        addresses.append(address)
                except Exception as exc:
                    errors += 1
                    if len(error_samples) < 3:
                        error_samples.append(str(exc))
                unique_count = len(addresses)
                _emit_progress(
                    progress_callback,
                    stage="fetch",
                    total=len(tasks),
                    completed=completed,
                    candidates=unique_count,
                    errors=errors,
                    target_candidates=target_candidates,
                    workers=worker_count,
                    message=f"正在读取 SCDN 页面列表：{unique_count}/{target_candidates}",
                )
            while len(pending) < worker_count and _submit_next():
                pass
    finally:
        for future in pending:
            if not future.done():
                future.cancel()
        executor.shutdown(wait=False, cancel_futures=True)
    unique = list(addresses)
    if errors:
        logging.info(
            "SCDN proxy page fetch completed with errors: errors=%s candidates=%s samples=%s",
            errors,
            len(unique),
            " | ".join(error_samples),
        )
    if not unique and errors:
        raise RuntimeError(f"SCDN 页面代理列表读取失败：{error_samples[0]}")
    return unique


def _load_free_proxy_addresses(
    *,
    force_refresh: bool = False,
    candidate_count: Optional[int] = _SCDN_DEFAULT_CANDIDATE_COUNT,
    rounds: Optional[int] = None,
    fetch_workers: Optional[int] = _SCDN_FETCH_WORKERS,
    stop_signal: Optional[threading.Event] = None,
    progress_callback: Optional[ProxyPoolProgressCallback] = None,
) -> List[str]:
    global _cache_expires_at, _cache_items, _cache_requested_count

    now = time.time()
    if rounds is not None:
        cache_target = min(
            _FREE_POOL_CACHE_MAX_ITEMS,
            _coerce_positive_int(rounds, _SCDN_DEFAULT_PAGE_ROUNDS)
            * _SCDN_PAGE_SIZE
            * len(_SCDN_PAGE_PROTOCOLS),
        )
    else:
        cache_target = min(_FREE_POOL_CACHE_MAX_ITEMS, _coerce_positive_int(candidate_count, _SCDN_DEFAULT_CANDIDATE_COUNT))
    with _cache_lock:
        if (
            not force_refresh
            and _cache_items
            and _cache_expires_at > now
            and _cache_requested_count >= cache_target
        ):
            cached = list(_cache_items)
            _emit_progress(
                progress_callback,
                stage="fetch",
                total=1,
                completed=1,
                candidates=len(cached),
                cached=True,
                message=f"已复用缓存候选 {len(cached)} 个",
            )
            return cached

    unique = _fetch_public_source_addresses(
        candidate_count=candidate_count,
        rounds=rounds,
        fetch_workers=fetch_workers,
        stop_signal=stop_signal,
        progress_callback=progress_callback,
    )
    if not unique:
        raise RuntimeError("公共代理源未返回可解析的 HTTP/HTTPS 代理，请降低候选数量/拉取并发或稍后重试")
    random.shuffle(unique)
    with _cache_lock:
        _cache_items = unique[:_FREE_POOL_CACHE_MAX_ITEMS]
        _cache_requested_count = cache_target
        _cache_expires_at = time.time() + _FREE_POOL_CACHE_TTL_SECONDS
        return list(_cache_items)


def _build_proxy_leases(addresses: Iterable[str], *, limit: int, source: str) -> List[ProxyLease]:
    leases: List[ProxyLease] = []
    max_items = max(0, int(limit or 0))
    for address in addresses:
        lease = _build_proxy_lease(address, source=source)
        if lease is None:
            continue
        leases.append(lease)
        if max_items and len(leases) >= max_items:
            break
    return leases


def _validate_proxy_leases_concurrently(
    leases: Sequence[ProxyLease],
    *,
    expected_count: int,
    timeout_seconds: float,
    max_workers: int,
    source_label: str,
    stop_signal: Optional[threading.Event] = None,
    validate_all: bool = False,
    return_limit: Optional[int] = None,
    progress_callback: Optional[ProxyPoolProgressCallback] = None,
    quiet: bool = False,
    target_url: Optional[str] = None,
) -> List[ProxyLease]:
    expected = max(1, min(_FREE_POOL_MAX_TARGET_COUNT, int(expected_count or 1)))
    candidates = [lease for lease in leases if lease is not None and str(lease.address or "").strip()]
    probe_target_url = str(target_url or "").strip()
    if not candidates:
        _emit_progress(
            progress_callback,
            stage="validate",
            total=0,
            checked=0,
            passed=0,
            message="没有可检测的代理候选",
        )
        return []

    healthy: List[ProxyLease] = []
    requested_workers = max(1, min(int(max_workers or 1), _FREE_POOL_VALIDATE_WORKER_HARD_LIMIT, len(candidates)))
    effective_worker_count = requested_workers if validate_all else min(
        requested_workers,
        len(candidates),
        max(expected * _FREE_POOL_VALIDATE_BATCH_MULTIPLIER, expected + 20, 40),
    )
    result_limit = max(expected, min(_FREE_POOL_MAX_TARGET_COUNT, int(return_limit or _FREE_POOL_MAX_TARGET_COUNT)))
    checked_count = 0
    next_index = 0
    stop_early = False

    def _check(lease: ProxyLease) -> Optional[ProxyLease]:
        if stop_signal is not None and stop_signal.is_set():
            return None
        if is_http_proxy_connect_responsive(
            lease.address,
            target_url=probe_target_url,
            timeout=max(0.001, float(timeout_seconds or _FREE_POOL_VALIDATE_TIMEOUT_SECONDS)),
            log_failures=not quiet,
            log_success=not quiet,
        ):
            return lease
        return None

    logging.info(
        "%s proxy validation started: candidates=%s expected=%s mode=%s workers=%s timeout=%.1fs target=%s",
        source_label,
        len(candidates),
        expected,
        "full_scan" if validate_all else "fast_until_ready",
        effective_worker_count,
        max(0.001, float(timeout_seconds or _FREE_POOL_VALIDATE_TIMEOUT_SECONDS)),
        probe_target_url or "default",
    )
    _emit_progress(
        progress_callback,
        stage="validate",
        total=len(candidates),
        checked=0,
        passed=0,
        expected=expected,
        workers=effective_worker_count,
        message=f"检测 0/{len(candidates)}，可用 0",
    )

    executor = ThreadPoolExecutor(max_workers=effective_worker_count, thread_name_prefix=f"{source_label}ProxyCheck")
    pending: set[Future] = set()

    def _submit_next() -> bool:
        nonlocal next_index
        if next_index >= len(candidates):
            return False
        if stop_signal is not None and stop_signal.is_set():
            return False
        pending.add(executor.submit(_check, candidates[next_index]))
        next_index += 1
        return True

    for _ in range(effective_worker_count):
        if not _submit_next():
            break

    try:
        while pending:
            if stop_signal is not None and stop_signal.is_set():
                break
            done, pending = wait(pending, return_when=FIRST_COMPLETED)
            for future in done:
                checked_count += 1
                try:
                    lease = future.result()
                except Exception as exc:
                    log_suppressed_exception(f"{source_label} proxy validation worker", exc, level=logging.INFO)
                    continue
                if lease is not None and len(healthy) < result_limit:
                    healthy.append(lease)
                if not validate_all and len(healthy) >= expected:
                    stop_early = True
            _emit_progress(
                progress_callback,
                stage="validate",
                total=len(candidates),
                checked=checked_count,
                passed=len(healthy),
                expected=expected,
                workers=effective_worker_count,
                message=f"检测 {checked_count}/{len(candidates)}，可用 {len(healthy)}",
            )
            if stop_early:
                break
            while len(pending) < effective_worker_count and _submit_next():
                pass
    finally:
        for future in pending:
            if not future.done():
                future.cancel()
        executor.shutdown(wait=False, cancel_futures=True)
    logging.info(
        "%s proxy validation finished: checked=%s/%s passed=%s",
        source_label,
        checked_count,
        len(candidates),
        len(healthy),
    )
    _emit_progress(
        progress_callback,
        stage="done",
        total=len(candidates),
        checked=checked_count,
        passed=len(healthy),
        expected=expected,
        workers=effective_worker_count,
        message=f"代理池构建完成，可用 {len(healthy)} 个",
    )
    if validate_all:
        return healthy[:result_limit]
    return healthy[:expected]


def validate_proxy_leases_concurrently(
    leases: Sequence[ProxyLease],
    *,
    expected_count: int,
    timeout_seconds: float,
    max_workers: int,
    source_label: str,
    stop_signal: Optional[threading.Event] = None,
    validate_all: bool = False,
    return_limit: Optional[int] = None,
    progress_callback: Optional[ProxyPoolProgressCallback] = None,
    quiet: bool = False,
    target_url: Optional[str] = None,
) -> List[ProxyLease]:
    return _validate_proxy_leases_concurrently(
        leases,
        expected_count=expected_count,
        timeout_seconds=timeout_seconds,
        max_workers=max_workers,
        source_label=source_label,
        stop_signal=stop_signal,
        validate_all=validate_all,
        return_limit=return_limit,
        progress_callback=progress_callback,
        quiet=quiet,
        target_url=target_url,
    )


def _validate_free_proxy_pool_initially(
    leases: Sequence[ProxyLease],
    *,
    expected_count: int,
    probe_timeout_ms: Optional[int],
    max_workers: Optional[int],
    stop_signal: Optional[threading.Event] = None,
    progress_callback: Optional[ProxyPoolProgressCallback] = None,
    target_url: Optional[str] = None,
) -> List[ProxyLease]:
    candidates = [lease for lease in leases if lease is not None and str(lease.address or "").strip()]
    if not candidates:
        _emit_progress(
            progress_callback,
            stage="done",
            total=0,
            checked=0,
            passed=0,
            expected=max(1, int(expected_count or 1)),
            message="没有可检测的代理候选",
        )
        return []

    passed_by_address: dict[str, ProxyLease] = {}
    timeout_seconds = _probe_timeout_seconds(probe_timeout_ms)
    worker_count = max_workers if max_workers is not None else _FREE_POOL_VALIDATE_WORKERS
    total_checks = len(candidates) * _FREE_POOL_INITIAL_VALIDATE_ROUNDS
    checked_offset = 0

    for round_index in range(_FREE_POOL_INITIAL_VALIDATE_ROUNDS):
        if stop_signal is not None and stop_signal.is_set():
            break

        def _round_progress(payload: Dict[str, Any]) -> None:
            data = dict(payload or {})
            checked = max(0, int(data.get("checked") or 0))
            passed = max(0, int(data.get("passed") or 0))
            stage = str(data.get("stage") or "validate")
            data.update(
                {
                    "stage": "done" if stage == "done" and round_index == _FREE_POOL_INITIAL_VALIDATE_ROUNDS - 1 else "validate",
                    "round": round_index + 1,
                    "rounds": _FREE_POOL_INITIAL_VALIDATE_ROUNDS,
                    "total": total_checks,
                    "checked": min(total_checks, checked_offset + checked),
                    "passed": len(passed_by_address) + passed,
                    "message": (
                        f"第 {round_index + 1}/{_FREE_POOL_INITIAL_VALIDATE_ROUNDS} 轮快检 "
                        f"{checked}/{len(candidates)}，累计可用 {len(passed_by_address) + passed}"
                    ),
                }
            )
            _emit_progress(progress_callback, **data)

        healthy = _validate_proxy_leases_concurrently(
            candidates,
            expected_count=expected_count,
            timeout_seconds=timeout_seconds,
            max_workers=worker_count,
            source_label="Free",
            stop_signal=stop_signal,
            validate_all=True,
            return_limit=_FREE_POOL_MAX_TARGET_COUNT,
            progress_callback=_round_progress,
            quiet=True,
            target_url=target_url,
        )
        for lease in healthy:
            address = str(getattr(lease, "address", "") or "").strip()
            if address and address not in passed_by_address:
                passed_by_address[address] = lease
        checked_offset += len(candidates)

    healthy = list(passed_by_address.values())
    _emit_progress(
        progress_callback,
        stage="done",
        total=total_checks,
        checked=min(total_checks, checked_offset),
        passed=len(healthy),
        expected=max(1, int(expected_count or 1)),
        workers=max(1, min(int(worker_count or 1), _FREE_POOL_VALIDATE_WORKER_HARD_LIMIT, len(candidates))),
        rounds=_FREE_POOL_INITIAL_VALIDATE_ROUNDS,
        message=f"代理池构建完成，三轮快检累计可用 {len(healthy)} 个",
    )
    return healthy


def fetch_free_proxy_batch(
    expected_count: int = 1,
    *,
    force_refresh: bool = False,
    validate: bool = True,
    stop_signal: Optional[threading.Event] = None,
    max_workers: Optional[int] = None,
    candidate_count: Optional[int] = _SCDN_DEFAULT_CANDIDATE_COUNT,
    fetch_rounds: Optional[int] = None,
    fetch_workers: Optional[int] = _SCDN_FETCH_WORKERS,
    probe_timeout_ms: Optional[int] = None,
    progress_callback: Optional[ProxyPoolProgressCallback] = None,
    target_url: Optional[str] = None,
) -> List[ProxyLease]:
    """Fetch and validate public HTTP/SOCKS5 proxies from the aggregated free pool."""
    expected = max(1, min(_FREE_POOL_MAX_TARGET_COUNT, int(expected_count or 1)))
    addresses = _load_free_proxy_addresses(
        force_refresh=force_refresh,
        candidate_count=candidate_count,
        rounds=fetch_rounds,
        fetch_workers=fetch_workers,
        stop_signal=stop_signal,
        progress_callback=progress_callback,
    )
    if not addresses:
        raise RuntimeError("Public free proxy list is empty")

    candidates = _build_proxy_leases(addresses, limit=len(addresses), source=PROXY_SOURCE_FREE_POOL)
    if not validate:
        return candidates

    healthy = _validate_free_proxy_pool_initially(
        candidates,
        expected_count=expected,
        probe_timeout_ms=probe_timeout_ms,
        max_workers=max_workers if max_workers is not None else _FREE_POOL_VALIDATE_WORKERS,
        stop_signal=stop_signal,
        progress_callback=progress_callback,
        target_url=target_url,
    )
    if healthy:
        random.shuffle(healthy)
        return healthy
    raise RuntimeError("No usable public free proxy after validation; retry later or switch proxy source")


__all__ = [
    "PROXY_SOURCE_FREE_POOL",
    "PROXY_SOURCE_IPLIST",
    "FREE_POOL_DEFAULT_CANDIDATE_COUNT",
    "FREE_POOL_DEFAULT_FETCH_WORKERS",
    "FREE_POOL_DEFAULT_PROBE_TIMEOUT_MS",
    "FREE_POOL_DEFAULT_TARGET_COUNT",
    "FREE_POOL_DEFAULT_VALIDATE_WORKERS",
    "FREE_POOL_INITIAL_VALIDATE_ROUNDS",
    "FREE_POOL_MAX_CANDIDATE_COUNT",
    "FREE_POOL_MAX_FETCH_WORKERS",
    "FREE_POOL_MAX_TARGET_COUNT",
    "FREE_POOL_MAX_VALIDATE_WORKERS",
    "fetch_free_proxy_batch",
    "validate_proxy_leases_concurrently",
]
