from __future__ import annotations

import random

import pytest

from credamo.provider import runtime_answerers, runtime_dom


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
