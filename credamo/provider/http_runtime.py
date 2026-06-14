"""Credamo 见数 HTTP 解析辅助。"""

from __future__ import annotations

import hashlib
import random
import re
import time
from typing import Any, Mapping
from urllib.parse import urlparse

import httpx

from software.app.config import DEFAULT_HTTP_HEADERS, DEFAULT_USER_AGENT

_CIPHER = "bdd048cdbf5a382d"
_RANDOM_CHARS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
_DEFAULT_ORIGIN = "https://www.credamo.com"
_CREDAMO_REQUEST_TIMEOUT_SECONDS = 30


class _CredamoHttpSession:
    def __init__(self, proxy_address: str | None = None) -> None:
        self.proxy_address = str(proxy_address or "").strip()
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> "_CredamoHttpSession":
        self._client = httpx.AsyncClient(
            proxy=_resolve_httpx_proxy(self.proxy_address),
            follow_redirects=True,
            trust_env=not bool(self.proxy_address),
            timeout=None,
        )
        return self

    async def __aexit__(self, *_exc: Any) -> None:
        if self._client is not None:
            await self._client.aclose()
        self._client = None

    def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None:
            raise RuntimeError("见数 HTTP 会话尚未启动")
        return self._client

    async def get(self, url: str, **kwargs: Any) -> httpx.Response:
        return await self._ensure_client().get(url, **kwargs)


def _resolve_httpx_proxy(proxy_address: str) -> str | None:
    proxy = str(proxy_address or "").strip()
    return proxy if proxy else None


def _origin_from_url(url: str) -> str:
    parsed = urlparse(str(url or "").strip())
    if parsed.scheme and parsed.netloc:
        return f"{parsed.scheme}://{parsed.netloc}"
    return _DEFAULT_ORIGIN


def _short_url_from_url(url: str) -> str:
    text = str(url or "").strip()
    parsed = urlparse(text)
    candidates = [parsed.path, parsed.fragment, text]
    for candidate in candidates:
        clean = str(candidate or "").strip().lstrip("#").split("?", 1)[0].rstrip("/")
        if not clean:
            continue
        parts = [part for part in clean.split("/") if part]
        if "s" in parts:
            index = parts.index("s")
            if index + 1 < len(parts):
                return parts[index + 1].strip()
        if re.fullmatch(r"[A-Za-z0-9_]+(?:ano)?", clean):
            return clean
    raise RuntimeError("见数链接缺少短链接编号")


def _noauth_short_url(short_url: str) -> str:
    short = str(short_url or "").strip().rstrip("/")
    if short.endswith("_"):
        return f"{short[:-1]}ano"
    if short.endswith("ano"):
        return short
    raise RuntimeError("见数 HTTP 目前只支持免登录短链接")


def _answer_page_url(origin: str, short_url: str) -> str:
    return f"{origin.rstrip('/')}/answer.html#/s/{short_url}"


def _sha1_upper(value: str) -> str:
    return hashlib.sha1(str(value or "").encode("utf-8")).hexdigest().upper()


def _random_token(length: int) -> str:
    return "".join(random.choice(_RANDOM_CHARS) for _ in range(max(1, int(length or 1))))


def _build_signature_headers(
    *,
    answer_token: str = "",
    union_id: str | None = None,
    nonce: str | None = None,
    timestamp_ms: int | str | None = None,
) -> dict[str, str]:
    token = str(answer_token or "")
    union = str(union_id or _random_token(10))
    nonce_value = str(nonce or _random_token(16))
    timestamp = str(timestamp_ms if timestamp_ms is not None else int(time.time() * 1000))
    inner = _sha1_upper(f"{token}{nonce_value}{timestamp}{union}{_CIPHER}")
    signature = _sha1_upper(f"{token}{nonce_value}{timestamp}{inner}{union}{_CIPHER}")
    return {
        "unionId": union,
        "nonce": nonce_value,
        "timestamp": timestamp,
        "signature": signature,
    }


def _request_headers(
    *,
    origin: str,
    short_url: str,
    user_agent: str | None = None,
    answer_token: str = "",
) -> dict[str, str]:
    return {
        **DEFAULT_HTTP_HEADERS,
        "User-Agent": str(user_agent or "").strip() or DEFAULT_USER_AGENT,
        "Accept": "application/json, text/plain, */*",
        "Referer": _answer_page_url(origin, short_url),
        **_build_signature_headers(answer_token=answer_token),
    }


def _json_payload(response: Any, label: str) -> Mapping[str, Any]:
    try:
        payload = response.json()
    except Exception:
        response.raise_for_status()
        raise RuntimeError(f"见数{label}接口返回了非 JSON 内容")
    if getattr(response, "is_error", False):
        message = ""
        if isinstance(payload, Mapping):
            message = str(payload.get("message") or payload.get("msg") or payload.get("code") or "").strip()
        if message:
            raise RuntimeError(f"见数{label}失败：{message}")
        response.raise_for_status()
    if not isinstance(payload, Mapping):
        raise RuntimeError(f"见数{label}接口返回了非 JSON 对象")
    return payload


def _ensure_api_ok(payload: Mapping[str, Any], label: str) -> Mapping[str, Any]:
    if payload.get("success") is False:
        message = str(payload.get("message") or payload.get("msg") or payload.get("code") or payload).strip()
        raise RuntimeError(f"见数{label}失败：{message}")
    code = payload.get("code")
    if code not in (None, "", 0, "0", "OK", "ok", "SUCCESS", "success"):
        message = str(payload.get("message") or payload.get("msg") or code).strip()
        raise RuntimeError(f"见数{label}失败：{message}")
    data = payload.get("data")
    return data if isinstance(data, Mapping) else payload


async def _fetch_detail(
    session: _CredamoHttpSession,
    *,
    origin: str,
    short_url: str,
    headers: dict[str, str],
) -> Mapping[str, Any]:
    response = await session.get(
        f"{origin.rstrip('/')}/v1/survey/noauth/detail/get/{short_url}",
        headers=headers,
        timeout=_CREDAMO_REQUEST_TIMEOUT_SECONDS,
    )
    return _ensure_api_ok(_json_payload(response, "详情"), "详情")


def _as_mapping_list(value: Any) -> list[Mapping[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def _iter_raw_questions(detail_data: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    result: list[Mapping[str, Any]] = []
    direct_questions = _as_mapping_list(detail_data.get("questions"))
    if direct_questions:
        result.extend(direct_questions)
    for block in _as_mapping_list(detail_data.get("blocks")):
        for element in _as_mapping_list(block.get("blockElements") or block.get("elements")):
            candidates = [
                element.get("question"),
                element.get("qst"),
                element.get("surveyQuestion"),
                element,
            ]
            for candidate in candidates:
                if not isinstance(candidate, Mapping):
                    continue
                if candidate.get("qstId") or candidate.get("questionId") or candidate.get("questionType"):
                    result.append(candidate)
                    break
    return result


def _raw_question_num(raw_question: Mapping[str, Any], fallback_num: int) -> int:
    for key in ("qstNo", "questionNo", "qstNum", "sortNo"):
        match = re.search(r"\d+", str(raw_question.get(key) or ""))
        if match:
            return max(1, int(match.group(0)))
    return max(1, int(fallback_num or 1))


def _raw_question_type(raw_question: Mapping[str, Any]) -> int:
    try:
        return int(raw_question.get("questionType") or 0)
    except Exception:
        return 0


def _raw_selector(raw_question: Mapping[str, Any]) -> int:
    try:
        return int(raw_question.get("selector") or 0)
    except Exception:
        return 0


def _raw_provider_type(raw_question: Mapping[str, Any]) -> str:
    question_type = _raw_question_type(raw_question)
    selector = _raw_selector(raw_question)
    if question_type == 2 and selector == 2:
        return "multiple"
    if question_type == 2 and selector == 3:
        return "dropdown"
    if question_type == 2:
        return "single"
    if question_type == 4:
        return "matrix"
    if question_type == 6:
        return "order"
    if question_type == 11:
        return "scale"
    if question_type == 1:
        return "text"
    return str(question_type or "")


def _raw_option_count(raw_question: Mapping[str, Any]) -> int:
    question_type = _raw_question_type(raw_question)
    if question_type == 4:
        return len(_as_mapping_list(raw_question.get("answers")))
    if question_type == 1:
        return 1
    return len(_as_mapping_list(raw_question.get("choices")))


def _raw_row_count(raw_question: Mapping[str, Any]) -> int:
    if _raw_question_type(raw_question) == 4:
        return max(1, len(_as_mapping_list(raw_question.get("choices"))))
    return 1


__all__ = [
    "_CredamoHttpSession",
    "_as_mapping_list",
    "_fetch_detail",
    "_iter_raw_questions",
    "_noauth_short_url",
    "_origin_from_url",
    "_raw_option_count",
    "_raw_provider_type",
    "_raw_question_num",
    "_raw_question_type",
    "_raw_row_count",
    "_request_headers",
    "_short_url_from_url",
]
