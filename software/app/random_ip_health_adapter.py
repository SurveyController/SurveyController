from __future__ import annotations

import math
from datetime import UTC, datetime

import software.network.http as http_client
from software.network.config import RANDOM_IP_STATUS_ENDPOINT
from software.network.http.defaults import DEFAULT_HTTP_HEADERS

_RANDOM_IP_HEALTH_TIMEOUT_SECONDS = 5
_RANDOM_IP_MONITOR_ID = "12"
_HEARTBEAT_MAX_AGE_SECONDS = 300
_STATUS_PRESENTATIONS = {
    0: ("error", "服务异常"),
    1: ("success", "服务正常"),
    2: ("warning", "检测中"),
    3: ("warning", "维护中"),
}


class PythonRandomIpHealthAdapter:
    async def check(self) -> dict[str, str]:
        response = await http_client.aget(
            RANDOM_IP_STATUS_ENDPOINT,
            timeout=_RANDOM_IP_HEALTH_TIMEOUT_SECONDS,
            headers={**DEFAULT_HTTP_HEADERS, "Accept": "application/json"},
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict) or not isinstance(payload.get("heartbeatList"), dict):
            raise ValueError("状态页返回格式异常")
        heartbeats = payload["heartbeatList"].get(_RANDOM_IP_MONITOR_ID, [])
        if not isinstance(heartbeats, list):
            raise ValueError("随机IP提取监测记录格式异常")
        if not heartbeats:
            return {
                "level": "warning",
                "text": "状态未知",
                "tooltip": "状态页尚无随机IP提取的监测记录。",
            }
        heartbeat = heartbeats[-1]
        if not isinstance(heartbeat, dict) or not isinstance(heartbeat.get("time"), str):
            raise ValueError("随机IP提取监测记录格式异常")
        checked_at = datetime.fromisoformat(heartbeat["time"].replace("Z", "+00:00"))
        if checked_at.tzinfo is None:
            checked_at = checked_at.replace(tzinfo=UTC)
        age_seconds = (datetime.now(UTC) - checked_at).total_seconds()
        checked_text = checked_at.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")
        if age_seconds > _HEARTBEAT_MAX_AGE_SECONDS or age_seconds < -60:
            return {
                "level": "warning",
                "text": "状态未知",
                "tooltip": f"状态页监测记录未更新或时间异常，最后记录：{checked_text}。",
            }
        status = heartbeat.get("status")
        if type(status) is not int or status not in _STATUS_PRESENTATIONS:
            raise ValueError("随机IP提取监测状态无效")
        level, text = _STATUS_PRESENTATIONS[status]
        ping = heartbeat.get("ping")
        if status == 1 and type(ping) in (int, float) and math.isfinite(ping) and ping >= 0:
            text = f"{text} {ping:.0f} ms"
        return {
            "level": level,
            "text": text,
            "tooltip": f"随机IP提取：{text}。状态页最后检测：{checked_text}。",
        }


__all__ = ["PythonRandomIpHealthAdapter"]
