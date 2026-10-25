from __future__ import annotations

import pytest

from software.core.task import ExecutionConfig, ExecutionState
from surveycore.providers.answering import AnswerAction
from surveycore.providers.contracts import SurveyQuestionMeta
from surveycore.wjx.provider import http_runtime as core_wjx_http
from wjx.provider import http_runtime as wjx_http

from .http_runtime_fakes import _FakeResponse


def test_wjx_submitdata_formats_common_actions() -> None:
    submitdata = wjx_http._submitdata_from_actions(
        [
            AnswerAction(
                question_num=1, kind="choice", selected_indices=(0,), record_type="single"
            ),
            AnswerAction(
                question_num=2, kind="choice", selected_indices=(0, 2), record_type="multiple"
            ),
            AnswerAction(question_num=3, kind="text", text_values=("甲", "乙"), record_type="text"),
            AnswerAction(
                question_num=4, kind="matrix", matrix_indices=(1, 2), record_type="matrix"
            ),
            AnswerAction(question_num=5, kind="slider", slider_value=66.0, record_type="slider"),
        ]
    )

    assert submitdata == "1$1}2$1|3}3$甲^乙}4$1!2,2!3}5$66.0"


def test_wjx_submitdata_uses_current_fill_delimiter_and_escapes_special_chars() -> None:
    submitdata = wjx_http._submitdata_from_actions(
        [
            AnswerAction(
                question_num=9,
                kind="choice",
                selected_indices=(1,),
                option_fill_texts=((1, "改进!内容^A$B}C|D<"),),
                record_type="single",
            ),
            AnswerAction(
                question_num=10,
                kind="text",
                text_values=("A!B", "C$D"),
                record_type="text",
            ),
        ]
    )

    assert submitdata == "9$2^改进！内容ˆAξB｝C¦D＜}10$A！B^CξD"


def test_wjx_submitdata_keeps_frontend_skip_placeholders() -> None:
    submitdata = wjx_http._submitdata_from_actions(
        [
            AnswerAction(
                question_num=1, kind="choice", selected_indices=(1,), record_type="single"
            ),
            AnswerAction(
                question_num=5, kind="choice", selected_indices=(0, 1), record_type="multiple"
            ),
        ],
        questions=[
            SurveyQuestionMeta(
                num=1, title="单选", type_code="3", option_texts=["A", "B"], options=2
            ),
            SurveyQuestionMeta(
                num=2, title="排序", type_code="11", option_texts=["A", "B", "C"], options=3
            ),
            SurveyQuestionMeta(
                num=3, title="量表", type_code="5", option_texts=["1", "2"], options=2
            ),
            SurveyQuestionMeta(num=4, title="填空", type_code="1", options=1),
            SurveyQuestionMeta(
                num=5, title="多选", type_code="4", option_texts=["A", "B"], options=2
            ),
        ],
        skipped_question_nums=(2, 3, 4),
    )

    assert submitdata == "1$2}2$-3,-3,-3}3$-3}4$(跳过)}5$1|2"


def test_wjx_default_ktimes_uses_90_seconds_with_jitter(monkeypatch) -> None:
    config = ExecutionConfig(survey_provider="wjx", answer_duration_range_seconds=(0, 0))
    monkeypatch.setattr(wjx_http.random, "gauss", lambda center, _std: center)

    assert wjx_http._sample_ktimes(config) == 90


def test_wjx_ktimes_sampling_failure_falls_back_to_90(monkeypatch) -> None:
    config = ExecutionConfig(survey_provider="wjx", answer_duration_range_seconds=(0, 0))

    def _raise(*_args, **_kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(core_wjx_http, "sample_answer_duration_seconds", _raise)

    assert wjx_http._sample_ktimes(config) == 90


def test_wjx_scene_id_extraction_prefers_page_value() -> None:
    page_html = """
    <script>
      window.initAlicom({ sceneId: "scene-real-123" });
    </script>
    """

    assert wjx_http._extract_wjx_scene_id(page_html) == "scene-real-123"
    assert wjx_http._extract_wjx_scene_id("<html></html>") == "q0hcfsca"


def test_wjx_scene_id_extraction_supports_snake_case_and_data_attr() -> None:
    assert (
        wjx_http._extract_wjx_scene_id("<script>var x = { scene_id: 'scene-snake-1' }</script>")
        == "scene-snake-1"
    )
    assert (
        wjx_http._extract_wjx_scene_id("<div data-scene-id='scene-data-2'></div>") == "scene-data-2"
    )


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
