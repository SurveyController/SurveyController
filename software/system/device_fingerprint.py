from __future__ import annotations

import uuid

from software.app.settings_store import app_settings
from software.system.secure_store import read_secret

_DEVICE_ID_PREFIX = "sc-v2-"
_DEVICE_SECRET_KEY = "random_ip/device_id"
_DEVICE_SETTINGS_KEY = "random_ip_auth/device_id"


def build_stable_device_id() -> str:
    settings = app_settings()
    value = str(settings.value(_DEVICE_SETTINGS_KEY) or "").strip()
    if value:
        return value

    # Migrate one existing identifier from the legacy DPAPI store, then keep
    # the runtime on the ordinary application settings path.
    legacy = read_secret(_DEVICE_SECRET_KEY)
    value = str(legacy.value or "").strip()
    if value:
        settings.setValue(_DEVICE_SETTINGS_KEY, value)
        settings.sync()
        return value

    device_id = f"{_DEVICE_ID_PREFIX}{uuid.uuid4().hex[:32]}"
    settings.setValue(_DEVICE_SETTINGS_KEY, device_id)
    settings.sync()
    return device_id
