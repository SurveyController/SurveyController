from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from typing import Any

from software.core.config.schema import RuntimeConfig
from software.core.engine.execution_artifacts import (
    PreparedExecutionArtifacts,
    RuntimePreparationError,
)


class PreparationJob:
    """Run blocking execution preparation off the caller thread."""

    def __init__(
        self,
        *,
        preparer: Callable[..., PreparedExecutionArtifacts],
        config: RuntimeConfig,
        fallback_survey_title: str,
        stop_signal: threading.Event,
        dispatch: Callable[[Callable[[], Any]], None],
        on_prepared: Callable[[PreparedExecutionArtifacts], None],
        on_failed: Callable[[str], None],
        on_dispatch_failed: Callable[[], None],
    ) -> None:
        self._preparer = preparer
        self._config = config
        self._fallback_survey_title = fallback_survey_title
        self._stop_signal = stop_signal
        self._dispatch = dispatch
        self._on_prepared = on_prepared
        self._on_failed = on_failed
        self._on_dispatch_failed = on_dispatch_failed
        self.thread = threading.Thread(
            target=self._run,
            daemon=True,
            name="RuntimePreparation",
        )

    def start(self) -> threading.Thread:
        self.thread.start()
        return self.thread

    def cancel(self) -> None:
        self._stop_signal.set()

    def _run(self) -> None:
        try:
            prepared = self._preparer(
                self._config,
                fallback_survey_title=self._fallback_survey_title,
                stop_signal=self._stop_signal,
            )
        except Exception as exc:
            if isinstance(exc, RuntimePreparationError):
                logging.error(exc.log_message, exc_info=exc.detailed)
                detail = exc.user_message
            else:
                logging.exception("运行准备失败")
                detail = str(exc)
            callback = lambda detail=detail: self._on_failed(detail)
        else:
            callback = lambda: self._on_prepared(prepared)

        try:
            self._dispatch(callback)
        except Exception:
            self._stop_signal.set()
            self._on_dispatch_failed()
            logging.warning("派发运行准备结果失败", exc_info=True)


__all__ = ["PreparationJob"]
