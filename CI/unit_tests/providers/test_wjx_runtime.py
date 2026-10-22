from __future__ import annotations

from types import SimpleNamespace

import pytest

from software.core.task import ExecutionConfig, ExecutionState
from surveycore.providers.answering import AnswerAction
from surveycore.providers.contracts import SurveyQuestionMeta
from wjx.provider import http_runtime as wjx_http

from .http_runtime_fakes import _FakeResponse


@pytest.mark.asyncio
async def test_wjx_http_runtime_uses_proxy_and_posts_submitdata(monkeypatch) -> None:
    config = ExecutionConfig(
        url="https://www.wjx.cn/vm/demo.aspx",
        survey_provider="wjx",
    )
    config.questions_metadata = {
        1: SurveyQuestionMeta(num=1, title="Q1", type_code="3", options=2, option_texts=["A", "B"]),
    }
    state = ExecutionState(config=config)
    captured: dict[str, object] = {}
    load_kwargs: dict[str, object] = {}

    async def fake_load(*_args, **_kwargs):
        load_kwargs.update(_kwargs)
        return "<html><body><input type='hidden' value='2026/5/30 1:23:18' id='starttime' name='starttime' /></body></html>"

    async def fake_build_action(*_args, **_kwargs):
        return AnswerAction(question_num=1, kind="choice", selected_indices=(0,), record_type="single")

    async def fake_post(*_args, **kwargs):
        captured.update(kwargs)
        return _FakeResponse(text="success")

    monkeypatch.setattr(wjx_http, "_load_wjx_page", fake_load)
    monkeypatch.setattr(wjx_http, "build_answer_action", fake_build_action)
    monkeypatch.setattr(wjx_http.http_client, "apost", fake_post)
    monkeypatch.setattr(wjx_http.time, "time", lambda: 1710000000.0)
    monkeypatch.setattr(wjx_http.random, "gauss", lambda center, _std: center)

    ok = await wjx_http.brush_wjx_http(
        config,
        state,
        proxy_address="http://1.1.1.1:80",
        user_agent="UA",
    )

    assert ok is True
    assert load_kwargs["proxies"] == {}
    assert captured["proxies"] == "http://1.1.1.1:80"
    assert captured["data"] == {"submitdata": "1$1", "sceneId": "q0hcfsca"}
    assert captured["params"]["starttime"] == wjx_http._format_wjx_starttime(1710000000 - 90)


@pytest.mark.asyncio
async def test_wjx_http_runtime_uses_wechat_channel_params_for_wechat_profile(monkeypatch) -> None:
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
        return "<html><body><input type='hidden' value='2026/5/30 1:23:18' id='starttime' name='starttime' /></body></html>"

    async def fake_build_action(*_args, **_kwargs):
        return AnswerAction(question_num=1, kind="choice", selected_indices=(0,), record_type="single")

    async def fake_post(*_args, **kwargs):
        captured.update(kwargs)
        return _FakeResponse(text="success")

    monkeypatch.setattr(wjx_http, "_load_wjx_page", fake_load)
    monkeypatch.setattr(wjx_http, "build_answer_action", fake_build_action)
    monkeypatch.setattr(wjx_http.http_client, "apost", fake_post)

    ok = await wjx_http.brush_wjx_http(
        config,
        state,
        user_agent="Mozilla/5.0 MicroMessenger/8.0.43 WeChat/arm64",
        user_agent_profile=SimpleNamespace(category="wechat", ua="Mozilla/5.0 MicroMessenger/8.0.43 WeChat/arm64"),
    )

    assert ok is True
    assert captured["params"]["source"] == "微信"
    assert captured["params"]["iwx"] == "1"
    assert captured["params"]["wxfs"] == "100"
    assert captured["params"]["wxappid"] == "wx8fe84c5d52db247a"
    assert "openid" in captured["params"]
    assert "unionId" in captured["params"]


@pytest.mark.asyncio
async def test_wjx_http_runtime_uses_default_pc_ua_when_user_agent_is_not_explicitly_selected(monkeypatch) -> None:
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
        return None

    async def fake_build_action(*_args, **_kwargs):
        return AnswerAction(question_num=1, kind="choice", selected_indices=(0,), record_type="single")

    async def fake_post(*_args, **kwargs):
        captured.update(kwargs)
        return _FakeResponse(text="success")

    monkeypatch.setattr(wjx_http, "_load_wjx_page", fake_load)
    monkeypatch.setattr(wjx_http, "build_answer_action", fake_build_action)
    monkeypatch.setattr(wjx_http.http_client, "apost", fake_post)

    ok = await wjx_http.brush_wjx_http(
        config,
        state,
        user_agent=None,
    )

    assert ok is True
    assert captured["params"]["source"] == "直链访问"
    assert "MicroMessenger" not in str(captured["headers"]["User-Agent"])
    assert "Windows NT" in str(captured["headers"]["User-Agent"])
    assert "iwx" not in captured["params"]
    assert "wxfs" not in captured["params"]


@pytest.mark.asyncio
async def test_wjx_http_runtime_uses_mobile_channel_for_mobile_profile(monkeypatch) -> None:
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
        return None

    async def fake_build_action(*_args, **_kwargs):
        return AnswerAction(question_num=1, kind="choice", selected_indices=(0,), record_type="single")

    async def fake_post(*_args, **kwargs):
        captured.update(kwargs)
        return _FakeResponse(text="success")

    monkeypatch.setattr(wjx_http, "_load_wjx_page", fake_load)
    monkeypatch.setattr(wjx_http, "build_answer_action", fake_build_action)
    monkeypatch.setattr(wjx_http.http_client, "apost", fake_post)

    ok = await wjx_http.brush_wjx_http(
        config,
        state,
        user_agent="Mozilla/5.0 Chrome/121.0.0.0 Mobile Safari/537.36",
        user_agent_profile=SimpleNamespace(category="mobile", ua="Mozilla/5.0 Chrome/121.0.0.0 Mobile Safari/537.36"),
    )

    assert ok is True
    assert captured["params"]["source"] == "手机访问"
    assert "iwx" not in captured["params"]
    assert "wxfs" not in captured["params"]


@pytest.mark.asyncio
async def test_wjx_http_runtime_uses_pc_channel_for_pc_profile(monkeypatch) -> None:
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
        return None

    async def fake_build_action(*_args, **_kwargs):
        return AnswerAction(question_num=1, kind="choice", selected_indices=(0,), record_type="single")

    async def fake_post(*_args, **kwargs):
        captured.update(kwargs)
        return _FakeResponse(text="success")

    monkeypatch.setattr(wjx_http, "_load_wjx_page", fake_load)
    monkeypatch.setattr(wjx_http, "build_answer_action", fake_build_action)
    monkeypatch.setattr(wjx_http.http_client, "apost", fake_post)

    ok = await wjx_http.brush_wjx_http(
        config,
        state,
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/121.0.0.0 Safari/537.36",
        user_agent_profile=SimpleNamespace(category="pc", ua="Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/121.0.0.0 Safari/537.36"),
    )

    assert ok is True
    assert captured["params"]["source"] == "直链访问"
    assert "iwx" not in captured["params"]
    assert "wxfs" not in captured["params"]


@pytest.mark.asyncio
async def test_wjx_http_runtime_passes_slot_label_to_reverse_fill_builder(monkeypatch) -> None:
    config = ExecutionConfig(
        url="https://www.wjx.cn/vm/demo.aspx",
        survey_provider="wjx",
    )
    config.questions_metadata = {
        1: SurveyQuestionMeta(num=1, title="Q1", type_code="3", option_texts=["A", "B"], options=2),
    }
    state = ExecutionState(config=config)
    seen_thread_names: list[str] = []

    async def fake_build_action(_driver, question, _ctx, **kwargs):
        seen_thread_names.append(str(kwargs.get("thread_name") or ""))
        return AnswerAction(
            question_num=int(question.num),
            kind="choice",
            selected_indices=(0,),
            record_type="single",
        )

    monkeypatch.setattr(wjx_http, "build_answer_action", fake_build_action)

    actions = await wjx_http._build_actions(
        config,
        state,
        psycho_plan=None,
        stop_signal=None,
        thread_name="Slot-2",
    )

    assert [action.question_num for action in actions] == [1]
    assert seen_thread_names == ["Slot-2"]


@pytest.mark.asyncio
async def test_wjx_http_runtime_clears_prefill_cache_on_error(monkeypatch) -> None:
    config = ExecutionConfig(
        url="https://www.wjx.cn/vm/demo.aspx",
        survey_provider="wjx",
    )
    config.questions_metadata = {
        1: SurveyQuestionMeta(num=1, title="Q1", type_code="1", text_inputs=1),
    }
    config.question_config_index_map = {1: ("text", 0)}
    config.text_ai_flags = [True]
    state = ExecutionState(config=config)

    async def fake_load(*_args, **_kwargs):
        return "<html><body><input type='hidden' value='2026/5/30 1:23:18' id='starttime' name='starttime' /></body></html>"

    async def fake_prefill(_questions, ctx, *, thread_name=""):
        ctx.set_ai_prefill_answers(thread_name, {1: ("缓存答案",)})
        return None

    async def fake_build_action(*_args, **_kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(wjx_http, "_load_wjx_page", fake_load)
    monkeypatch.setattr(wjx_http, "prefill_ai_answers_for_questions", fake_prefill)
    monkeypatch.setattr(wjx_http, "build_answer_action", fake_build_action)

    with pytest.raises(RuntimeError, match="boom"):
        await wjx_http.brush_wjx_http(
            config,
            state,
            thread_name="slot-3",
        )

    assert state.get_ai_prefill_answer("slot-3", 1) is None
