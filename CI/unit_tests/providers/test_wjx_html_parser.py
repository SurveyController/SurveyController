from __future__ import annotations

from types import SimpleNamespace

import pytest

from software.core.config.codec import deserialize_question_entry, serialize_question_entry
from surveycore.core.questions.schema import QuestionEntry
from wjx.provider import parser as client_parser


class WjxHtmlParserTests:
    @pytest.mark.asyncio
    async def test_multilevel_options_use_client_http_and_keep_complete_paths(
        self, monkeypatch
    ) -> None:
        calls = []

        async def fake_aget(url, **kwargs):
            calls.append((url, kwargs))
            return SimpleNamespace(
                text='<input id="hfLevelData" value="甲|---甲\n乙" />',
                raise_for_status=lambda: None,
            )

        monkeypatch.setattr(client_parser.http_client, "aget", fake_aget)
        question = {
            "num": 2,
            "provider_type": "multilevel_dropdown",
            "provider_page_raw": {"cid": ""},
        }
        html = "<script>var activityId = 123;</script>"

        await client_parser._load_multilevel_options(
            [question], html, "https://www.wjx.cn/vm/demo.aspx"
        )

        assert calls[0][0] == "https://www.wjx.cn/joinnew/setmenuselnew.aspx"
        assert calls[0][1]["params"] == {"activityid": "123", "ct": "5", "pos": "2"}
        assert question["option_texts"] == ["甲‐乙"]
        assert question["options"] == 1
        assert question["provider_page_raw"]["submit_values"] == ["甲‐乙"]

    def test_multilevel_dropdown_weights_and_question_metadata_roundtrip(self) -> None:
        entry = QuestionEntry(
            question_type="multilevel_dropdown",
            probabilities=[0.0, 100.0],
            custom_weights=[0.0, 100.0],
            distribution_mode="custom",
            option_count=2,
            question_num=1,
        )

        restored = deserialize_question_entry(serialize_question_entry(entry))

        assert restored.question_type == "multilevel_dropdown"
        assert restored.custom_weights == [0.0, 100.0]
        assert restored.probabilities == [0.0, 100.0]
