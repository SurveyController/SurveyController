"""Provider hook 构建工具。"""

from __future__ import annotations

from functools import lru_cache
from importlib import import_module
from typing import Any, TypeAlias

from software.providers.contracts import SurveyDefinition, build_survey_definition

HookTarget: TypeAlias = tuple[str, str]


@lru_cache(maxsize=None)
def _load_hook(target: HookTarget) -> Any:
    module_path, attr_name = target
    module = import_module(module_path)
    return getattr(module, attr_name)


def build_parse_hook(provider: str, target: HookTarget):
    def _parse(url: str) -> SurveyDefinition:
        parser = _load_hook(target)
        info, title = parser(url)
        return build_survey_definition(provider, title, info)

    return _parse


def build_fill_hook(target: HookTarget):
    def _fill(
        driver: Any,
        config: Any,
        state: Any,
        *,
        stop_signal: Any = None,
        thread_name: str = "",
        psycho_plan: Any = None,
    ) -> bool:
        fill_impl = _load_hook(target)
        return bool(
            fill_impl(
                driver,
                config,
                state,
                stop_signal=stop_signal,
                thread_name=thread_name,
                psycho_plan=psycho_plan,
            )
        )

    return _fill


def build_predicate_hook(target: HookTarget):
    def _predicate(driver: Any) -> bool:
        return bool(_load_hook(target)(driver))

    return _predicate


def build_text_hook(target: HookTarget):
    def _text(driver: Any) -> str:
        return str(_load_hook(target)(driver) or "").strip()

    return _text


def build_wait_hook(target: HookTarget):
    def _wait(driver: Any, *, timeout: int = 3, stop_signal: Any = None) -> bool:
        return bool(
            _load_hook(target)(
                driver,
                timeout=timeout,
                stop_signal=stop_signal,
            )
        )

    return _wait


def build_wait_from_predicate_hook(target: HookTarget):
    def _wait(driver: Any, *, timeout: int = 3, stop_signal: Any = None) -> bool:
        del timeout, stop_signal
        return bool(_load_hook(target)(driver))

    return _wait


def build_action_hook(target: HookTarget):
    def _action(ctx: Any, gui_instance: Any, stop_signal: Any) -> None:
        _load_hook(target)(ctx, gui_instance, stop_signal)

    return _action

