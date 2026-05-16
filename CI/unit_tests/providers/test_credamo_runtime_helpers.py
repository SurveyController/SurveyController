from __future__ import annotations

import random

import pytest

from credamo.provider import runtime_answerers, runtime_dom
from credamo.provider import runtime


class _FakePage:
    async def evaluate(self, _script, _root):
        return "  第 1 题   测试题面  "


class _FakeRoot:
    def __init__(self, attrs):
        self._attrs = dict(attrs)

    async def get_attribute(self, name):
        return self._attrs.get(name)


class CredamoRuntimeHelperTests:
    def test_loading_shell_detection_covers_empty_answer_page(self):
        assert runtime_dom._looks_like_loading_shell("答卷", "")
        assert runtime_dom._looks_like_loading_shell("答卷", "载入中...")
        assert not runtime_dom._looks_like_loading_shell("答卷", "第 1 题 请选择一个最符合你的选项并继续作答")

    @pytest.mark.asyncio
    async def test_runtime_question_key_prefers_stable_dom_id(self):
        root = _FakeRoot({"id": "q-123"})
        assert await runtime_dom._runtime_question_key(_FakePage(), root, 1) == "id:q-123"

    @pytest.mark.asyncio
    async def test_runtime_question_key_falls_back_to_number_and_text(self):
        root = _FakeRoot({})
        assert await runtime_dom._runtime_question_key(_FakePage(), root, 3) == "num:3|text:  第 1 题   测试题面  "

    @pytest.mark.asyncio
    async def test_provider_page_id_from_root_falls_back_to_runtime_page_index(self):
        root = _FakeRoot({})
        assert await runtime._provider_page_id_from_root(_FakePage(), root, fallback_page_id=6) == "6"

    @pytest.mark.asyncio
    async def test_unanswered_question_roots_rechecks_dom_before_skipping_answered_key(self, monkeypatch):
        page = object()
        root = object()

        async def _is_answerable_root(_page, _root):
            return True

        async def _question_kind_from_root(_page, _root):
            return "scale"

        async def _question_number_from_root(_page, _root, _fallback):
            return 4

        async def _runtime_question_key(_page, _root, _question_num):
            return "id:question-4"

        states = iter([False, True, None])

        async def _question_answer_state(_page, _root, *, kind: str = ""):
            _ = kind
            return next(states)

        monkeypatch.setattr(runtime_dom, "_is_answerable_root", _is_answerable_root)
        monkeypatch.setattr(runtime_dom, "_question_kind_from_root", _question_kind_from_root)
        monkeypatch.setattr(runtime_dom, "_question_number_from_root", _question_number_from_root)
        monkeypatch.setattr(runtime_dom, "_runtime_question_key", _runtime_question_key)
        monkeypatch.setattr(runtime_dom, "_question_answer_state", _question_answer_state)

        pending = await runtime_dom._unanswered_question_roots(page, [root], {"id:question-4"})
        assert pending == [(root, 4, "id:question-4")]

        pending = await runtime_dom._unanswered_question_roots(page, [root], {"id:question-4"})
        assert pending == []

        pending = await runtime_dom._unanswered_question_roots(page, [root], {"id:question-4"})
        assert pending == []

    def test_positive_multiple_indexes_never_returns_empty_selection(self):
        random.seed(1)
        selected = runtime_answerers._positive_multiple_indexes([0, 0, 0], 3)
        assert len(selected) == 1
        assert 0 <= selected[0] < 3

    def test_positive_multiple_indexes_uses_positive_weights(self):
        random.seed(2)
        selected = runtime_answerers._positive_multiple_indexes([0, 100, 0], 3)
        assert selected == [1]

    def test_positive_multiple_indexes_with_limits_tops_up_to_min_limit(self):
        random.seed(3)
        selected = runtime_answerers._positive_multiple_indexes_with_limits([100, 0, 0, 0], 4, min_limit=2, max_limit=4)
        assert len(selected) == 2
        assert 0 in selected

    def test_positive_multiple_indexes_with_limits_trims_to_max_limit(self):
        random.seed(4)
        selected = runtime_answerers._positive_multiple_indexes_with_limits([100, 100, 100, 100], 4, min_limit=1, max_limit=2)
        assert len(selected) == 2
