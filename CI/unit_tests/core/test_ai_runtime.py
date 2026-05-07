from __future__ import annotations

from software.core.ai import runtime as ai_runtime


class AiRuntimeTests:
    def test_generate_ai_answer_retries_up_to_three_times_after_initial_try(self, monkeypatch) -> None:
        calls: list[int] = []

        def _raise(*_args, **_kwargs):
            calls.append(1)
            raise RuntimeError("临时故障")

        monkeypatch.setattr(ai_runtime, "generate_answer", _raise)
        monkeypatch.setattr(ai_runtime.time, "sleep", lambda *_args, **_kwargs: None)

        try:
            ai_runtime.generate_ai_answer("题目", question_type="fill_blank")
        except ai_runtime.AIRuntimeError as exc:
            assert "临时故障" in str(exc)

        assert len(calls) == 4
