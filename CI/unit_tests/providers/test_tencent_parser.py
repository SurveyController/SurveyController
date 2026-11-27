from __future__ import annotations

from unittest.mock import AsyncMock

import pytest


from tencent.provider import parser as qq_parser


class _FakeHttpResponse:
    def __init__(
        self,
        *,
        json_payload=None,
        text: str = "",
        url: str = "https://wj.qq.com/api/demo",
        headers=None,
        history=None,
        should_raise: Exception | None = None,
    ) -> None:
        self._json_payload = json_payload
        self.text = text
        self.url = url
        self.headers = headers or {}
        self.history = history or []
        self._should_raise = should_raise

    def raise_for_status(self) -> None:
        if self._should_raise is not None:
            raise self._should_raise

    def json(self):
        if isinstance(self._json_payload, Exception):
            raise self._json_payload
        return self._json_payload


class TencentParserTests:
    @pytest.mark.asyncio
    async def test_request_qq_api_raises_on_invalid_json_and_non_dict_payload(
        self, patch_attrs
    ) -> None:
        bad_json_response = _FakeHttpResponse(json_payload=ValueError("bad json"), text="not login")
        bad_json_aget = AsyncMock(return_value=bad_json_response)
        patch_attrs((qq_parser.http_client, "aget", bad_json_aget))

        with pytest.raises(RuntimeError, match="无法解析的响应：meta"):
            await qq_parser._request_qq_api("123", "meta", hash_value="hash", headers={})
        assert bad_json_aget.await_args.kwargs.get("proxies") == {}

        non_dict_response = _FakeHttpResponse(json_payload=["bad"])
        non_dict_aget = AsyncMock(return_value=non_dict_response)
        patch_attrs((qq_parser.http_client, "aget", non_dict_aget))

        with pytest.raises(RuntimeError, match="非对象响应：questions"):
            await qq_parser._request_qq_api("123", "questions", hash_value="hash", headers={})
        assert non_dict_aget.await_args.kwargs.get("proxies") == {}

    @pytest.mark.asyncio
    async def test_parse_qq_survey_returns_supported_ratings_after_locale_retry(
        self, patch_attrs
    ) -> None:
        calls: list[str] = []

        async def fake_request(_survey_id, endpoint, *, hash_value, headers, extra_params=None):
            _ = hash_value, headers
            locale = (extra_params or {}).get("locale")
            calls.append(f"{endpoint}:{locale or ''}")
            if endpoint == "session":
                return {"code": "OK", "data": {}}
            if endpoint == "meta" and locale == "zhs":
                return {"code": "FAIL", "data": {}}
            if endpoint == "questions" and locale == "zht":
                return {"code": "OK", "data": {"questions": []}}
            if endpoint == "meta" and locale == "zh":
                return {"code": "OK", "data": {"title": "腾讯问卷标题 - 腾讯问卷"}}
            if endpoint == "questions" and locale == "zh":
                return {
                    "code": "OK",
                    "data": {
                        "questions": [
                            {
                                "id": "q1",
                                "type": "star",
                                "title": "综合满意度",
                                "star_num": 3,
                                "revert_sort": True,
                                "page_id": "p1",
                                "page": 1,
                            },
                            {
                                "id": "q2",
                                "type": "matrix_star",
                                "title": "矩阵满意度",
                                "sub_titles": [{"id": "g1", "text": "服务态度"}],
                                "star_num": 3,
                                "page_id": "p1",
                                "page": 1,
                            },
                        ]
                    },
                }
            return {"code": "OK", "data": {}}

        patch_attrs((qq_parser, "_request_qq_api", fake_request))

        info, title = await qq_parser.parse_qq_survey("https://wj.qq.com/s2/123/hash/")

        assert title == "腾讯问卷标题 - 腾讯问卷"
        assert [question["provider_question_id"] for question in info] == ["q1", "q2"]
        assert [question["type_code"] for question in info] == ["5", "6"]
        assert [question["unsupported"] for question in info] == [False, False]
        assert info[0]["option_texts"] == ["3", "2", "1"]
        assert info[1]["row_texts"] == ["服务态度"]
        assert "questions:zht" in calls
        assert calls[-1] == "questions:zh"

    @pytest.mark.asyncio
    async def test_parse_qq_survey_does_not_repeat_http_failure_prefix(self, patch_attrs) -> None:
        message = "腾讯问卷 HTTP 解析失败：未返回题目"

        async def fake_fetch(*_args, **_kwargs):
            raise RuntimeError(message)

        patch_attrs((qq_parser, "_fetch_qq_survey_via_http", fake_fetch))

        with pytest.raises(RuntimeError) as failure:
            await qq_parser.parse_qq_survey("https://wj.qq.com/s2/123/hash/")

        assert str(failure.value) == message

    @pytest.mark.asyncio
    async def test_parse_qq_survey_rejects_login_url(self) -> None:
        with pytest.raises(RuntimeError, match="需要登录"):
            await qq_parser.parse_qq_survey("https://wj.qq.com/r/login.html")

    @pytest.mark.asyncio
    async def test_parse_qq_survey_login_required_http_error_is_terminal(self, patch_attrs) -> None:
        patch_attrs(
            (
                qq_parser,
                "_fetch_qq_survey_via_http",
                AsyncMock(side_effect=RuntimeError("need login")),
            ),
        )

        with pytest.raises(RuntimeError, match="需要登录"):
            await qq_parser.parse_qq_survey("https://wj.qq.com/s2/123/hash/")

    @pytest.mark.asyncio
    async def test_parse_qq_survey_http_failure_is_terminal(self, patch_attrs) -> None:
        patch_attrs(
            (
                qq_parser,
                "_fetch_qq_survey_via_http",
                lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("http failed")),
            ),
        )

        with pytest.raises(RuntimeError, match="腾讯问卷 HTTP 解析失败：http failed"):
            await qq_parser.parse_qq_survey("https://wj.qq.com/s2/123/hash/")
