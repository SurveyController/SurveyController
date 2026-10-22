from __future__ import annotations

import time

import software.network.http as http_client
from software.network.config import IP_EXTRACT_ENDPOINT
from software.network.http.defaults import DEFAULT_HTTP_HEADERS

_RANDOM_IP_HEALTH_TIMEOUT_SECONDS = 5
_RANDOM_IP_HEALTH_TOKEN = "status-rzib9lqpuk3httr4"


class PythonRandomIpHealthAdapter:
    async def check(self) -> dict[str, str]:
        headers = {
            **DEFAULT_HTTP_HEADERS,
            "X-Health-Token": _RANDOM_IP_HEALTH_TOKEN,
            "Content-Type": "application/json",
        }
        started = time.perf_counter()
        response = await http_client.apost(
            IP_EXTRACT_ENDPOINT,
            json={},
            timeout=_RANDOM_IP_HEALTH_TIMEOUT_SECONDS,
            headers=headers,
        )
        elapsed_ms = max(1, int(round((time.perf_counter() - started) * 1000)))
        status_code = int(getattr(response, "status_code", 0) or 0)
        if 200 <= status_code < 300:
            return {
                "level": "success",
                "text": f"服务正常 {elapsed_ms} ms",
                "tooltip": f"随机IP提取接口返回 HTTP {status_code}，耗时 {elapsed_ms} ms。",
            }
        return {
            "level": "error",
            "text": f"异常 {status_code or 0}",
            "tooltip": f"随机IP提取接口返回 HTTP {status_code or 0}，耗时 {elapsed_ms} ms。",
        }


__all__ = ["PythonRandomIpHealthAdapter"]
