"""Windows device fingerprint helpers."""
from __future__ import annotations

import getpass
import hashlib
import logging
import os
import subprocess
import sys
import uuid
from typing import Iterable

if sys.platform == "win32":
    import winreg
else:  # pragma: no cover
    winreg = None

_DEVICE_ID_PREFIX = "sc-v2-"
_FINGERPRINT_SALT = "SurveyController.random_ip.device.v2"
_MACHINE_GUID_REGISTRY_PATH = r"SOFTWARE\Microsoft\Cryptography"
_MACHINE_GUID_VALUE_NAME = "MachineGuid"


def _normalize_component(value: object) -> str:
    return str(value or "").strip().lower()


def _read_machine_guid() -> str:
    if winreg is None:
        return ""
    for access in _registry_access_variants():
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, _MACHINE_GUID_REGISTRY_PATH, 0, access) as key:
                value, _ = winreg.QueryValueEx(key, _MACHINE_GUID_VALUE_NAME)
                return str(value or "").strip()
        except FileNotFoundError:
            return ""
        except OSError:
            continue
        except Exception as exc:
            logging.info("读取 MachineGuid 失败：%s", exc)
            return ""
    return ""


def _registry_access_variants() -> Iterable[int]:
    if winreg is None:
        return ()
    variants = [winreg.KEY_READ]
    if hasattr(winreg, "KEY_WOW64_64KEY"):
        variants.append(winreg.KEY_READ | winreg.KEY_WOW64_64KEY)
    if hasattr(winreg, "KEY_WOW64_32KEY"):
        variants.append(winreg.KEY_READ | winreg.KEY_WOW64_32KEY)
    return tuple(variants)


def _read_user_sid() -> str:
    if sys.platform != "win32":
        return ""
    try:
        completed = subprocess.run(
            ["whoami", "/user", "/fo", "csv", "/nh"],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except Exception as exc:
        logging.info("读取 Windows 用户 SID 失败：%s", exc)
        return ""
    if completed.returncode != 0:
        return ""
    text = str(completed.stdout or "").strip()
    if not text:
        return ""
    parts = [part.strip().strip('"') for part in text.split(",")]
    for part in parts:
        if part.startswith("S-1-"):
            return part
    return ""


def _fallback_user_component() -> str:
    return _normalize_component(os.environ.get("USERDOMAIN")) + "\\" + _normalize_component(getpass.getuser())


def build_stable_device_id() -> str:
    """Build a stable local device id for first-time random IP identity creation."""
    machine_guid = _normalize_component(_read_machine_guid())
    user_sid = _normalize_component(_read_user_sid()) or _fallback_user_component()
    components = [component for component in (_FINGERPRINT_SALT, machine_guid, user_sid) if component]
    if machine_guid and user_sid:
        digest = hashlib.sha256("|".join(components).encode("utf-8")).hexdigest()
        return f"{_DEVICE_ID_PREFIX}{digest[:32]}"
    logging.warning("设备指纹信息不足，退回随机设备号：machine_guid=%s user_sid=%s", bool(machine_guid), bool(user_sid))
    return uuid.uuid4().hex

