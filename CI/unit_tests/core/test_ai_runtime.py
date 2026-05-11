from __future__ import annotations

import pytest

from software.core.ai import runtime as ai_runtime


class AiRuntimeTests:
    @pytest.mark.asyncio
    async def test_agenerate_ai_answer_retries_up_to_three_times_after_initial_try(self, monkeypatch) -> None:
        calls: list[int] = []

        async def _raise(*_args, **_kwargs):
            calls.append(1)
            raise RuntimeError("临时故障")

        async def _sleep(*_args, **_kwargs):
            return None

        monkeypatch.setattr(ai_runtime, "agenerate_answer", _raise)
        monkeypatch.setattr(ai_runtime.asyncio, "sleep", _sleep)

        try:
            await ai_runtime.agenerate_ai_answer("题目", question_type="fill_blank")
        except ai_runtime.AIRuntimeError as exc:
            assert "临时故障" in str(exc)

        assert len(calls) == 4
