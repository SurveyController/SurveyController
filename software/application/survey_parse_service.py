from __future__ import annotations

import concurrent.futures
import logging
from typing import Any, Callable

from software.application.events import ApplicationEvent
from software.application.ports import RuntimeEnginePort
from software.application.run_state_store import RunStateStore
from software.core.config.schema import RuntimeConfig
from software.providers.common import is_supported_survey_url
from software.providers.contracts import ProviderFailure, ProviderParseResult
from surveycore.core.questions.config import build_default_question_entries
from surveycore.providers.contracts import SurveyDefinition
from surveycore.providers.errors import (
    SurveyEnterpriseUnavailableError,
    SurveyNotOpenError,
    SurveyPausedError,
    SurveyStoppedError,
)


class SurveyParseService:
    def __init__(
        self,
        *,
        async_engine_client: RuntimeEnginePort,
        state_store: RunStateStore,
        emit_event: Callable[[ApplicationEvent], Any],
        dispatch_async: Callable[[Callable[[], Any]], None],
    ) -> None:
        self._async_engine_client = async_engine_client
        self._state_store = state_store
        self._emit_event = emit_event
        self._dispatch_async = dispatch_async
        self._generation = 0
        self._closed = False
        self._parse_future: concurrent.futures.Future[ProviderParseResult] | None = None

    def close(self) -> None:
        self._closed = True
        self._generation += 1
        if self._parse_future is not None:
            self._parse_future.cancel()

    def parse_survey(self, url: str) -> None:
        if self._closed:
            return
        self._generation += 1
        generation = self._generation
        normalized_url = str(url or "").strip()
        if not normalized_url:
            self._state_store.apply_survey_patch(
                {
                    "phase": "error",
                    "url": "",
                    "parse_error": "",
                    "error_code": "url_required",
                }
            )
            return
        if not is_supported_survey_url(normalized_url):
            logging.warning("收到不支持的问卷链接：%r", normalized_url)
            self._state_store.apply_survey_patch(
                {
                    "phase": "error",
                    "url": normalized_url,
                    "parse_error": "",
                    "error_code": "url_unsupported",
                }
            )
            return

        current_entries = self._state_store.get_survey_snapshot().get("question_entries") or []
        self._state_store.apply_survey_patch(
            {
                "phase": "parsing",
                "url": normalized_url,
                "survey_title": "",
                "questions_info": [],
                "question_entries": [],
                "parse_error": "",
                "error_code": "",
            }
        )

        def _apply_parse_success(definition: SurveyDefinition) -> None:
            if self._closed or generation != self._generation:
                return
            info = [q for q in definition.questions if not q.is_description]
            title = definition.title
            provider = definition.provider
            entries = build_default_question_entries(
                info,
                survey_url=normalized_url,
                existing_entries=current_entries,
            )
            self._state_store.apply_survey_patch(
                {
                    "phase": "ready",
                    "url": normalized_url,
                    "survey_provider": provider,
                    "survey_title": title or "",
                    "questions_info": list(info or []),
                    "question_entries": list(entries or []),
                    "parse_error": "",
                    "error_code": "",
                }
            )
            self._state_store.update_runtime_settings(
                emit=True,
                survey_provider=provider,
            )

        def _apply_parse_failure(message: str) -> None:
            if self._closed or generation != self._generation:
                return
            self._state_store.apply_survey_patch(
                {
                    "phase": "error",
                    "url": normalized_url,
                    "survey_title": "",
                    "questions_info": [],
                    "question_entries": [],
                    "parse_error": str(message or ""),
                    "error_code": "parse_failed",
                }
            )

        def _on_done(done_future: concurrent.futures.Future[ProviderParseResult]) -> None:
            if self._closed or generation != self._generation:
                return
            callback: Callable[[], None]
            try:
                result = done_future.result()
                if result.failure is not None:
                    _record_provider_failure(result.failure)
                    raise result.failure.exception
                if result.definition is None:
                    raise RuntimeError("Provider 返回了空的解析结果")
                definition = result.definition
            except (
                SurveyPausedError,
                SurveyStoppedError,
                SurveyEnterpriseUnavailableError,
                SurveyNotOpenError,
            ) as exc:
                logging.info("解析问卷被业务状态拦截，url=%r：%s", normalized_url, exc)
                callback = lambda message=str(exc): _apply_parse_failure(message)
            except Exception as exc:
                logging.exception("解析问卷流程失败，url=%r", normalized_url)
                callback = lambda message=str(exc): _apply_parse_failure(message)
            else:

                def apply_success() -> None:
                    try:
                        _apply_parse_success(definition)
                    except Exception as exc:
                        logging.exception("构建问卷编辑草稿失败")
                        _apply_parse_failure(str(exc))

                callback = apply_success
            try:
                self._dispatch_async(callback)
            except Exception:
                logging.warning("派发问卷解析结果失败", exc_info=True)
                if not self._closed and generation == self._generation:
                    self._state_store.apply_survey_patch(
                        {
                            "phase": "error",
                            "error_code": "dispatch_failed",
                            "parse_error": "",
                        },
                        emit=False,
                    )

        try:
            future = self._async_engine_client.parse_survey(normalized_url)
        except Exception as exc:
            _apply_parse_failure(str(exc))
            return
        self._parse_future = future
        future.add_done_callback(_on_done)

    def hydrate_from_config(self, cfg: RuntimeConfig) -> None:
        self._state_store.hydrate_from_config(cfg)

    def replace_question_entries(self, entries: Any, *, questions_info: Any = None) -> None:
        self._state_store.replace_question_entries(entries, questions_info=questions_info)


def _record_provider_failure(failure: ProviderFailure) -> None:
    category = failure.category.value
    logging.error(
        "Provider[%s] 解析失败 category=%s: %s",
        failure.provider,
        category,
        failure.message,
    )
    add_note = getattr(failure.exception, "add_note", None)
    if callable(add_note):
        add_note(f"provider={failure.provider}; category={category}")


__all__ = ["SurveyParseService"]
