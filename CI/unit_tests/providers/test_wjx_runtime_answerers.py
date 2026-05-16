from __future__ import annotations

from types import SimpleNamespace

import pytest

from wjx.provider import runtime_answerers
from software.core.questions.schema import _TEXT_RANDOM_MOBILE


def _question(num: int, **overrides):
    payload = {
        "num": num,
        "option_texts": ["A", "B", "C"],
        "options": 3,
        "rows": 2,
        "title": f"Q{num}",
        "description": "",
        "multi_min_limit": 1,
        "multi_max_limit": 3,
        "text_inputs": 1,
        "forced_option_index": None,
    }
    payload.update(overrides)
    return SimpleNamespace(**payload)


def _ctx(**config_overrides):
    config = {
        "single_prob": [[30, 70, 0]],
        "single_option_fill_texts": [["填空A", "填空B"]],
        "droplist_prob": [[20, 80, 0]],
        "droplist_option_fill_texts": [["下拉A", "下拉B"]],
        "texts": [["配置文本"]],
        "texts_prob": [[1.0]],
        "text_ai_flags": [False],
        "scale_prob": [[0, 100, 0]],
        "matrix_prob": [[60, 40, 0], [0, 100, 0]],
        "multiple_prob": [[-1]],
        "multiple_option_fill_texts": [["多选补充"]],
        "slider_targets": [66],
        "question_dimension_map": {},
        "question_config_index_map": {},
    }
    config.update(config_overrides)
    return SimpleNamespace(config=SimpleNamespace(**config))


class WjxRuntimeAnswerersTests:
    @pytest.mark.asyncio
    async def test_answer_wjx_single_covers_normal_and_strict_ratio_paths(self, monkeypatch) -> None:
        ctx = _ctx()
        question = _question(3, option_texts=["甲", "乙", "丙"])
        recorded: list[tuple[tuple[object, ...], dict[str, object]]] = []
        pending: list[tuple[object, ...]] = []
        fills: list[tuple[object, ...]] = []
        monkeypatch.setattr(runtime_answerers, "normalize_droplist_probs", lambda weights, count: [0.2, 0.8, 0.0][:count])
        monkeypatch.setattr(runtime_answerers, "apply_persona_boost", lambda texts, probs: [0.1, 0.9, 0.0])
        monkeypatch.setattr(runtime_answerers, "apply_single_like_consistency", lambda probs, _current: probs)
        monkeypatch.setattr(runtime_answerers, "is_strict_ratio_question", lambda _ctx, _current: False)
        monkeypatch.setattr(runtime_answerers, "weighted_index", lambda _probs: 1)

        async def _click_choice_input(*_args, **_kwargs):
            return True

        async def _resolve_fill(*_args, **_kwargs):
            return "补充"

        async def _fill_choice_option_additional_text(*_args, **_kwargs):
            fills.append(_args)
            return True

        monkeypatch.setattr(runtime_answerers, "_click_choice_input", _click_choice_input)
        monkeypatch.setattr(runtime_answerers, "resolve_runtime_option_fill_text_from_config", _resolve_fill)
        monkeypatch.setattr(runtime_answerers, "_fill_choice_option_additional_text", _fill_choice_option_additional_text)
        monkeypatch.setattr(runtime_answerers, "record_answer", lambda *args, **kwargs: recorded.append((args, kwargs)))
        monkeypatch.setattr(runtime_answerers, "record_pending_distribution_choice", lambda *args: pending.append(args))

        await runtime_answerers._answer_wjx_single(object(), question, 0, ctx)

        assert fills
        assert pending == []
        assert recorded == [((3, "single"), {"selected_indices": [1], "selected_texts": ["乙 / 补充"]})]

        recorded.clear()
        pending.clear()
        monkeypatch.setattr(runtime_answerers, "is_strict_ratio_question", lambda _ctx, _current: True)
        monkeypatch.setattr(runtime_answerers, "resolve_distribution_probabilities", lambda probs, *_args, **_kwargs: [0.3, 0.7, 0.0])
        monkeypatch.setattr(runtime_answerers, "enforce_reference_rank_order", lambda probs, _reference: probs)
        await runtime_answerers._answer_wjx_single(object(), question, 0, ctx)
        assert pending == [(ctx, 3, 1, 3)]
        assert recorded[-1][1]["selected_indices"] == [1]

    @pytest.mark.asyncio
    async def test_answer_wjx_dropdown_covers_dimension_and_click_fail_paths(self, monkeypatch, caplog) -> None:
        ctx = _ctx(question_dimension_map={7: "D1"})
        question = _question(7, option_texts=["一", "二", "三"])
        pending: list[tuple[object, ...]] = []
        recorded: list[tuple[tuple[object, ...], dict[str, object]]] = []
        monkeypatch.setattr(runtime_answerers, "normalize_droplist_probs", lambda weights, count: [0.2, 0.8, 0.0][:count])
        monkeypatch.setattr(runtime_answerers, "is_strict_ratio_question", lambda _ctx, _current: False)
        monkeypatch.setattr(runtime_answerers, "apply_persona_boost", lambda texts, probs: probs)
        monkeypatch.setattr(runtime_answerers, "resolve_distribution_probabilities", lambda probs, *_args, **_kwargs: [0.1, 0.9, 0.0])
        monkeypatch.setattr(runtime_answerers, "get_tendency_index", lambda *_args, **_kwargs: 1)

        async def _set_select_value(*_args, **_kwargs):
            return True

        async def _resolve_fill(*_args, **_kwargs):
            return None

        monkeypatch.setattr(runtime_answerers, "_set_select_value", _set_select_value)
        monkeypatch.setattr(runtime_answerers, "resolve_runtime_option_fill_text_from_config", _resolve_fill)
        monkeypatch.setattr(runtime_answerers, "record_pending_distribution_choice", lambda *args: pending.append(args))
        monkeypatch.setattr(runtime_answerers, "record_answer", lambda *args, **kwargs: recorded.append((args, kwargs)))

        await runtime_answerers._answer_wjx_dropdown(object(), question, 0, ctx, psycho_plan="plan")

        assert pending == [(ctx, 7, 1, 3)]
        assert recorded == [((7, "dropdown"), {"selected_indices": [1], "selected_texts": ["二"]})]

        async def _select_fail(*_args, **_kwargs):
            return False

        monkeypatch.setattr(runtime_answerers, "_set_select_value", _select_fail)
        with caplog.at_level("WARNING"):
            result = await runtime_answerers._answer_wjx_dropdown(object(), question, 0, ctx, psycho_plan=None)
        assert result is False
        assert "无法选中选项" in caplog.text

    @pytest.mark.asyncio
    async def test_answer_wjx_text_covers_config_ai_and_failure_paths(self, monkeypatch) -> None:
        ctx = _ctx(texts=[["静态配置", "__TOKEN__"]], texts_prob=[[1.0]], text_ai_flags=[False])
        question = _question(9, title="标题", description="说明")
        recorded: list[tuple[tuple[object, ...], dict[str, object]]] = []
        monkeypatch.setattr(runtime_answerers, "normalize_probabilities", lambda probs: [1.0] * len(probs))
        monkeypatch.setattr(runtime_answerers, "resolve_dynamic_text_token", lambda value: "动态值" if value == "__TOKEN__" else value)
        monkeypatch.setattr(runtime_answerers, "weighted_index", lambda _probs: 0)

        async def _fill_text(*_args, **_kwargs):
            return True

        monkeypatch.setattr(runtime_answerers, "_fill_text_input", _fill_text)
        monkeypatch.setattr(runtime_answerers, "record_answer", lambda *args, **kwargs: recorded.append((args, kwargs)))

        await runtime_answerers._answer_wjx_text(object(), question, 0, ctx)
        assert recorded == [((9, "text"), {"text_answer": "静态配置"})]

        recorded.clear()
        ctx_ai = _ctx(texts=[["配置"]], texts_prob=[[1.0]], text_ai_flags=[True])

        async def _ai_answer(*_args, **_kwargs):
            return ["AI答案"]

        monkeypatch.setattr(runtime_answerers, "agenerate_ai_answer", _ai_answer)
        await runtime_answerers._answer_wjx_text(object(), question, 0, ctx_ai)
        assert recorded == [((9, "text"), {"text_answer": "AI答案"})]

        async def _ai_fail(*_args, **_kwargs):
            raise runtime_answerers.AIRuntimeError("boom")

        monkeypatch.setattr(runtime_answerers, "agenerate_ai_answer", _ai_fail)
        with pytest.raises(runtime_answerers.AIRuntimeError, match="问卷星第9题 AI 生成失败"):
            await runtime_answerers._answer_wjx_text(object(), question, 0, ctx_ai)

    @pytest.mark.asyncio
    async def test_answer_wjx_text_applies_multi_text_blank_modes(self, monkeypatch) -> None:
        ctx = _ctx(
            texts=[["默认文本"]],
            texts_prob=[[1.0]],
            text_ai_flags=[False],
            text_entry_types=["multi_text"],
            multi_text_blank_modes=[["none", _TEXT_RANDOM_MOBILE, "none"]],
            multi_text_blank_int_ranges=[[]],
        )
        question = _question(9, text_inputs=3)
        fill_calls: list[tuple[object, ...]] = []

        monkeypatch.setattr(runtime_answerers, "weighted_index", lambda _probs: 0)
        monkeypatch.setattr(runtime_answerers, "resolve_dynamic_text_token", lambda value: "13900001111" if value == "__RANDOM_MOBILE__" else str(value))

        async def _fill_text(*args, **kwargs):
            fill_calls.append((args, kwargs))
            return True

        monkeypatch.setattr(runtime_answerers, "_fill_text_input", _fill_text)
        monkeypatch.setattr(runtime_answerers, "record_answer", lambda *args, **kwargs: None)

        await runtime_answerers._answer_wjx_text(object(), question, 0, ctx)

        assert [call[0][2] for call in fill_calls] == ["默认文本", "13900001111", "默认文本"]

    @pytest.mark.asyncio
    async def test_answer_wjx_score_matrix_slider_and_order_cover_main_paths(self, monkeypatch) -> None:
        ctx = _ctx(question_dimension_map={10: "D10"})
        question = _question(10, option_texts=["差", "中", "好"], options=3, rows=2)
        pending: list[tuple[object, ...]] = []
        recorded: list[tuple[tuple[object, ...], dict[str, object]]] = []
        matrix_clicks = iter([True, False])
        monkeypatch.setattr(runtime_answerers, "normalize_droplist_probs", lambda weights, count: [0.1, 0.9, 0.0][:count])
        monkeypatch.setattr(runtime_answerers, "apply_single_like_consistency", lambda probs, _current: probs)
        monkeypatch.setattr(runtime_answerers, "resolve_distribution_probabilities", lambda probs, *_args, **_kwargs: probs if isinstance(probs, list) else [1.0, 0.0, 0.0])
        monkeypatch.setattr(runtime_answerers, "get_tendency_index", lambda *_args, **_kwargs: 1)
        monkeypatch.setattr(runtime_answerers, "is_strict_ratio_question", lambda _ctx, _current: True)
        monkeypatch.setattr(runtime_answerers, "apply_matrix_row_consistency", lambda probs, _current, _row_index: probs)
        monkeypatch.setattr(runtime_answerers, "enforce_reference_rank_order", lambda probs, _reference: probs)

        async def _click_choice_input(*_args, **_kwargs):
            return True

        async def _click_matrix_cell(*_args, **_kwargs):
            return next(matrix_clicks)

        async def _set_slider_value(*_args, **_kwargs):
            return True

        async def _click_reorder_sequence(*_args, **_kwargs):
            return True

        monkeypatch.setattr(runtime_answerers, "_click_choice_input", _click_choice_input)
        monkeypatch.setattr(runtime_answerers, "_click_matrix_cell", _click_matrix_cell)
        monkeypatch.setattr(runtime_answerers, "_set_slider_value", _set_slider_value)
        monkeypatch.setattr(runtime_answerers, "_click_reorder_sequence", _click_reorder_sequence)
        monkeypatch.setattr(runtime_answerers, "record_pending_distribution_choice", lambda *args, **kwargs: pending.append(args))
        monkeypatch.setattr(runtime_answerers, "record_answer", lambda *args, **kwargs: recorded.append((args, kwargs)))
        monkeypatch.setattr(runtime_answerers.random, "shuffle", lambda values: values.reverse())

        assert await runtime_answerers._answer_wjx_score_like(object(), question, 0, ctx, psycho_plan=None, answer_type="scale")
        answered = await runtime_answerers._answer_wjx_matrix(object(), question, 0, ctx, psycho_plan=None)
        assert answered is False
        assert await runtime_answerers._answer_wjx_slider(object(), question, 0, ctx)
        assert await runtime_answerers._answer_wjx_order(object(), question)
        assert pending[0] == (ctx, 10, 1, 3)
        assert any(call[1].get("row_index") == 0 for call in recorded if call[0][1] == "matrix")
        assert any(call[0][1] == "slider" for call in recorded)
        assert any(call[0][1] == "order" for call in recorded)

    @pytest.mark.asyncio
    async def test_answer_wjx_multiple_and_dispatch_cover_random_strict_and_missing_config(self, monkeypatch) -> None:
        question = _question(11, option_texts=["甲", "乙", "丙", "丁"], options=4, multi_min_limit=2, multi_max_limit=3)
        recorded: list[tuple[tuple[object, ...], dict[str, object]]] = []
        fill_calls: list[tuple[object, ...]] = []
        monkeypatch.setattr(runtime_answerers, "get_multiple_rule_constraint", lambda *_args, **_kwargs: ({0}, {3}, None))
        monkeypatch.setattr(runtime_answerers, "_normalize_selected_indices", lambda values, count: list(dict.fromkeys(v for v in values if 0 <= v < count)))

        async def _click_choice_input(*_args, **_kwargs):
            return True

        async def _resolve_fill(*_args, **_kwargs):
            return "补"

        async def _fill_choice_option_additional_text(*_args, **_kwargs):
            fill_calls.append(_args)
            return None

        monkeypatch.setattr(runtime_answerers, "_click_choice_input", _click_choice_input)
        monkeypatch.setattr(runtime_answerers, "resolve_runtime_option_fill_text_from_config", _resolve_fill)
        monkeypatch.setattr(runtime_answerers, "_fill_choice_option_additional_text", _fill_choice_option_additional_text)
        monkeypatch.setattr(runtime_answerers, "record_answer", lambda *args, **kwargs: recorded.append((args, kwargs)))
        monkeypatch.setattr(runtime_answerers.random, "randint", lambda _start, _end: 1)
        monkeypatch.setattr(runtime_answerers.random, "sample", lambda population, count: list(population)[:count])

        ctx_random = _ctx(multiple_prob=[[-1]], multiple_option_fill_texts=[["填"]])
        assert await runtime_answerers._answer_wjx_multiple(object(), question, 0, ctx_random)
        assert recorded[0][1]["selected_indices"] == [0, 1]
        assert fill_calls

        recorded.clear()
        fill_calls.clear()
        ctx_prob = _ctx(multiple_prob=[[100, 60, 0, 10]])
        monkeypatch.setattr(runtime_answerers, "is_strict_ratio_question", lambda _ctx, _current: True)
        monkeypatch.setattr(runtime_answerers, "stochastic_round", lambda _value: 1)
        monkeypatch.setattr(runtime_answerers, "weighted_sample_without_replacement", lambda candidates, _weights, count: list(candidates)[:count])
        assert await runtime_answerers._answer_wjx_multiple(object(), question, 0, ctx_prob)
        assert recorded[0][1]["selected_indices"][0] == 0

        dispatch_ctx = _ctx(question_config_index_map={1: ("single", 0), 2: ("matrix", 0)})
        dispatch_record: list[str] = []

        async def _prepare_question_interaction(*_args, **_kwargs):
            dispatch_record.append("prepare")
            return True

        async def _answer_single(*_args, **_kwargs):
            dispatch_record.append("single")
            return True

        async def _answer_matrix(*_args, **_kwargs):
            dispatch_record.append("matrix")
            return True

        monkeypatch.setattr(runtime_answerers, "_prepare_question_interaction", _prepare_question_interaction)
        monkeypatch.setattr(runtime_answerers, "_answer_wjx_single", _answer_single)
        monkeypatch.setattr(runtime_answerers, "_answer_wjx_matrix", _answer_matrix)

        assert await runtime_answerers.answer_question_by_meta(object(), _question(1), dispatch_ctx, psycho_plan=None) is True
        assert await runtime_answerers.answer_question_by_meta(object(), _question(2), dispatch_ctx, psycho_plan=None) is True
        assert await runtime_answerers.answer_question_by_meta(object(), _question(99), _ctx(), psycho_plan=None) is False
        assert dispatch_record == ["prepare", "single", "prepare", "matrix"]
