from __future__ import annotations

from types import SimpleNamespace

from wjx.provider import runtime_dispatch


class _FakeQuestionDiv:
    def __init__(self, *, text: str = "", question_type: str = "3") -> None:
        self.text = text
        self.question_type = question_type

    def get_attribute(self, name: str):
        if name == "type":
            return self.question_type
        return None


def _ctx():
    return SimpleNamespace(
        config=SimpleNamespace(
            question_dimension_map={4: "D4"},
            single_prob=[],
            single_option_fill_texts=[],
            single_attached_option_selects=[],
            multiple_prob=[],
            multiple_option_fill_texts=[],
            scale_prob=[],
            matrix_prob=[],
            droplist_prob=[],
            droplist_option_fill_texts=[],
            slider_targets=[33],
            texts=[],
            texts_prob=[],
            text_entry_types=[],
            text_ai_flags=[],
            text_titles=[],
            multi_text_blank_modes=[],
            multi_text_blank_ai_flags=[],
            multi_text_blank_int_ranges=[],
        )
    )


class RuntimeDispatchTests:
    def test_question_title_for_log_prefers_ai_title_then_dom_text(self, monkeypatch) -> None:
        monkeypatch.setattr(runtime_dispatch, "extract_question_title_from_dom", lambda *_args, **_kwargs: "AI标题")
        assert runtime_dispatch._question_title_for_log(object(), 3, _FakeQuestionDiv(text="DOM 文本")) == "AI标题"

        monkeypatch.setattr(runtime_dispatch, "extract_question_title_from_dom", lambda *_args, **_kwargs: "")
        assert runtime_dispatch._question_title_for_log(object(), 3, _FakeQuestionDiv(text="  一段 很长 的 DOM 文本  ")) == "一段 很长 的 DOM 文本"
        assert runtime_dispatch._question_title_for_log(object(), 3, None) == ""

    def test_should_advance_reverse_fill_index_respects_mapping(self) -> None:
        reverse_fill_answer = object()
        assert runtime_dispatch._should_advance_reverse_fill_index(None, "text", (), None)
        assert not runtime_dispatch._should_advance_reverse_fill_index(None, "text", (), reverse_fill_answer)
        assert runtime_dispatch._should_advance_reverse_fill_index(("text", 1), "text", (), reverse_fill_answer)
        assert runtime_dispatch._should_advance_reverse_fill_index(("score", 1), "scale", ("score",), reverse_fill_answer)

    def test_dispatcher_routes_location_and_text_like_and_slider_matrix_paths(self, monkeypatch) -> None:
        dispatcher = runtime_dispatch._QuestionDispatcher()
        ctx = _ctx()
        indices = {"single": 0, "text": 2, "dropdown": 0, "multiple": 0, "matrix": 1, "scale": 0, "slider": 0}
        calls: list[tuple[str, int, int]] = []
        monkeypatch.setattr(runtime_dispatch, "resolve_current_reverse_fill_answer", lambda *_args, **_kwargs: None)
        monkeypatch.setattr(runtime_dispatch, "_driver_question_looks_like_reorder", lambda _div: False)
        monkeypatch.setattr(runtime_dispatch, "_driver_question_is_location", lambda _div: True)

        assert dispatcher.fill(object(), "1", 8, _FakeQuestionDiv(question_type="1"), None, indices, ctx) is False

        monkeypatch.setattr(runtime_dispatch, "_driver_question_is_location", lambda _div: False)
        monkeypatch.setattr(runtime_dispatch, "_count_choice_inputs_driver", lambda _div: (0, 0))
        monkeypatch.setattr(runtime_dispatch, "_count_visible_text_inputs_driver", lambda _div: 2)
        monkeypatch.setattr(runtime_dispatch, "_driver_question_looks_like_slider_matrix", lambda _div: False)
        monkeypatch.setattr(runtime_dispatch, "_should_treat_question_as_text_like", lambda *_args, **_kwargs: True)
        monkeypatch.setattr(runtime_dispatch, "_text_impl", lambda _driver, q_num, idx, *_args, **_kwargs: calls.append(("text", q_num, idx)))

        dispatcher.fill(object(), "3", 9, _FakeQuestionDiv(question_type="3"), ("text", 1), indices, ctx)
        assert calls[-1] == ("text", 9, 2)
        assert indices["text"] == 3

        monkeypatch.setattr(runtime_dispatch, "_driver_question_looks_like_slider_matrix", lambda _div: True)
        monkeypatch.setattr(runtime_dispatch, "_matrix_impl", lambda _driver, q_num, idx, *_args, **_kwargs: calls.append(("matrix", q_num, idx)) or 5)
        dispatcher.fill(object(), "9", 10, _FakeQuestionDiv(question_type="9"), ("matrix", 0), indices, ctx)
        assert calls[-1] == ("matrix", 10, 1)
        assert indices["matrix"] == 5

    def test_dispatcher_registry_and_index_rollback_protection(self, monkeypatch) -> None:
        dispatcher = runtime_dispatch._QuestionDispatcher()
        ctx = _ctx()
        indices = {"single": 3, "text": 0, "dropdown": 0, "multiple": 0, "matrix": 0, "scale": 2, "slider": 1}
        calls: list[tuple[str, int, int]] = []
        monkeypatch.setattr(runtime_dispatch, "resolve_current_reverse_fill_answer", lambda *_args, **_kwargs: None)
        monkeypatch.setattr(runtime_dispatch, "_driver_question_looks_like_reorder", lambda _div: False)
        monkeypatch.setattr(runtime_dispatch, "_driver_question_looks_like_slider_matrix", lambda _div: False)

        dispatcher.register("42", index_key="single", handler=lambda _driver, q_num, idx, _ctx: calls.append(("custom", q_num, idx)))
        dispatcher.fill(object(), "42", 4, _FakeQuestionDiv(question_type="42"), ("single", 1), indices, ctx)
        assert calls == [("custom", 4, 3)]
        assert indices["single"] == 4

        monkeypatch.setattr(runtime_dispatch, "_slider_impl", lambda _driver, q_num, score: calls.append(("slider", q_num, score)))
        monkeypatch.setattr(runtime_dispatch, "_resolve_slider_score", lambda idx, targets: 99)
        dispatcher.fill(object(), "8", 6, _FakeQuestionDiv(question_type="8"), ("slider", 0), indices, ctx)
        assert calls[-1] == ("slider", 6, 99)
        assert indices["slider"] == 2

        assert dispatcher.fill(object(), "404", 12, _FakeQuestionDiv(question_type="404"), None, indices, ctx) is False
