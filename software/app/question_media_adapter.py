from __future__ import annotations

import asyncio
import ipaddress
import socket
from urllib.parse import urlsplit

import software.network.http as http_client

_MAX_MEDIA_BYTES = 5 * 1024 * 1024
_MEDIA_TIMEOUT_SECONDS = 8


def _is_public_http_url(url: str) -> bool:
    text = str(url or "").strip()
    if not text:
        return False
    try:
        parsed = urlsplit(text)
    except Exception:
        return False
    if str(parsed.scheme or "").strip().lower() not in {"http", "https"}:
        return False
    hostname = str(parsed.hostname or "").strip()
    if not hostname:
        return False
    try:
        return ipaddress.ip_address(hostname).is_global
    except ValueError:
        pass
    try:
        addresses = socket.getaddrinfo(hostname, None)
    except Exception:
        return False
    for family, _type, _proto, _canonname, sockaddr in addresses:
        if family not in (socket.AF_INET, socket.AF_INET6):
            continue
        try:
            if not ipaddress.ip_address(sockaddr[0]).is_global:
                return False
        except ValueError:
            return False
    return bool(addresses)


async def fetch_question_media(url: str) -> bytes:
    source_url = str(url or "").strip()
    try:
        if not await asyncio.to_thread(_is_public_http_url, source_url):
            return b""
    except Exception:
        return b""

    response = None
    try:
        response = await http_client.aget(
            source_url,
            timeout=_MEDIA_TIMEOUT_SECONDS,
            proxies={},
            allow_redirects=False,
            stream=True,
        )
        response.raise_for_status()
        content_length = response.headers.get("content-length")
        if content_length:
            try:
                if int(content_length) > _MAX_MEDIA_BYTES:
                    return b""
            except ValueError:
                pass

        chunks: list[bytes] = []
        total = 0
        async for chunk in response.aiter_content(65536):
            total += len(chunk)
            if total > _MAX_MEDIA_BYTES:
                return b""
            chunks.append(bytes(chunk))
        return b"".join(chunks)
    except Exception:
        return b""
    finally:
        if response is not None:
            try:
                await response.aclose()
            except Exception:
                pass


__all__ = ["fetch_question_media"]
