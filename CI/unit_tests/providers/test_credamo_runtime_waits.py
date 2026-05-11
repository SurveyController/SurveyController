from __future__ import annotations

import pytest

from credamo.provider import runtime


def _async_return(value):
    async def _runner(*_args, **_kwargs):
        return value

    return _runner


class CredamoRuntimeWaitTests:
    @pytest.mark.asyncio
    async def test_wait_for_question_roots_extends_when_page_is_loading_shell(self, patch_attrs) -> None:
        patch_attrs(
            (runtime, "_question_roots", _async_return([])),
            (runtime, "_page_loading_snapshot", _async_return(("答卷", "载入中..."))),
        )
        roots_iter = iter([[], ["root"]])

        async def _roots(*_args, **_kwargs):
            return next(roots_iter)

        patch_attrs((runtime, "_question_roots", _roots))
        roots = await runtime._wait_for_question_roots(object(), None, timeout_ms=10, loading_shell_extra_timeout_ms=10)
        assert roots == ["root"]

    @pytest.mark.asyncio
    async def test_wait_for_question_roots_returns_empty_after_extended_timeout(self, patch_attrs) -> None:
        patch_attrs(
            (runtime, "_question_roots", _async_return([])),
            (runtime, "_page_loading_snapshot", _async_return(("答卷", "载入中..."))),
        )
        roots = await runtime._wait_for_question_roots(object(), None, timeout_ms=10, loading_shell_extra_timeout_ms=10)
        assert roots == []
