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

    def test_generate_ai_answer_limits_timeout_retries(self, monkeypatch) -> None:
        calls: list[int] = []

        def _raise_timeout(*_args, **_kwargs):
            calls.append(1)
            raise RuntimeError("The read operation timed out")

        monkeypatch.setattr(ai_runtime, "generate_answer", _raise_timeout)
        monkeypatch.setattr(ai_runtime.time, "sleep", lambda *_args, **_kwargs: None)

        try:
            ai_runtime.generate_ai_answer("题目", question_type="fill_blank")
        except ai_runtime.AIRuntimeError as exc:
            assert "timed out" in str(exc)

        assert len(calls) == 2

    def test_generate_ai_answer_includes_min_word_requirement_in_prompt(self, monkeypatch) -> None:
        prompts: list[str] = []

        def _answer(prompt: str, **_kwargs):
            prompts.append(prompt)
            return "这是一个满足要求的回答内容"

        monkeypatch.setattr(ai_runtime, "generate_answer", _answer)

        result = ai_runtime.generate_ai_answer("请简述个人发展目标", question_type="fill_blank", min_words=30)

        assert result == "这是一个满足要求的回答内容"
        assert prompts
        assert "至少30字" in prompts[0]
        assert "只输出最终答案" in prompts[0]
