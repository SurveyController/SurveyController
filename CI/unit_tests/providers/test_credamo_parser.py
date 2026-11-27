from __future__ import annotations
from unittest.mock import AsyncMock, patch

import pytest


from credamo.provider import parser


class CredamoParserTests:
    @pytest.mark.asyncio
    async def test_parse_credamo_survey_reads_detail_interface_questions(self) -> None:
        detail_data = {
            "surveyTitle": "Credamo 标题",
            "questions": [
                {
                    "qstNo": "Q1",
                    "qstTitle": "正式题目",
                    "questionType": 2,
                    "selector": 1,
                    "questionId": "q1",
                    "choices": [{"display": "A"}, {"display": "B"}],
                },
                {
                    "qstNo": "Q2",
                    "qstTitle": "矩阵题",
                    "questionType": 4,
                    "questionId": "q2",
                    "choices": [{"display": "行1"}, {"display": "行2"}],
                    "answers": [{"display": "满意"}, {"display": "不满意"}],
                },
            ],
        }

        with patch(
            "credamo.provider.parser._fetch_detail", new=AsyncMock(return_value=detail_data)
        ):
            info, title = await parser.parse_credamo_survey(
                "https://www.credamo.com/answer.html#/s/demo_"
            )

        assert title == "Credamo 标题"
        assert [item["title"] for item in info] == ["正式题目", "矩阵题"]
        assert info[0]["provider_type"] == "single"
        assert info[0]["option_texts"] == ["A", "B"]
        assert info[1]["provider_type"] == "matrix"
        assert info[1]["row_texts"] == ["行1", "行2"]

    @pytest.mark.asyncio
    async def test_parse_credamo_survey_rejects_empty_detail_questions(self) -> None:
        with patch(
            "credamo.provider.parser._fetch_detail",
            new=AsyncMock(return_value={"surveyTitle": "空问卷", "questions": []}),
        ):
            with pytest.raises(parser.CredamoParseError, match="未返回可解析题目"):
                await parser.parse_credamo_survey("https://www.credamo.com/answer.html#/s/demo_")
