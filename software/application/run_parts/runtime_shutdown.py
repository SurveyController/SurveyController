from __future__ import annotations

import logging
import time
import threading
from typing import Any, Iterable, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from software.application.run_service import RunApplicationService


def collect_unique_threads(candidates: Iterable[Any]) -> List[threading.Thread]:
    seen: set[int] = set()
    threads: List[threading.Thread] = []
    for candidate in candidates:
        if not isinstance(candidate, threading.Thread):
            continue
        identifier = id(candidate)
        if identifier in seen:
            continue
        seen.add(identifier)
        threads.append(candidate)
    return threads


class RuntimeShutdownHelper:
    

    def __init__(self, controller: Any) -> None:
        self.controller = controller

    def collect_threads(self) -> List[threading.Thread]:
        controller = self.controller
        engine_thread = getattr(getattr(controller, "_async_engine_client", None), "thread", None)
        collect_random_ip_threads = getattr(
            controller,
            "collect_random_ip_background_threads",
            lambda: [],
        )
        return collect_unique_threads(
            [
                getattr(controller, "_init_gate_thread", None),
                *[
                    thread
                    for thread in list(getattr(controller, "worker_threads", []) or [])
                    if thread is not engine_thread
                ],
                getattr(controller, "_monitor_thread", None),
                getattr(controller, "_status_snapshot_monitor_thread", None),
                *list(collect_random_ip_threads() or []),
            ]
        )


def clear_finished_thread(value: Optional[threading.Thread]) -> Optional[threading.Thread]:
    if value is not None and not value.is_alive():
        return None
    return value





def request_shutdown_for_close(service: RunApplicationService, timeout_seconds: float = 5.0) -> None:
    service._closing = True
    service._interactions.cancel_pending()
    with service._close_shutdown_lock:
        active = service._close_shutdown_thread
        if isinstance(active, threading.Thread) and active.is_alive():
            return

        def _worker() -> None:
            try:
                service.shutdown_for_close(timeout_seconds=timeout_seconds)
            except Exception:
                logging.warning("异步关闭收尾失败", exc_info=True)
            finally:
                service._close_shutdown_complete.set()
                with service._close_shutdown_lock:
                    if service._close_shutdown_thread is threading.current_thread():
                        service._close_shutdown_thread = None

        thread = threading.Thread(
            target=_worker,
            daemon=True,
            name="CloseShutdownWorker",
        )
        service._close_shutdown_thread = thread
        service._close_shutdown_complete.clear()
        thread.start()


def wait_for_shutdown(service: RunApplicationService, timeout_seconds: float = 5.0) -> bool:
    thread = service._close_shutdown_thread
    if thread is None:
        return service._close_shutdown_complete.is_set()
    if thread is threading.current_thread():
        return False
    thread.join(timeout=max(0.0, float(timeout_seconds or 0.0)))
    return not thread.is_alive() and service._close_shutdown_complete.is_set()


def collect_shutdown_threads(service: RunApplicationService) -> List[threading.Thread]:
    return RuntimeShutdownHelper(service).collect_threads()


def shutdown_for_close(service: RunApplicationService, timeout_seconds: float = 5.0) -> bool:
    deadline = time.monotonic() + max(0.0, float(timeout_seconds or 0.0))
    service._closing = True
    service._interactions.cancel_pending()
    service._cleanup_scheduled = True
    service.stop_run()

    try:
        service.runtime_port.cleanup_targets()
    except Exception:
        logging.warning("关闭窗口时执行运行时兜底清理失败", exc_info=True)

    current = threading.current_thread()
    pending = [thread for thread in collect_shutdown_threads(service) if thread is not current]

    try:
        remaining = max(0.0, deadline - time.monotonic())
        service._async_engine_client.shutdown(timeout=remaining)
    except Exception:
        logging.warning("关闭窗口时停止 async-first 内核失败", exc_info=True)

    while True:
        alive = [thread for thread in pending if thread.is_alive()]
        if not alive:
            break
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        slice_timeout = min(0.1, remaining)
        for thread in alive:
            thread.join(timeout=slice_timeout)

    service.worker_threads = [thread for thread in service.worker_threads if thread.is_alive()]
    service._monitor_thread = clear_finished_thread(service._monitor_thread)
    service._init_gate_thread = clear_finished_thread(service._init_gate_thread)
    alive = [thread for thread in pending if thread.is_alive()]
    if alive:
        logging.warning(
            "关闭窗口时仍有后台线程未退出：%s",
            ", ".join(thread.name or "UnnamedThread" for thread in alive),
        )
    return not alive

