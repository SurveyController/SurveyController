from __future__ import annotations

from contextlib import contextmanager

import pytest

from wjx.provider import parser as wjx_parser


class _FakeHttpResponse:
    def __init__(self, html: str, *, should_raise: Exception | None = None) -> None:
        self.text = html
        self._should_raise = should_raise

    def raise_for_status(self) -> None:
        if self._should_raise is not None:
            raise self._should_raise


class _FakeBrowserDriver:
    def __init__(self, html: str) -> None:
        self._html = html
        self.page = self._FakePage()
        self.get_calls: list[tuple[str, int, str]] = []

    class _FakePage:
        def wait_for_selector(self, *args, **kwargs) -> None:
            return None

        def wait_for_load_state(self, *args, **kwargs) -> None:
            return None

    def get(self, url: str, timeout: int = 20000, wait_until: str = "domcontentloaded") -> None:
        self.get_calls.append((url, timeout, wait_until))

    @property
    def page_source(self) -> str:
        return self._html


class WjxParserTests:
    def test_is_paused_survey_page_accepts_pause_copy(self) -> None:
        html = "<html><body>此问卷（123）已暂停，不能填写</body></html>"
        assert wjx_parser.is_paused_survey_page(html)

    def test_build_not_open_survey_message_returns_time_when_gate_page_detected(self) -> None:
        html = """
        <html>
          <body>
            此问卷将于 2026-05-06 09:30 开放
            请到时再进入此页面进行填写
          </body>
        </html>
        """
        assert (
            wjx_parser.build_not_open_survey_message(html)
            == "该问卷暂未开放，无法解析，开放时间：2026-05-06 09:30"
        )

    def test_build_not_open_survey_message_skips_open_question_container(self) -> None:
        html = """
        <html>
          <body>
            <div id="divQuestion">
              <fieldset>
                <div topic="1" type="3">题目 1</div>
              </fieldset>
            </div>
            此问卷将于 2026-05-06 09:30 开放
          </body>
        </html>
        """
        assert wjx_parser.build_not_open_survey_message(html) is None

    def test_parse_wjx_survey_raises_paused_error_from_http_html(self, patch_attrs) -> None:
        patch_attrs(
            (wjx_parser.http_client, "get", lambda *_args, **_kwargs: _FakeHttpResponse("<html><body>问卷已暂停，不能填写</body></html>")),
        )

        with pytest.raises(wjx_parser.SurveyPausedError, match="问卷已暂停"):
            wjx_parser.parse_wjx_survey("https://www.wjx.cn/vm/demo.aspx")

    def test_parse_wjx_survey_raises_not_open_error_from_http_html(self, patch_attrs) -> None:
        html = "<html><body>此问卷将于 2026-05-06 09:30 开放，请到时再进入此页面进行填写</body></html>"
        patch_attrs(
            (wjx_parser.http_client, "get", lambda *_args, **_kwargs: _FakeHttpResponse(html)),
        )

        with pytest.raises(wjx_parser.SurveyNotOpenError, match="开放时间：2026-05-06 09:30"):
            wjx_parser.parse_wjx_survey("https://www.wjx.cn/vm/demo.aspx")

    def test_parse_wjx_survey_returns_http_parse_result_without_browser_fallback(self, patch_attrs) -> None:
        browser_used = {"value": False}

        @contextmanager
        def fake_pool():
            browser_used["value"] = True
            yield _FakeBrowserDriver("<html></html>")

        patch_attrs(
            (wjx_parser.http_client, "get", lambda *_args, **_kwargs: _FakeHttpResponse("<html><body>ok</body></html>")),
            (wjx_parser, "parse_survey_questions_from_html", lambda _html: [{"num": 1, "title": "Q1", "type_code": "3"}]),
            (wjx_parser, "extract_survey_title_from_html", lambda _html: "  标题  "),
            (wjx_parser, "acquire_parse_browser_session", fake_pool),
        )

        info, title = wjx_parser.parse_wjx_survey("https://www.wjx.cn/vm/demo.aspx")

        assert info == [{"num": 1, "title": "Q1", "type_code": "3"}]
        assert title == "标题"
        assert not browser_used["value"]

    def test_parse_wjx_survey_keeps_http_fast_path_even_when_static_page_has_hidden_questions(self, patch_attrs) -> None:
        static_html = """
        <html><body>
          <div id="divQuestion">
            <fieldset>
              <div id="div20" topic="20" type="5" style="display:none;"><div class="topicnumber">20.</div></div>
              <div id="div23" topic="23" type="2"><div class="topicnumber">23.</div></div>
            </fieldset>
          </div>
        </body></html>
        """
        browser_used = {"value": False}

        @contextmanager
        def fake_pool():
            browser_used["value"] = True
            yield _FakeBrowserDriver("<html></html>")

        patch_attrs(
            (wjx_parser.http_client, "get", lambda *_args, **_kwargs: _FakeHttpResponse(static_html)),
            (wjx_parser, "parse_survey_questions_from_html", lambda _html: [{"num": 23, "display_num": 22, "title": "Q23", "type_code": "2"}]),
            (wjx_parser, "extract_survey_title_from_html", lambda _html: "标题"),
            (wjx_parser, "acquire_parse_browser_session", fake_pool),
        )

        info, title = wjx_parser.parse_wjx_survey("https://www.wjx.cn/vm/demo.aspx")

        assert info == [{"num": 23, "display_num": 22, "title": "Q23", "type_code": "2"}]
        assert title == "标题"
        assert not browser_used["value"]

    def test_parse_wjx_survey_raises_combined_environment_message(self, patch_attrs) -> None:
        http_exc = OSError("socket blocked")
        http_exc.winerror = 10013
        browser_exc = RuntimeError("playwright blocked")

        @contextmanager
        def fake_pool():
            yield _FakeBrowserDriver("<html></html>")

        patch_attrs(
            (wjx_parser.http_client, "get", lambda *_args, **_kwargs: (_ for _ in ()).throw(http_exc)),
            (wjx_parser, "acquire_parse_browser_session", fake_pool),
            (wjx_parser, "parse_survey_questions_from_html", lambda _html: []),
            (wjx_parser, "is_playwright_startup_environment_error", lambda exc: exc is browser_exc),
            (wjx_parser, "describe_playwright_startup_error", lambda _exc: "不该走到这里"),
        )

        driver = _FakeBrowserDriver("<html><body></body></html>")

        @contextmanager
        def fake_pool_with_error():
            yield driver
            raise browser_exc

        patch_attrs(
            (wjx_parser, "acquire_parse_browser_session", fake_pool_with_error),
        )

        with pytest.raises(RuntimeError, match="WinError 10013"):
            wjx_parser.parse_wjx_survey("https://www.wjx.cn/vm/demo.aspx")

    def test_parse_wjx_survey_uses_browser_fallback_message_when_http_error_is_plain(self, patch_attrs) -> None:
        http_exc = RuntimeError("http failed")
        browser_exc = RuntimeError("browser failed")

        @contextmanager
        def fake_pool():
            raise browser_exc
            yield

        patch_attrs(
            (wjx_parser.http_client, "get", lambda *_args, **_kwargs: (_ for _ in ()).throw(http_exc)),
            (wjx_parser, "acquire_parse_browser_session", fake_pool),
            (wjx_parser, "is_playwright_startup_environment_error", lambda exc: False),
        )

        with pytest.raises(RuntimeError, match="无法获取问卷网页：http failed"):
            wjx_parser.parse_wjx_survey("https://www.wjx.cn/vm/demo.aspx")
