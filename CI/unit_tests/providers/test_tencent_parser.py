from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace

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


class _FakeQQPage:
    def __init__(self, *, payload=None, url: str = "https://wj.qq.com/s2/123/hash/", wait_selector_error: Exception | None = None) -> None:
        self._payload = payload or {}
        self.url = url
        self.wait_selector_error = wait_selector_error
        self.selector_waits: list[tuple[str, str, int]] = []
        self.load_state_waits: list[tuple[str, int]] = []
        self.evaluations: list[tuple[str, object]] = []

    def wait_for_selector(self, selector: str, *, state: str, timeout: int) -> None:
        self.selector_waits.append((selector, state, timeout))
        if self.wait_selector_error is not None:
            raise self.wait_selector_error

    def wait_for_load_state(self, state: str, *, timeout: int) -> None:
        self.load_state_waits.append((state, timeout))

    def evaluate(self, script: str, payload: object):
        self.evaluations.append((script, payload))
        return self._payload


class _FakeQQDriver:
    def __init__(self, page: _FakeQQPage | None, *, title: str = "") -> None:
        self.page = page
        self.title = title
        self.current_url = getattr(page, "url", "")
        self.get_calls: list[str] = []

    def get(self, url: str) -> None:
        self.get_calls.append(url)


class TencentParserTests:
    def test_login_required_helpers_cover_url_error_and_response(self) -> None:
        assert qq_parser._is_qq_login_required_url("https://open.weixin.qq.com/connect/confirm?a=1")
        assert qq_parser._is_qq_login_required_url("wj.qq.com/r/login.html")
        assert qq_parser._is_qq_login_required_error({"msg": ["need login"]})
        assert not qq_parser._is_qq_login_required_error("all good")

        response = _FakeHttpResponse(
            text="normal",
            headers={"location": "https://wj.qq.com/r/login.html"},
            history=[SimpleNamespace(url="https://foo.example")],
        )
        assert qq_parser._is_qq_login_required_response(response)

    def test_request_qq_api_raises_on_invalid_json_and_non_dict_payload(self, patch_attrs) -> None:
        bad_json_response = _FakeHttpResponse(json_payload=ValueError("bad json"), text="not login")
        patch_attrs((qq_parser.http_client, "get", lambda *_args, **_kwargs: bad_json_response))

        with pytest.raises(RuntimeError, match="无法解析的响应：meta"):
            qq_parser._request_qq_api("123", "meta", hash_value="hash", headers={})

        non_dict_response = _FakeHttpResponse(json_payload=["bad"])
        patch_attrs((qq_parser.http_client, "get", lambda *_args, **_kwargs: non_dict_response))

        with pytest.raises(RuntimeError, match="非对象响应：questions"):
            qq_parser._request_qq_api("123", "questions", hash_value="hash", headers={})

    def test_ensure_api_ok_and_http_fetch_locale_fallback(self, patch_attrs) -> None:
        calls: list[str] = []

        def fake_request(_survey_id, endpoint, *, hash_value, headers, extra_params=None):
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
                            {"id": "q1", "type": "radio", "title": "题目1", "options": [{"text": "A"}], "page_id": "p1", "page": 1}
                        ]
                    },
                }
            return {"code": "OK", "data": {}}

        patch_attrs((qq_parser, "_request_qq_api", fake_request))

        info, title = qq_parser._fetch_qq_survey_via_http("123", "hash")

        assert title == "腾讯问卷标题 - 腾讯问卷"
        assert qq_parser._normalize_qq_title("标题 - 腾讯问卷") == "标题"
        assert info[0]["provider_question_id"] == "q1"
        assert "meta:zhs" in calls
        assert "questions:zh" in calls

        with pytest.raises(RuntimeError, match="接口返回异常（meta）：FAIL"):
            qq_parser._ensure_qq_api_ok({"code": "FAIL", "data": {}}, "meta")

        with pytest.raises(RuntimeError, match="缺少 data 对象：meta"):
            qq_parser._ensure_qq_api_ok({"code": "OK", "data": []}, "meta")

    def test_builders_and_standardize_questions_cover_fillblank_rating_and_unsupported(self) -> None:
        question = {
            "id": "q1",
            "type": "checkbox",
            "title": "  题目1  ",
            "description": " 描述 ",
            "options": [
                {"text": "正常选项"},
                {"text": "其他 {fillblank-1}", "extra": {"fillblank": True}},
            ],
            "sub_titles": [{"text": " 行1 "}, {"text": "行2"}],
            "page_id": "page-a",
            "page": "2",
            "min_length": 1,
            "max_length": 3,
            "required": True,
        }
        rating_question = {
            "id": "q2",
            "type": "star",
            "title": "评分题",
            "star_begin_num": 3,
            "star_num": 4,
            "page_id": "page-b",
            "page": "4",
        }
        unsupported_question = {
            "id": "q3",
            "type": "upload",
            "title": "上传题",
            "page_id": "page-b",
            "page": "4",
        }

        normalized = qq_parser._standardize_qq_questions([question, rating_question, unsupported_question])

        first = normalized[0]
        assert qq_parser._normalize_qq_option_text(" 其他 _{fillblank-1} ") == "其他"
        assert qq_parser._option_payload_contains_fillblank({"nested": ["x", "{fillblank-a}"]})
        assert first["fillable_options"] == [1]
        assert first["row_texts"] == ["行1", "行2"]
        assert first["multi_min_limit"] == 1
        assert first["multi_max_limit"] == 3
        assert first["page"] == 1

        second = normalized[1]
        assert second["is_rating"]
        assert second["option_texts"] == ["3", "4", "5", "6"]
        assert second["rating_max"] == 4

        third = normalized[2]
        assert third["unsupported"]
        assert "暂不支持腾讯题型" in third["unsupported_reason"]

    def test_parse_qq_survey_rejects_login_url_and_supports_browser_fallback(self, patch_attrs) -> None:
        with pytest.raises(RuntimeError, match="需要登录"):
            qq_parser.parse_qq_survey("https://wj.qq.com/r/login.html")

        browser_payload = {
            "ok": True,
            "payload": {
                "code": "OK",
                "data": {
                    "questions": [
                        {"id": "q1", "type": "radio", "title": "题目1", "options": [{"text": "选项A"}], "page_id": "p1", "page": 1}
                    ]
                },
            },
            "metaPayload": {"code": "OK", "data": {"title": "浏览器标题 - 腾讯问卷"}},
            "title": "",
            "pageUrl": "https://wj.qq.com/s2/123/hash/",
            "status": 200,
        }
        page = _FakeQQPage(payload=browser_payload, wait_selector_error=RuntimeError("wait failed"))
        driver = _FakeQQDriver(page, title="备用浏览器标题")

        @contextmanager
        def fake_pool():
            yield driver

        patch_attrs(
            (qq_parser, "_fetch_qq_survey_via_http", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("http failed"))),
            (qq_parser, "acquire_parse_browser_session", fake_pool),
        )

        info, title = qq_parser.parse_qq_survey("https://wj.qq.com/s2/123/hash/")

        assert driver.get_calls == ["https://wj.qq.com/s2/123/hash/"]
        assert info[0]["title"] == "题目1"
        assert title == "浏览器标题"

    def test_parse_qq_survey_browser_fallback_rejects_missing_page_and_bad_status(self, patch_attrs) -> None:
        missing_page_driver = _FakeQQDriver(None)

        @contextmanager
        def fake_pool_missing():
            yield missing_page_driver

        patch_attrs(
            (qq_parser, "_fetch_qq_survey_via_http", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("http failed"))),
            (qq_parser, "acquire_parse_browser_session", fake_pool_missing),
        )

        with pytest.raises(RuntimeError, match="不支持腾讯问卷解析"):
            qq_parser.parse_qq_survey("https://wj.qq.com/s2/123/hash/")

        bad_payload_driver = _FakeQQDriver(_FakeQQPage(payload={"ok": False, "status": 403}))

        @contextmanager
        def fake_pool_bad():
            yield bad_payload_driver

        patch_attrs((qq_parser, "acquire_parse_browser_session", fake_pool_bad))

        with pytest.raises(RuntimeError, match="HTTP 403"):
            qq_parser.parse_qq_survey("https://wj.qq.com/s2/123/hash/")
