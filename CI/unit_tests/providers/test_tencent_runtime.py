from __future__ import annotations

from types import SimpleNamespace

import pytest

from software.core.task import ExecutionConfig, ExecutionState
from surveycore.providers.answering import AnswerAction
from surveycore.providers.contracts import SurveyQuestionMeta
from tencent.provider import http_runtime as qq_http

from .http_runtime_fakes import _FakeResponse


@pytest.mark.asyncio
async def test_qq_http_runtime_uses_proxy_and_answer_session(monkeypatch) -> None:
    config = ExecutionConfig(
        url="https://wj.qq.com/s2/123/hash/",
        survey_provider="qq",
        answer_duration_range_seconds=(480, 480),
    )
    config.questions_metadata = {
        1: SurveyQuestionMeta(num=1, title="Q1", provider="qq", provider_question_id="q1", provider_type="radio"),
    }
    state = ExecutionState(config=config)
    captured = SimpleNamespace(fetch_proxies=None, post_kwargs=None)
    session_checks: list[str] = []

    async def fake_fetch(*_args, headers, proxies, **_kwargs):
        captured.fetch_proxies = proxies
        headers["X-Answer-Session"] = "sess"
        return "sess", {"answer_session": {"last_submitted_at": 10, "last_answer_id": 1}}, [{"id": "q1", "type": "radio", "options": [{"id": "o1", "text": "A"}], "page_id": "p1"}]

    async def fake_build_action(*_args, **_kwargs):
        return AnswerAction(question_num=1, question_id="q1", kind="choice", selected_indices=(0,), record_type="single")

    async def fake_post(*_args, **kwargs):
        captured.post_kwargs = kwargs
        return _FakeResponse(payload={"code": "OK", "data": {"answer_hash": "hash-ok"}})

    async def fake_request_qq_api(_survey_id, endpoint, **_kwargs):
        session_checks.append(endpoint)
        return {"code": "OK", "data": {"answer_session": {"last_submitted_at": 11, "last_answer_id": 2}}}

    monkeypatch.setattr(qq_http, "_fetch_submit_source", fake_fetch)
    monkeypatch.setattr(qq_http, "build_answer_action", fake_build_action)
    monkeypatch.setattr(qq_http.http_client, "apost", fake_post)
    monkeypatch.setattr(qq_http, "_request_qq_api", fake_request_qq_api)
    monkeypatch.setattr(qq_http, "sample_answer_duration_seconds", lambda *_args, **_kwargs: 480.0)

    ok = await qq_http.brush_qq_http(
        config,
        state,
        proxy_address="http://1.1.1.1:80",
        user_agent="UA",
    )

    assert ok is True
    assert captured.fetch_proxies == {}
    assert captured.post_kwargs["proxies"] == "http://1.1.1.1:80"
    assert captured.post_kwargs["headers"]["X-Answer-Session"] == "sess"
    assert captured.post_kwargs["json"]["answer_survey"]["duration"] == 480
    assert session_checks == ["session"]


@pytest.mark.asyncio
async def test_qq_http_runtime_submits_only_visible_questions_grouped_by_page(monkeypatch) -> None:
    config = ExecutionConfig(
        url="https://wj.qq.com/s2/123/hash/",
        survey_provider="qq",
    )
    config.questions_metadata = {
        1: SurveyQuestionMeta(
            num=1,
            title="Q1",
            provider="qq",
            provider_question_id="q1",
            provider_type="radio",
            has_jump=True,
            logic_parse_status="complete",
            jump_rules=[{"option_index": 1, "jumpto": 3}],
            option_texts=["A", "B"],
            options=2,
        ),
        2: SurveyQuestionMeta(
            num=2,
            title="Q2",
            provider="qq",
            provider_question_id="q2",
            provider_type="radio",
            has_display_condition=True,
            logic_parse_status="complete",
            display_conditions=[{"condition_question_num": 1, "condition_mode": "selected", "condition_option_indices": [0]}],
            option_texts=["C", "D"],
            options=2,
        ),
        3: SurveyQuestionMeta(
            num=3,
            title="Q3",
            provider="qq",
            provider_question_id="q3",
            provider_type="radio",
            option_texts=["E", "F"],
            options=2,
        ),
    }
    state = ExecutionState(config=config)
    captured: dict[str, object] = {}
    session_checks: list[str] = []

    async def fake_fetch(*_args, **_kwargs):
        return "sess", {"answer_session": {"last_submitted_at": 20, "last_answer_id": 3}}, [
            {"id": "q1", "type": "radio", "options": [{"id": "o1", "text": "A"}, {"id": "o2", "text": "B"}], "page_id": "p1"},
            {"id": "q2", "type": "radio", "options": [{"id": "o3", "text": "C"}, {"id": "o4", "text": "D"}], "page_id": "p1"},
            {"id": "q3", "type": "radio", "options": [{"id": "o5", "text": "E"}, {"id": "o6", "text": "F"}], "page_id": "p2"},
        ]

    async def fake_build_action(_driver, question, _ctx, **_kwargs):
        if int(question.num) == 1:
            return AnswerAction(question_num=1, question_id="q1", kind="choice", selected_indices=(1,), record_type="single")
        if int(question.num) == 3:
            return AnswerAction(question_num=3, question_id="q3", kind="choice", selected_indices=(0,), record_type="single")
        raise AssertionError("隐藏题不该进 HTTP 构建")

    async def fake_post(*_args, **kwargs):
        captured.update(kwargs)
        return _FakeResponse(payload={"code": "OK", "data": {"answer_hash": "hash-ok"}})

    async def fake_request_qq_api(_survey_id, endpoint, **_kwargs):
        session_checks.append(endpoint)
        return {"code": "OK", "data": {"answer_session": {"last_submitted_at": 21, "last_answer_id": 4}}}

    monkeypatch.setattr(qq_http, "_fetch_submit_source", fake_fetch)
    monkeypatch.setattr(qq_http, "build_answer_action", fake_build_action)
    monkeypatch.setattr(qq_http.http_client, "apost", fake_post)
    monkeypatch.setattr(qq_http, "_request_qq_api", fake_request_qq_api)

    ok = await qq_http.brush_qq_http(config, state)

    assert ok is True
    pages = captured["json"]["answer_survey"]["pages"]
    assert [page["id"] for page in pages] == ["p1", "p2"]
    assert [[question["id"] for question in page["questions"]] for page in pages] == [["q1"], ["q3"]]
    assert session_checks == ["session"]


@pytest.mark.asyncio
async def test_qq_http_runtime_blocks_unparsed_display_logic(monkeypatch) -> None:
    config = ExecutionConfig(
        url="https://wj.qq.com/s2/123/hash/",
        survey_provider="qq",
    )
    config.questions_metadata = {
        1: SurveyQuestionMeta(
            num=1,
            title="Q1",
            provider="qq",
            provider_question_id="q1",
            provider_type="radio",
            option_texts=["A", "B"],
            options=2,
        ),
        2: SurveyQuestionMeta(
            num=2,
            title="Q2",
            provider="qq",
            provider_question_id="q2",
            provider_type="radio",
            has_display_condition=True,
            logic_parse_status="unknown",
            option_texts=["C", "D"],
            options=2,
        ),
    }
    state = ExecutionState(config=config)

    async def fake_fetch(*_args, **_kwargs):
        return "sess", {}, [
            {"id": "q1", "type": "radio", "options": [{"id": "o1", "text": "A"}, {"id": "o2", "text": "B"}], "page_id": "p1"},
            {"id": "q2", "type": "radio", "options": [{"id": "o3", "text": "C"}, {"id": "o4", "text": "D"}], "page_id": "p1"},
        ]

    async def fake_build_action(*_args, **_kwargs):
        raise AssertionError("未知显隐逻辑不该生成答案")

    monkeypatch.setattr(qq_http, "_fetch_submit_source", fake_fetch)
    monkeypatch.setattr(qq_http, "build_answer_action", fake_build_action)

    with pytest.raises(RuntimeError, match="第2题逻辑规则未完整解析"):
        await qq_http.brush_qq_http(config, state)


@pytest.mark.asyncio
async def test_qq_http_runtime_skips_description_metadata(monkeypatch) -> None:
    config = ExecutionConfig(
        url="https://wj.qq.com/s2/123/hash/",
        survey_provider="qq",
    )
    config.questions_metadata = {
        5: SurveyQuestionMeta(
            num=5,
            title="模特A：无眼镜",
            provider="qq",
            provider_question_id="q5",
            provider_type="description",
            is_description=True,
        ),
        6: SurveyQuestionMeta(
            num=6,
            title="模特A评分",
            provider="qq",
            provider_question_id="q-13-7d39",
            provider_type="matrix_star",
            type_code="6",
            unsupported=True,
            unsupported_reason="当前版本暂不支持腾讯问卷矩阵量表题，请改用 v3.2.2 旧版本",
            option_texts=["1", "2"],
            row_texts=["专业"],
            options=2,
            rows=1,
        ),
    }
    state = ExecutionState(config=config)
    built_questions: list[int] = []
    captured: dict[str, object] = {}

    async def fake_fetch(*_args, **_kwargs):
        return "sess", {}, [
            {"id": "q5", "type": "description", "title": "模特A", "page_id": "p1"},
            {
                "id": "q-13-7d39",
                "type": "matrix_star",
                "options": [{"id": "o1", "text": "1"}, {"id": "o2", "text": "2"}],
                "sub_titles": [{"id": "g-101-ae7c", "text": "专业"}],
                "page_id": "p1",
            },
        ]

    async def fake_build_action(_driver, question, _ctx, **_kwargs):
        built_questions.append(int(question.num))
        return AnswerAction(
            question_num=int(question.num),
            question_id=str(question.provider_question_id),
            kind="matrix",
            matrix_indices=(0,),
            record_type="matrix",
        )

    async def fake_post(*_args, **kwargs):
        captured.update(kwargs)
        return _FakeResponse(payload={"code": "OK"})

    monkeypatch.setattr(qq_http, "_fetch_submit_source", fake_fetch)
    monkeypatch.setattr(qq_http, "build_answer_action", fake_build_action)
    monkeypatch.setattr(qq_http.http_client, "apost", fake_post)

    with pytest.raises(RuntimeError, match="腾讯问卷第6题暂不支持：当前版本暂不支持腾讯问卷矩阵量表题，请改用 v3.2.2 旧版本"):
        await qq_http.brush_qq_http(config, state)

    assert built_questions == []
    assert captured == {}


@pytest.mark.asyncio
async def test_qq_http_runtime_uses_latest_dynamic_ids_for_score_questions(monkeypatch) -> None:
    config = ExecutionConfig(
        url="https://wj.qq.com/s2/123/hash/",
        survey_provider="qq",
    )
    config.questions_metadata = {
        8: SurveyQuestionMeta(
            num=8,
            title="留校工作推荐度",
            provider="qq",
            provider_question_id="q-15-old",
            provider_type="nps",
            type_code="5",
            is_rating=True,
            unsupported=True,
            unsupported_reason="当前版本暂不支持腾讯问卷量表题，请改用 v3.2.2 旧版本",
            options=11,
            rating_max=11,
            option_texts=[str(index) for index in range(11)],
        ),
    }
    config.question_config_index_map = {8: ("score", 0)}
    config.scale_prob = [[0.0, 0.0, 0.0, 1.0] + [0.0] * 7]
    state = ExecutionState(config=config)
    captured: dict[str, object] = {}

    async def fake_fetch(*_args, **_kwargs):
        return "sess", {}, [
            {
                "id": "q-15-new",
                "type": "nps",
                "title": "留校工作推荐度",
                "star_begin_num": 0,
                "star_num": 11,
                "page_id": "p1",
                "page": 1,
            },
        ]

    async def fake_post(*_args, **kwargs):
        captured.update(kwargs)
        return _FakeResponse(payload={"code": "OK"})

    monkeypatch.setattr(qq_http, "_fetch_submit_source", fake_fetch)
    monkeypatch.setattr(qq_http.http_client, "apost", fake_post)

    with pytest.raises(RuntimeError, match="腾讯问卷第8题暂不支持：当前版本暂不支持腾讯问卷量表题，请改用 v3.2.2 旧版本"):
        await qq_http.brush_qq_http(config, state)

    assert captured == {}
