from __future__ import annotations

import pytest

from software.core.task import ExecutionConfig, ExecutionState
from surveycore.providers.answering import AnswerAction
from surveycore.providers.contracts import SurveyQuestionMeta
from surveycore.wjx.provider import http_runtime as core_wjx_http
from wjx.provider import http_runtime as wjx_http

from CI.unit_tests.providers.http_runtime_fakes import _FakeResponse


@pytest.mark.asyncio
async def test_wjx_submit_timing_uses_configured_answer_duration(monkeypatch) -> None:
    config = ExecutionConfig(
        url="https://www.wjx.cn/vm/demo.aspx",
        survey_provider="wjx",
        answer_duration_range_seconds=(90, 90),
    )
    config.questions_metadata = {
        1: SurveyQuestionMeta(num=1, title="Q1", type_code="3", options=2, option_texts=["A", "B"]),
    }
    state = ExecutionState(config=config)
    captured: dict[str, object] = {}
    page_html = """
    <html>
      <body>
        <input type="hidden" value="2026/5/30 1:23:18" id="starttime" name="starttime" />
      </body>
    </html>
    """

    async def fake_load(*_args, **_kwargs):
        return page_html

    async def fake_build_action(*_args, **_kwargs):
        return AnswerAction(
            question_num=1, kind="choice", selected_indices=(0,), record_type="single"
        )

    async def fake_post(*_args, **kwargs):
        captured.update(kwargs)
        return _FakeResponse(text="success")

    monkeypatch.setattr(wjx_http, "_load_wjx_page", fake_load)
    monkeypatch.setattr(wjx_http, "build_answer_action", fake_build_action)
    monkeypatch.setattr(wjx_http.http_client, "apost", fake_post)
    page_start = int(
        core_wjx_http.datetime.strptime("2026/5/30 1:23:18", "%Y/%m/%d %H:%M:%S").timestamp()
    )
    monkeypatch.setattr(wjx_http.time, "time", lambda: float(page_start + 5))
    monkeypatch.setattr(wjx_http.random, "gauss", lambda center, _std: center)

    ok = await wjx_http.brush_wjx_http(
        config,
        state,
        proxy_address="http://1.1.1.1:80",
        user_agent="UA",
    )

    assert ok is True
    assert captured["params"]["ktimes"] == "90"
    assert captured["params"]["starttime"] == "2026/5/30 1:21:53"
    assert captured["params"]["cst"] == str((page_start + 5 - 90) * 1000)


@pytest.mark.asyncio
async def test_wjx_submit_body_uses_extracted_scene_id(monkeypatch) -> None:
    config = ExecutionConfig(
        url="https://www.wjx.cn/vm/demo.aspx",
        survey_provider="wjx",
    )
    config.questions_metadata = {
        1: SurveyQuestionMeta(num=1, title="Q1", type_code="3", options=2, option_texts=["A", "B"]),
    }
    state = ExecutionState(config=config)
    captured: dict[str, object] = {}

    async def fake_load(*_args, **_kwargs):
        return """
        <html>
          <script>var captchaConfig = { sceneId: 'scene-from-page' };</script>
        </html>
        """

    async def fake_build_action(*_args, **_kwargs):
        return AnswerAction(
            question_num=1, kind="choice", selected_indices=(0,), record_type="single"
        )

    async def fake_post(*_args, **kwargs):
        captured.update(kwargs)
        return _FakeResponse(text="success")

    monkeypatch.setattr(wjx_http, "_load_wjx_page", fake_load)
    monkeypatch.setattr(wjx_http, "build_answer_action", fake_build_action)
    monkeypatch.setattr(wjx_http.http_client, "apost", fake_post)

    ok = await wjx_http.brush_wjx_http(config, state, user_agent="UA")

    assert ok is True
    assert captured["data"] == {"submitdata": "1$1", "sceneId": "scene-from-page"}
