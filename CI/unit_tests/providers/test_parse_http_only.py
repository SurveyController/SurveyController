from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from credamo.provider import parser as credamo_parser
from tencent.provider import parser as qq_parser
from wjx.provider import parser as wjx_parser


class ParseHttpOnlyTests:
    def test_parser_modules_do_not_expose_parse_browser_pool(self) -> None:
        assert not hasattr(wjx_parser, "acquire_parse_browser_session")
        assert not hasattr(qq_parser, "acquire_parse_browser_session")
        assert not hasattr(credamo_parser, "acquire_parse_browser_session")

    @pytest.mark.asyncio
    async def test_wjx_http_error_does_not_fall_back_to_browser(self) -> None:
        with patch("wjx.provider.parser.http_client.aget", new=AsyncMock(side_effect=RuntimeError("http failed"))):
            with pytest.raises(RuntimeError, match="无法获取问卷网页：http failed"):
                await wjx_parser.parse_wjx_survey("https://www.wjx.cn/vm/demo.aspx")

    @pytest.mark.asyncio
    async def test_qq_http_error_does_not_fall_back_to_browser(self) -> None:
        with patch("tencent.provider.parser._fetch_qq_survey_via_http", new=AsyncMock(side_effect=RuntimeError("http failed"))):
            with pytest.raises(RuntimeError, match="腾讯问卷 HTTP 解析失败：http failed"):
                await qq_parser.parse_qq_survey("https://wj.qq.com/s2/123/hash/")

    @pytest.mark.asyncio
    async def test_credamo_uses_detail_api_for_parse(self) -> None:
        class _FakeSession:
            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

        payload = {
            "surveyTitle": "Credamo 标题",
            "questions": [
                {
                    "qstNo": "Q1",
                    "questionId": "q1",
                    "questionType": 2,
                    "selector": 1,
                    "qstTitle": "Q1",
                    "choices": [{"display": "A"}],
                }
            ],
        }

        with patch("credamo.provider.parser._CredamoHttpSession", return_value=_FakeSession()), \
             patch("credamo.provider.parser._fetch_detail", new=AsyncMock(return_value=payload)) as fetch_detail:
            info, title = await credamo_parser.parse_credamo_survey("https://www.credamo.com/answer.html#/s/demo_")

        assert title == "Credamo 标题"
        assert len(info) == 1
        assert info[0]["provider_question_id"] == "q1"
        fetch_detail.assert_awaited_once()
