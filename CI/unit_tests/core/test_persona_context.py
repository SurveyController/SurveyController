from __future__ import annotations

from software.core.persona import context


class _Persona:
    def __init__(self, keyword_map: dict[str, list[str]] | None = None, description: str = "测试画像") -> None:
        self.keyword_map = keyword_map or {}
        self.description = description

    def to_keyword_map(self) -> dict[str, list[str]]:
        return self.keyword_map

    def to_description(self) -> str:
        return self.description


class PersonaContextTests:
    def test_record_answer_tracks_normal_and_matrix_answers(self) -> None:
        context.reset_context()
        context.record_answer(1, "single", selected_indices=[0], selected_texts=["喜欢"])
        context.record_answer(2, "matrix", selected_indices=[1], row_index=3)

        answered = context.get_answered()

        assert answered[1].selected_indices == [0]
        assert answered[1].selected_texts == ["喜欢"]
        assert answered[2].row_answers == {3: [1]}

    def test_apply_persona_boost_returns_copy_when_no_persona_or_keywords(self, patch_attrs) -> None:
        patch_attrs((context, "get_current_persona", lambda: None))
        weights = [1.0, 2.0]

        result = context.apply_persona_boost(["北京", "上海"], weights)

        assert result == weights
        assert result is not weights

        patch_attrs((context, "get_current_persona", lambda: _Persona({})))
        assert context.apply_persona_boost(["北京"], [1.0]) == [1.0]

    def test_apply_persona_boost_multiplies_each_matching_option_once(self, patch_attrs) -> None:
        patch_attrs((context, "get_current_persona", lambda: _Persona({"city": ["北京", "上海"]})))

        result = context.apply_persona_boost(["北京上海都可以", "广州", ""], [1.0, 2.0, 3.0])

        assert result == [3.0, 2.0, 3.0]

    def test_build_ai_context_prompt_includes_persona_and_recent_answers(self, patch_attrs) -> None:
        context.reset_context()
        patch_attrs((context, "get_current_persona", lambda: _Persona(description="25岁，北京用户")))
        for idx in range(1, 13):
            context.record_answer(idx, "single", selected_texts=[f"选项{idx}"])
        context.record_answer(13, "text", text_answer="这是一段很长的填空内容" * 5)

        prompt = context.build_ai_context_prompt()

        assert "你扮演的角色是：25岁，北京用户。" in prompt
        assert "第3题" not in prompt
        assert "第12题: 选了「选项12」" in prompt
        assert "第13题(填空):" in prompt
        assert "请保持与前面回答的一致性。" in prompt

    def test_build_ai_context_prompt_returns_empty_when_no_context(self, patch_attrs) -> None:
        context.reset_context()
        patch_attrs((context, "get_current_persona", lambda: None))

        assert context.build_ai_context_prompt() == ""
