"""Go 代理 sidecar 生命周期管理。"""
from __future__ import annotations

import atexit
import logging
import os
import socket
import subprocess
import threading
import time
from pathlib import Path
from typing import Optional

from software.app.runtime_paths import get_bundle_resource_root, get_runtime_directory
from software.network.proxy.policy import get_proxy_settings
from software.network.proxy.sidecar_client import ProxySidecarClient, ProxySidecarError

_LOCK = threading.RLock()
_PROCESS: Optional[subprocess.Popen] = None
_CLIENT: Optional[ProxySidecarClient] = None
_PORT: int = 0
_BASE_URL = "http://127.0.0.1:9010"
_START_RETRIES = 2
_STARTUP_TIMEOUT_SECONDS = 8.0
_DEFAULT_PORT_START = 19010
_DEFAULT_PORT_END = 19050


def _candidate_binary_paths() -> list[Path]:
    runtime_dir = Path(get_runtime_directory())
    bundle_root = Path(get_bundle_resource_root())
    return [
        runtime_dir / "proxy_service.exe",
        runtime_dir / "lib" / "proxy_service.exe",
        bundle_root / "proxy_service.exe",
        bundle_root / "lib" / "proxy_service.exe",
        Path(__file__).resolve().parents[2] / "proxy_service.exe",
        Path(__file__).resolve().parents[2] / "proxy_service" / "proxy_service.exe",
    ]


def resolve_sidecar_binary_path() -> Path:
    for candidate in _candidate_binary_paths():
        if candidate.is_file():
            return candidate
    raise ProxySidecarError("未找到 proxy_service.exe，请先编译 Go 代理服务")


def _pick_free_port() -> int:
    for port in range(_DEFAULT_PORT_START, _DEFAULT_PORT_END + 1):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind(("127.0.0.1", port))
            except OSError:
                continue
            return int(port)
    raise ProxySidecarError("无法分配本地代理服务端口")


def _create_startupinfo() -> Optional[subprocess.STARTUPINFO]:
    try:
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = 0
        return startupinfo
    except Exception:
        return None


def _is_process_alive(process: Optional[subprocess.Popen]) -> bool:
    return bool(process is not None and process.poll() is None)


def _build_client(port: int) -> ProxySidecarClient:
    return ProxySidecarClient(f"http://127.0.0.1:{int(port)}")


def _apply_runtime_config(client: ProxySidecarClient) -> None:
    client.apply_config(get_proxy_settings())


def _wait_until_ready(client: ProxySidecarClient, timeout_seconds: float) -> None:
    deadline = time.monotonic() + max(1.0, float(timeout_seconds or 1.0))
    last_error: Optional[BaseException] = None
    while time.monotonic() < deadline:
        try:
            client.status()
            return
        except Exception as exc:
            last_error = exc
            time.sleep(0.2)
    raise ProxySidecarError(f"代理服务启动超时：{last_error or 'unknown'}")


def ensure_proxy_sidecar_running(*, force_restart: bool = False) -> ProxySidecarClient:
    global _PROCESS, _CLIENT, _PORT
    with _LOCK:
        if force_restart:
            _stop_locked()
        if _CLIENT is not None and _is_process_alive(_PROCESS):
            try:
                _CLIENT.status()
                _apply_runtime_config(_CLIENT)
                return _CLIENT
            except Exception:
                _stop_locked()

        binary_path = resolve_sidecar_binary_path()
        last_error: Optional[BaseException] = None
        for _ in range(_START_RETRIES + 1):
            port = _pick_free_port()
            env = os.environ.copy()
            env["SURVEY_PROXY_PORT"] = str(port)
            env["SURVEY_PROXY_BASE_URL"] = "http://127.0.0.1:9010"
            creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            try:
                process = subprocess.Popen(
                    [str(binary_path)],
                    cwd=str(binary_path.parent),
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    startupinfo=_create_startupinfo(),
                    creationflags=creation_flags,
                    env=env,
                )
            except Exception as exc:
                last_error = exc
                continue
            client = _build_client(port)
            try:
                _wait_until_ready(client, _STARTUP_TIMEOUT_SECONDS)
                _apply_runtime_config(client)
            except Exception as exc:
                last_error = exc
                try:
                    process.terminate()
                    process.wait(timeout=2)
                except Exception:
                    pass
                continue
            _PROCESS = process
            _CLIENT = client
            _PORT = int(port)
            return client

        raise ProxySidecarError(f"代理服务启动失败：{last_error or 'unknown'}")


def get_proxy_sidecar_client() -> ProxySidecarClient:
    return ensure_proxy_sidecar_running(force_restart=False)


def restart_proxy_sidecar() -> ProxySidecarClient:
    return ensure_proxy_sidecar_running(force_restart=True)


def _stop_locked() -> None:
    global _PROCESS, _CLIENT, _PORT
    process = _PROCESS
    _PROCESS = None
    _CLIENT = None
    _PORT = 0
    if process is None:
        return
    try:
        process.terminate()
    except Exception:
        pass
    try:
        process.wait(timeout=3)
    except Exception:
        try:
            process.kill()
        except Exception:
            pass


def stop_proxy_sidecar() -> None:
    with _LOCK:
        _stop_locked()


def sync_proxy_sidecar_config() -> None:
    with _LOCK:
        client = ensure_proxy_sidecar_running(force_restart=False)
        client.apply_config(get_proxy_settings())


atexit.register(stop_proxy_sidecar)


__all__ = [
    "ProxySidecarError",
    "ensure_proxy_sidecar_running",
    "get_proxy_sidecar_client",
    "restart_proxy_sidecar",
    "resolve_sidecar_binary_path",
    "sync_proxy_sidecar_config",
    "stop_proxy_sidecar",
]
