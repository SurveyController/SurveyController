"""Proxy response parsing helpers shared by custom APIs and public pools."""
from __future__ import annotations

import json
import re
from typing import Any, Iterable, List, Optional, Sequence, Set
from urllib.parse import urlsplit

_DEFAULT_ALLOWED_SCHEMES = ("http", "https", "socks4", "socks5")
_PROXY_CANDIDATE_RE = re.compile(
    r"(?:(?P<scheme>https?|socks4|socks5)://)?"
    r"(?:(?P<auth>[^\s:@/,'\"]+:[^\s:@/,'\"]+)@)?"
    r"(?P<host>(?:\d{1,3}\.){3}\d{1,3}|[A-Za-z0-9.-]+\.[A-Za-z]{2,}|\[[0-9A-Fa-f:.]+\])"
    r":(?P<port>\d{1,5})",
    re.IGNORECASE,
)


def _normalize_allowed_schemes(allowed_schemes: Optional[Sequence[str]]) -> Set[str]:
    raw = allowed_schemes if allowed_schemes is not None else _DEFAULT_ALLOWED_SCHEMES
    normalized = {str(item or "").strip().lower() for item in raw}
    return {item for item in normalized if item}


def _port_is_valid(port: Any) -> bool:
    try:
        parsed = int(port)
    except Exception:
        return False
    return 1 <= parsed <= 65535


def _clean_token(value: Any) -> str:
    text = str(value or "").strip()
    return text.strip("`'\"<>()[]{}")


def _normalize_proxy_token(
    value: Any,
    *,
    allowed_schemes: Optional[Sequence[str]] = None,
    default_scheme: str = "http",
) -> Optional[str]:
    token = _clean_token(value)
    if not token:
        return None
    if "://" not in token:
        scheme = str(default_scheme or "http").strip().lower() or "http"
        token = f"{scheme}://{token}"
    try:
        parsed = urlsplit(token)
    except Exception:
        return None
    scheme = str(parsed.scheme or "").lower()
    allowed = _normalize_allowed_schemes(allowed_schemes)
    if scheme not in allowed:
        return None
    try:
        parsed_port = parsed.port
    except ValueError:
        return None
    if not parsed.hostname or not _port_is_valid(parsed_port):
        return None
    netloc = parsed.netloc
    if "@" not in netloc and parsed.hostname:
        host = parsed.hostname
        if ":" in host and not host.startswith("["):
            host = f"[{host}]"
        netloc = f"{host}:{parsed_port}"
    return f"{scheme}://{netloc}"


def _iter_string_candidates(text: str, *, default_scheme: str = "http") -> Iterable[str]:
    fallback_scheme = str(default_scheme or "http").strip().lower() or "http"
    for raw_line in str(text or "").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        direct = _clean_token(line)
        if direct:
            yield direct
        for match in _PROXY_CANDIDATE_RE.finditer(line):
            scheme = (match.group("scheme") or fallback_scheme).lower()
            auth = match.group("auth") or ""
            host = match.group("host") or ""
            port = match.group("port") or ""
            if auth:
                yield f"{scheme}://{auth}@{host}:{port}"
            else:
                yield f"{scheme}://{host}:{port}"


def _append_normalized(
    results: List[str],
    seen: Set[str],
    value: Any,
    *,
    allowed_schemes: Optional[Sequence[str]],
    default_scheme: str = "http",
) -> None:
    for candidate in _iter_string_candidates(str(value or ""), default_scheme=default_scheme):
        normalized = _normalize_proxy_token(
            candidate,
            allowed_schemes=allowed_schemes,
            default_scheme=default_scheme,
        )
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        results.append(normalized)


def _extract_from_dict(
    obj: dict,
    results: List[str],
    seen: Set[str],
    *,
    allowed_schemes: Optional[Sequence[str]],
    default_scheme: str,
    depth: int,
) -> None:
    host = obj.get("ip") or obj.get("IP") or obj.get("host") or obj.get("server")
    port = obj.get("port") or obj.get("Port") or obj.get("PORT")
    if host and port:
        scheme = str(obj.get("scheme") or obj.get("protocol") or obj.get("type") or default_scheme).strip().lower()
        username = str(obj.get("account") or obj.get("username") or obj.get("user") or "").strip()
        password = str(obj.get("password") or obj.get("pwd") or obj.get("pass") or "").strip()
        auth = f"{username}:{password}@" if username and password else ""
        _append_normalized(
            results,
            seen,
            f"{scheme}://{auth}{host}:{port}",
            allowed_schemes=allowed_schemes,
            default_scheme=default_scheme,
        )

    for key in ("proxy", "address", "url", "server", "https", "http"):
        value = obj.get(key)
        if isinstance(value, str):
            _append_normalized(
                results,
                seen,
                value,
                allowed_schemes=allowed_schemes,
                default_scheme=default_scheme,
            )

    for value in obj.values():
        _recursive_find_proxies(
            value,
            results,
            seen,
            allowed_schemes=allowed_schemes,
            default_scheme=default_scheme,
            depth=depth + 1,
        )


def _recursive_find_proxies(
    data: Any,
    results: List[str],
    seen: Set[str],
    *,
    allowed_schemes: Optional[Sequence[str]],
    default_scheme: str = "http",
    depth: int = 0,
) -> None:
    if depth > 10:
        return
    if isinstance(data, dict):
        _extract_from_dict(
            data,
            results,
            seen,
            allowed_schemes=allowed_schemes,
            default_scheme=default_scheme,
            depth=depth,
        )
        return
    if isinstance(data, list):
        for item in data:
            _recursive_find_proxies(
                item,
                results,
                seen,
                allowed_schemes=allowed_schemes,
                default_scheme=default_scheme,
                depth=depth + 1,
            )
        return
    if isinstance(data, str):
        _append_normalized(
            results,
            seen,
            data,
            allowed_schemes=allowed_schemes,
            default_scheme=default_scheme,
        )


def parse_proxy_payload(
    text: str,
    *,
    allowed_schemes: Optional[Sequence[str]] = None,
    default_scheme: str = "http",
) -> List[str]:
    """Extract unique proxy URLs from JSON or plain text responses."""
    results: List[str] = []
    seen: Set[str] = set()
    raw = str(text or "")

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        data = None
    if data is not None:
        _recursive_find_proxies(
            data,
            results,
            seen,
            allowed_schemes=allowed_schemes,
            default_scheme=default_scheme,
        )

    for raw_line in raw.splitlines():
        line = raw_line.strip()
        if not line or line[0] not in "[{":
            continue
        try:
            line_data = json.loads(line)
        except json.JSONDecodeError:
            continue
        _recursive_find_proxies(
            line_data,
            results,
            seen,
            allowed_schemes=allowed_schemes,
            default_scheme=default_scheme,
        )

    _append_normalized(
        results,
        seen,
        raw,
        allowed_schemes=allowed_schemes,
        default_scheme=default_scheme,
    )
    return results


__all__ = ["parse_proxy_payload"]
