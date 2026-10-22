from __future__ import annotations

import random
from collections.abc import Sequence
from typing import Protocol

from surveycore.core.user_agent import UserAgentProfile

USER_AGENT_PRESETS = {
    "pc_web": {
        "label": "电脑网页端",
        "ua": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    },
    "mobile_android": {
        "label": "安卓手机浏览器",
        "ua": "Mozilla/5.0 (Linux; Android 16; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Mobile Safari/537.36",
    },
    "wechat_android": {
        "label": "安卓微信端",
        "ua": "Mozilla/5.0 (Linux; Android 16; Pixel 8 Build/BP22.250124.009; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/121.0.0.0 Mobile Safari/537.36 MicroMessenger/8.0.43.2460(0x28002B3B) Process/appbrand0 WeChat/arm64 Weixin NetType/WIFI Language/zh_CN ABI/arm64",
    },
}

DEFAULT_USER_AGENT = USER_AGENT_PRESETS["pc_web"]["ua"]


class UserAgentRandomSource(Protocol):
    def choices(
        self,
        population: Sequence[str],
        *,
        weights: Sequence[int],
        k: int,
    ) -> list[str]: ...

    def choice(self, sequence: Sequence[str]) -> str: ...


def select_user_agent_from_ratios(
    ratios: dict[str, int],
    *,
    rng: UserAgentRandomSource | None = None,
) -> UserAgentProfile | None:
    chooser = rng if rng is not None else random
    device_presets = {
        "wechat": ("wechat_android",),
        "mobile": ("mobile_android",),
        "pc": ("pc_web",),
    }
    devices: list[str] = []
    weights: list[int] = []
    for device_type, preset_keys in device_presets.items():
        if not preset_keys:
            continue
        try:
            weight = max(0, int((ratios or {}).get(device_type, 0) or 0))
        except (TypeError, ValueError):
            weight = 0
        if weight > 0:
            devices.append(device_type)
            weights.append(weight)
    if not devices:
        return None

    device_type = chooser.choices(devices, weights=weights, k=1)[0]
    preset_key = chooser.choice(device_presets.get(device_type, ()))
    preset = USER_AGENT_PRESETS.get(preset_key) or {}
    user_agent = str(preset.get("ua") or "").strip()
    if not user_agent:
        return None
    return UserAgentProfile(
        category=device_type,
        preset_key=preset_key,
        ua=user_agent,
        label=str(preset.get("label") or "").strip(),
    )


__all__ = [
    "DEFAULT_USER_AGENT",
    "UserAgentRandomSource",
    "USER_AGENT_PRESETS",
    "select_user_agent_from_ratios",
]
