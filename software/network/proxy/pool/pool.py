"""代理池和租约管理 - 代理租约构建、TTL检查、地址规范化、健康检查"""
from datetime import datetime, timezone
import ipaddress
import logging
import socket
import ssl
import time
from urllib.parse import urlsplit
from typing import Any, List, Optional, Tuple

import software.network.http as http_client
from software.core.task import ProxyLease
from software.app.config import (
    PROXY_HEALTH_CHECK_TIMEOUT,
    PROXY_HEALTH_CHECK_URL,
    PROXY_SOURCE_DEFAULT,
    PROXY_TTL_GRACE_SECONDS,
)
from software.logging.log_utils import log_suppressed_exception
from software.network.proxy.policy.source import (
    _to_non_negative_int,
    get_proxy_source,
    is_official_proxy_source,
)


# ==================== 地址规范化 ====================

def _normalize_proxy_address(proxy_address: Optional[str]) -> Optional[str]:
    if not proxy_address:
        return None
    normalized = proxy_address.strip()
    if not normalized:
        return None
    if "://" not in normalized:
        normalized = f"http://{normalized}"
    return normalized


def _format_host_port(hostname: str, port: Optional[int]) -> str:
    if not hostname:
        return ""
    if port is None:
        return hostname
    if ":" in hostname and not hostname.startswith("["):
        return f"[{hostname}]:{port}"
    return f"{hostname}:{port}"


def _mask_proxy_for_log(proxy_address: Optional[str]) -> str:
    if not proxy_address:
        return ""
    text = str(proxy_address).strip()
    if not text:
        return ""
    if not is_official_proxy_source(get_proxy_source()):
        return text
    candidate = text if "://" in text else f"http://{text}"
    try:
        parsed = urlsplit(candidate)
        host_port = _format_host_port(parsed.hostname or "", parsed.port)
        if host_port:
            return host_port
    except Exception as exc:
        log_suppressed_exception("random_ip._mask_proxy_for_log parse proxy", exc)
    raw = text
    if "://" in raw:
        raw = raw.split("://", 1)[1]
    raw = raw.split("/", 1)[0]
    if "@" in raw:
        raw = raw.split("@", 1)[1]
    return raw


# ==================== 租约构建 ====================

def _parse_expire_at_to_ts(expire_at: Optional[str]) -> float:
    text = str(expire_at or "").strip()
    if not text:
        return 0.0
    try:
        parsed = datetime.fromisoformat(text)
    except Exception:
        logging.info("代理 expire_at 解析失败：%s", text, exc_info=True)
        return 0.0
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return float(parsed.astimezone(timezone.utc).timestamp())


def _build_proxy_lease(
    proxy_address: Optional[str],
    *,
    expire_at: Optional[str] = None,
    poolable: bool = True,
    source: str = "",
) -> Optional[ProxyLease]:
    normalized = _normalize_proxy_address(proxy_address)
    if not normalized:
        return None
    expire_text = str(expire_at or "").strip()
    return ProxyLease(
        address=normalized,
        expire_at=expire_text,
        expire_ts=_parse_expire_at_to_ts(expire_text),
        poolable=bool(poolable),
        source=str(source or "").strip(),
    )


def _coerce_proxy_lease(item: Any, *, source: str = "") -> Optional[ProxyLease]:
    if isinstance(item, ProxyLease):
        normalized = _normalize_proxy_address(item.address)
        if not normalized:
            return None
        if normalized == item.address:
            return item
        return ProxyLease(
            address=normalized,
            expire_at=item.expire_at,
            expire_ts=float(item.expire_ts or 0.0),
            poolable=bool(item.poolable),
            source=item.source,
        )
    if isinstance(item, str):
        return _build_proxy_lease(item, source=source)
    if isinstance(item, dict):
        address = item.get("address") or item.get("proxy") or item.get("host")
        expire_at = item.get("expire_at")
        poolable = bool(item.get("poolable", True))
        item_source = str(item.get("source") or source or "").strip()
        if address and item.get("port") and isinstance(address, str) and ":" not in address:
            address = f"{address}:{item.get('port')}"
        return _build_proxy_lease(address, expire_at=expire_at, poolable=poolable, source=item_source)
    return None


# ==================== TTL 检查 ====================

def get_proxy_required_ttl_seconds(answer_duration_range_seconds: Optional[Tuple[int, int]]) -> int:
    max_seconds = 0
    if isinstance(answer_duration_range_seconds, (list, tuple)):
        if len(answer_duration_range_seconds) >= 2:
            max_seconds = _to_non_negative_int(answer_duration_range_seconds[1], 0)
        elif len(answer_duration_range_seconds) >= 1:
            max_seconds = _to_non_negative_int(answer_duration_range_seconds[0], 0)
    return max(0, int(max_seconds)) + PROXY_TTL_GRACE_SECONDS


def proxy_lease_has_sufficient_ttl(lease: Optional[ProxyLease], *, required_ttl_seconds: int) -> bool:
    if lease is None:
        return False
    expire_ts = float(getattr(lease, "expire_ts", 0.0) or 0.0)
    if expire_ts <= 0:
        return True
    return (expire_ts - time.time()) >= max(0, int(required_ttl_seconds or 0))


# ==================== 默认代理构建 ====================

def _build_default_proxy_lease(payload: dict, *, source: str = PROXY_SOURCE_DEFAULT) -> Optional[ProxyLease]:
    if not isinstance(payload, dict):
        return None
    host = str(payload.get("host") or "").strip()
    port = _to_non_negative_int(payload.get("port"), 0)
    if not host or port <= 0:
        return None
    account = str(payload.get("account") or "").strip()
    password = str(payload.get("password") or "").strip()
    raw = f"{account}:{password}@{host}:{port}" if account and password else f"{host}:{port}"
    expire_at = str(payload.get("expire_at") or "").strip()
    poolable = True
    if not expire_at:
        logging.warning("默认随机IP响应缺少 expire_at，该代理仅允许立即使用，不会进入代理池")
        poolable = False
    return _build_proxy_lease(raw, expire_at=expire_at, poolable=poolable, source=source)


def _build_default_proxy_leases_from_batch(payload: dict, *, source: str = PROXY_SOURCE_DEFAULT) -> List[ProxyLease]:
    if not isinstance(payload, dict):
        return []
    raw_items = payload.get("items")
    if not isinstance(raw_items, list):
        return []
    leases: List[ProxyLease] = []
    for raw in raw_items:
        if not isinstance(raw, dict):
            continue
        lease = _build_default_proxy_lease(raw, source=source)
        if lease is None:
            continue
        leases.append(lease)
        logging.info("获取到代理: %s", _mask_proxy_for_log(lease.address))
    return leases


# ==================== 健康检查 ====================

def _proxy_is_responsive(
    proxy_address: str,
    skip_for_default: bool = True,
    *,
    timeout: Optional[float] = None,
    log_failures: bool = True,
    log_success: bool = True,
) -> bool:
    masked_proxy = _mask_proxy_for_log(proxy_address)
    if skip_for_default and is_official_proxy_source(get_proxy_source()):
        if log_success:
            logging.info(f"官方代理源，跳过健康检查: {masked_proxy}")
        return True
    proxy_address = _normalize_proxy_address(proxy_address) or ""
    if not proxy_address:
        return False
    proxies = {"http": proxy_address, "https": proxy_address}
    try:
        start = time.perf_counter()
        response = http_client.get(
            PROXY_HEALTH_CHECK_URL,
            proxies=proxies,
            timeout=float(timeout if timeout is not None else PROXY_HEALTH_CHECK_TIMEOUT),
        )
        elapsed = time.perf_counter() - start
    except Exception as exc:
        if log_failures:
            logging.info(f"代理 {masked_proxy} 验证失败: {exc}")
        return False
    if response.status_code >= 400:
        if log_failures:
            logging.warning(f"代理 {masked_proxy} 返回状态码 {response.status_code}")
        return False
    if log_success:
        logging.info(f"代理 {masked_proxy} 验证通过，耗时 {elapsed:.2f}s")
    return True


def _proxy_connect_probe(
    proxy_address: str,
    *,
    target_url: str = PROXY_HEALTH_CHECK_URL,
    timeout: Optional[float] = None,
    log_failures: bool = True,
    log_success: bool = True,
) -> bool:
    masked_proxy = _mask_proxy_for_log(proxy_address)
    proxy_address = _normalize_proxy_address(proxy_address) or ""
    if not proxy_address:
        return False

    parsed_proxy = urlsplit(proxy_address)
    proxy_host = parsed_proxy.hostname or ""
    proxy_scheme = str(parsed_proxy.scheme or "http").lower()
    try:
        proxy_port = int(parsed_proxy.port or (443 if proxy_scheme == "https" else 1080 if proxy_scheme in {"socks5", "socks5h"} else 80))
    except ValueError:
        return False
    if not proxy_host or proxy_port <= 0:
        return False
    if proxy_scheme in {"socks5", "socks5h"}:
        return _proxy_socks5_probe(
            proxy_address,
            target_url=target_url,
            timeout=timeout,
            log_failures=log_failures,
            log_success=log_success,
        )

    parsed_target = urlsplit(target_url or PROXY_HEALTH_CHECK_URL)
    target_scheme = str(parsed_target.scheme or "https").lower()
    target_host = parsed_target.hostname or "www.wjx.cn"
    target_port = int(parsed_target.port or (443 if target_scheme == "https" else 80))
    target_path = parsed_target.path or "/"
    if parsed_target.query:
        target_path = f"{target_path}?{parsed_target.query}"
    probe_timeout = max(0.3, float(timeout if timeout is not None else PROXY_HEALTH_CHECK_TIMEOUT))
    connect_request = (
        f"CONNECT {target_host}:{target_port} HTTP/1.1\r\n"
        f"Host: {target_host}:{target_port}\r\n"
        "Proxy-Connection: close\r\n"
        "User-Agent: SurveyControllerProxyProbe/1.0\r\n"
        "\r\n"
    ).encode("ascii", errors="ignore")
    origin_request = (
        f"HEAD {target_path} HTTP/1.1\r\n"
        f"Host: {target_host}\r\n"
        "Connection: close\r\n"
        "User-Agent: SurveyControllerProxyProbe/1.0\r\n"
        "\r\n"
    ).encode("ascii", errors="ignore")

    start = time.perf_counter()
    raw_sock: Optional[socket.socket] = None
    wrapped_sock: Optional[socket.socket] = None
    tunnel_sock: Optional[socket.socket] = None
    try:
        raw_sock = socket.create_connection((proxy_host, proxy_port), timeout=probe_timeout)
        raw_sock.settimeout(probe_timeout)
        if proxy_scheme == "https":
            context = ssl.create_default_context()
            wrapped_sock = context.wrap_socket(raw_sock, server_hostname=proxy_host)
            sock = wrapped_sock
            raw_sock = None
        else:
            sock = raw_sock
        sock.sendall(connect_request)
        chunks: list[bytes] = []
        header_data = b""
        while len(header_data) < 4096:
            chunk = sock.recv(256)
            if not chunk:
                break
            chunks.append(chunk)
            header_data = b"".join(chunks)
            if b"\r\n\r\n" in header_data or b"\n\n" in header_data:
                break
    except Exception as exc:
        for close_sock in (wrapped_sock, raw_sock):
            if close_sock is None:
                continue
            try:
                close_sock.close()
            except Exception:
                pass
        if log_failures:
            logging.info("浠ｇ悊 %s CONNECT 快检失败: %s", masked_proxy, exc)
        return False
    except BaseException:
        for close_sock in (wrapped_sock, raw_sock):
            if close_sock is None:
                continue
            try:
                close_sock.close()
            except Exception:
                pass
        raise

    first_line = header_data.splitlines()[0].decode("latin1", errors="ignore") if header_data else ""
    parts = first_line.split()
    status_code = 0
    if len(parts) >= 2:
        try:
            status_code = int(parts[1])
        except Exception:
            status_code = 0
    ok = 200 <= status_code < 300
    if ok:
        try:
            tunnel_sock = wrapped_sock or raw_sock
            wrapped_sock = None
            raw_sock = None
            if tunnel_sock is None:
                return False
            tunnel_sock.settimeout(probe_timeout)
            if target_scheme == "https":
                target_context = ssl.create_default_context()
                tunnel_sock = target_context.wrap_socket(tunnel_sock, server_hostname=target_host)
                tunnel_sock.settimeout(probe_timeout)
            tunnel_sock.sendall(origin_request)
            origin_data = tunnel_sock.recv(256)
            origin_first_line = origin_data.splitlines()[0].decode("latin1", errors="ignore") if origin_data else ""
        except Exception as exc:
            if log_failures:
                logging.info("代理 %s 目标站 TLS/HTTP 快检失败: %s", masked_proxy, exc)
            return False
        finally:
            for close_sock in (tunnel_sock, wrapped_sock, raw_sock):
                if close_sock is None:
                    continue
                try:
                    close_sock.close()
                except Exception:
                    pass
        if origin_first_line.startswith("HTTP/"):
            if log_success:
                logging.info("代理 %s 目标站快检通过，耗时 %.2fs", masked_proxy, time.perf_counter() - start)
            return True
        if log_failures:
            logging.info("代理 %s 目标站快检无有效响应: %s", masked_proxy, origin_first_line or "<empty>")
        return False
    for close_sock in (wrapped_sock, raw_sock):
        if close_sock is None:
            continue
        try:
            close_sock.close()
        except Exception:
            pass
    if log_failures:
        logging.info("浠ｇ悊 %s CONNECT 快检返回异常: %s", masked_proxy, first_line or "<empty>")
    return False


def _recv_exact(sock: socket.socket, size: int) -> bytes:
    chunks: list[bytes] = []
    remaining = max(0, int(size or 0))
    while remaining > 0:
        chunk = sock.recv(remaining)
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def _build_socks5_target_address(host: str, port: int) -> bytes:
    target_host = str(host or "").strip()
    try:
        ip = ipaddress.ip_address(target_host)
    except ValueError:
        host_bytes = target_host.encode("idna")
        if not host_bytes or len(host_bytes) > 255:
            raise ValueError("invalid SOCKS5 target host")
        address = bytes([0x03, len(host_bytes)]) + host_bytes
    else:
        if ip.version == 4:
            address = b"\x01" + ip.packed
        else:
            address = b"\x04" + ip.packed
    return address + int(port).to_bytes(2, "big")


def _proxy_socks5_probe(
    proxy_address: str,
    *,
    target_url: str = PROXY_HEALTH_CHECK_URL,
    timeout: Optional[float] = None,
    log_failures: bool = True,
    log_success: bool = True,
) -> bool:
    masked_proxy = _mask_proxy_for_log(proxy_address)
    parsed_proxy = urlsplit(_normalize_proxy_address(proxy_address) or "")
    proxy_host = parsed_proxy.hostname or ""
    try:
        proxy_port = int(parsed_proxy.port or 1080)
    except ValueError:
        return False
    if not proxy_host or proxy_port <= 0:
        return False

    parsed_target = urlsplit(target_url or PROXY_HEALTH_CHECK_URL)
    target_scheme = str(parsed_target.scheme or "https").lower()
    target_host = parsed_target.hostname or "www.wjx.cn"
    target_port = int(parsed_target.port or (443 if target_scheme == "https" else 80))
    target_path = parsed_target.path or "/"
    if parsed_target.query:
        target_path = f"{target_path}?{parsed_target.query}"
    probe_timeout = max(0.3, float(timeout if timeout is not None else PROXY_HEALTH_CHECK_TIMEOUT))
    origin_request = (
        f"HEAD {target_path} HTTP/1.1\r\n"
        f"Host: {target_host}\r\n"
        "Connection: close\r\n"
        "User-Agent: SurveyControllerProxyProbe/1.0\r\n"
        "\r\n"
    ).encode("ascii", errors="ignore")
    username = parsed_proxy.username or ""
    password = parsed_proxy.password or ""
    start = time.perf_counter()
    sock: Optional[socket.socket] = None
    try:
        sock = socket.create_connection((proxy_host, proxy_port), timeout=probe_timeout)
        sock.settimeout(probe_timeout)
        methods = b"\x00\x02" if username and password else b"\x00"
        sock.sendall(b"\x05" + bytes([len(methods)]) + methods)
        method_response = _recv_exact(sock, 2)
        if len(method_response) != 2 or method_response[0] != 0x05 or method_response[1] == 0xFF:
            return False
        if method_response[1] == 0x02:
            user_bytes = username.encode("utf-8", errors="ignore")[:255]
            pass_bytes = password.encode("utf-8", errors="ignore")[:255]
            sock.sendall(b"\x01" + bytes([len(user_bytes)]) + user_bytes + bytes([len(pass_bytes)]) + pass_bytes)
            auth_response = _recv_exact(sock, 2)
            if len(auth_response) != 2 or auth_response[1] != 0x00:
                return False
        elif method_response[1] != 0x00:
            return False

        sock.sendall(b"\x05\x01\x00" + _build_socks5_target_address(target_host, target_port))
        header = _recv_exact(sock, 4)
        if len(header) != 4 or header[0] != 0x05 or header[1] != 0x00:
            return False
        address_type = header[3]
        if address_type == 0x01:
            _recv_exact(sock, 4)
        elif address_type == 0x03:
            length_raw = _recv_exact(sock, 1)
            if len(length_raw) != 1:
                return False
            _recv_exact(sock, length_raw[0])
        elif address_type == 0x04:
            _recv_exact(sock, 16)
        else:
            return False
        bound_port = _recv_exact(sock, 2)
        if len(bound_port) != 2:
            return False

        tunnel_sock: socket.socket = sock
        if target_scheme == "https":
            target_context = ssl.create_default_context()
            tunnel_sock = target_context.wrap_socket(sock, server_hostname=target_host)
            sock = tunnel_sock
            tunnel_sock.settimeout(probe_timeout)
        tunnel_sock.sendall(origin_request)
        origin_data = tunnel_sock.recv(256)
        origin_first_line = origin_data.splitlines()[0].decode("latin1", errors="ignore") if origin_data else ""
        if origin_first_line.startswith("HTTP/"):
            if log_success:
                logging.info("SOCKS5 浠ｇ悊 %s 鐩爣绔欏揩妫€閫氳繃锛岃€楁椂 %.2fs", masked_proxy, time.perf_counter() - start)
            return True
        if log_failures:
            logging.info("SOCKS5 浠ｇ悊 %s 鐩爣绔欏揩妫€鏃犳湁鏁堝搷搴? %s", masked_proxy, origin_first_line or "<empty>")
        return False
    except Exception as exc:
        if log_failures:
            logging.info("SOCKS5 浠ｇ悊 %s 蹇澶辫触: %s", masked_proxy, exc)
        return False
    finally:
        if sock is not None:
            try:
                sock.close()
            except Exception:
                pass


def normalize_proxy_address(proxy_address: Optional[str]) -> Optional[str]:
    """公开的代理地址规范化接口。"""
    return _normalize_proxy_address(proxy_address)


def mask_proxy_for_log(proxy_address: Optional[str]) -> str:
    """公开的代理日志脱敏接口。"""
    return _mask_proxy_for_log(proxy_address)


def coerce_proxy_lease(item: Any, *, source: str = "") -> Optional[ProxyLease]:
    """公开的代理租约标准化接口。"""
    return _coerce_proxy_lease(item, source=source)


def is_proxy_responsive(
    proxy_address: str,
    *,
    skip_for_default: bool = True,
    timeout: Optional[float] = None,
    log_failures: bool = True,
    log_success: bool = True,
) -> bool:
    """公开的代理可用性检测接口。"""
    return _proxy_is_responsive(
        proxy_address,
        skip_for_default=skip_for_default,
        timeout=timeout,
        log_failures=log_failures,
        log_success=log_success,
    )


def is_http_proxy_connect_responsive(
    proxy_address: str,
    *,
    target_url: str = PROXY_HEALTH_CHECK_URL,
    timeout: Optional[float] = None,
    log_failures: bool = True,
    log_success: bool = True,
) -> bool:
    """Fast HTTP CONNECT probe for proxy validation without loading a full page."""
    return _proxy_connect_probe(
        proxy_address,
        target_url=target_url,
        timeout=timeout,
        log_failures=log_failures,
        log_success=log_success,
    )


__all__ = [
    "coerce_proxy_lease",
    "get_proxy_required_ttl_seconds",
    "is_http_proxy_connect_responsive",
    "is_proxy_responsive",
    "mask_proxy_for_log",
    "normalize_proxy_address",
    "proxy_lease_has_sufficient_ttl",
]



