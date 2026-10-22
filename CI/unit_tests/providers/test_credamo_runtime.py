from __future__ import annotations

from types import SimpleNamespace

import pytest

from software.core.task import ExecutionConfig, ExecutionState
from surveycore.credamo.provider import answering_builders as credamo_builders
from surveycore.credamo.provider import http_runtime as core_credamo_http
from surveycore.providers.contracts import SurveyQuestionMeta
from credamo.provider import http_runtime as credamo_http

from .http_runtime_fakes import _FakeResponse


@pytest.mark.asyncio
async def test_credamo_save_keeps_encoded_answer_token_verbatim() -> None:
    captured: dict[str, object] = {}

    class FakeSession:
        async def post(self, url, **kwargs):
            captured["url"] = url
            captured.update(kwargs)
            return _FakeResponse(payload={"success": True, "data": {"answerId": 1}})

    await credamo_http._save_answers(
        FakeSession(),
        origin="https://www.credamo.com",
        short_url="A73QR3ano",
        init_data=credamo_http._CredamoAnswerInit("abc%2Bdef%2Fghi%3D", 1710000000000, "device-id"),
        body={"answerQstList": [], "shortUrl": "A73QR3ano"},
        user_agent="UA",
    )

    assert "answerToken=abc%2Bdef%2Fghi%3D" in str(captured["url"])
    assert "%252B" not in str(captured["url"])
    assert captured["headers"]["Content-Type"] == "application/json"


@pytest.mark.asyncio
async def test_credamo_http_runtime_uses_proxy_and_posts_json(monkeypatch) -> None:
    config = ExecutionConfig(
        url="https://www.credamo.com/s/A73QR3ano",
        survey_provider="credamo",
        answer_duration_range_seconds=(70, 70),
    )
    config.questions_metadata = {
        1: SurveyQuestionMeta(num=1, title="Q1", provider="credamo", options=2, type_code="3"),
    }
    config.question_config_index_map = {1: ("single", 0)}
    config.single_prob = [[1.0, 0.0]]
    state = ExecutionState(config=config)
    captured = SimpleNamespace(session_proxies=[], post_kwargs=None)

    class FakeSession:
        def __init__(self, proxy_address=None):
            self.proxy_address = proxy_address

        async def __aenter__(self):
            captured.session_proxies.append(self.proxy_address)
            return self

        async def __aexit__(self, *_args):
            return None

    async def fake_fetch(_session, *_args, headers, **_kwargs):
        assert "signature" in headers
        return {
            "blocks": [
                {
                    "blockElements": [
                        {
                            "qstId": "101",
                            "qstNo": "Q1",
                            "questionId": "q1",
                            "questionType": 2,
                            "selector": 1,
                            "choices": [{"choiceId": "11"}, {"choiceId": "12"}],
                        }
                    ]
                }
            ]
        }

    async def fake_init(_session, *_args, **_kwargs):
        return credamo_http._CredamoAnswerInit("answer-token", 1710000000000, "device-id")

    async def fake_save(_session, **kwargs):
        captured.post_kwargs = kwargs
        return {}

    monkeypatch.setattr(credamo_http, "_CredamoHttpSession", FakeSession)
    monkeypatch.setattr(credamo_http, "_fetch_detail", fake_fetch)
    monkeypatch.setattr(credamo_http, "_init_answer", fake_init)
    monkeypatch.setattr(credamo_http, "_save_answers", fake_save)
    monkeypatch.setattr(credamo_builders, "weighted_index", lambda _probs: 0)
    monkeypatch.setattr(core_credamo_http, "sample_answer_duration_seconds", lambda *_args, **_kwargs: 70.0)

    ok = await credamo_http.brush_credamo_http(
        config,
        state,
        proxy_address="http://1.1.1.1:80",
        user_agent="UA",
    )

    assert ok is True
    assert captured.session_proxies == [None, None, "http://1.1.1.1:80"]
    assert captured.post_kwargs["user_agent"] == "UA"
    assert captured.post_kwargs["init_data"].answer_token == "answer-token"
    assert captured.post_kwargs["init_data"].time_code == "device-id"
    assert captured.post_kwargs["body"]["shortUrl"] == "A73QR3ano"
    assert "answerToken" not in captured.post_kwargs["body"]
    assert captured.post_kwargs["body"]["answerStartTime"] == 1710000000000
    assert captured.post_kwargs["body"]["answerEndTime"] == 1710000070000
    assert "answerQstEeg" not in captured.post_kwargs["body"]["answerQstList"][0]
    assert captured.post_kwargs["body"]["answerQstList"][0]["answerTime"] == 70000
    assert captured.post_kwargs["body"]["answerQstList"][0]["answerQstChoice"]["choiceId"] == 11


def test_credamo_samples_answer_start_time_inside_datetime_window(monkeypatch) -> None:
    config = ExecutionConfig(
        survey_provider="credamo",
        answer_datetime_window_ms=(1710000000000, 1710003600000),
    )
    monkeypatch.setattr(core_credamo_http.random, "randint", lambda start, end: start + 1234)

    started_at = credamo_http._sample_answer_start_time_ms(
        config,
        init_started_at_ms=1700000000000,
        duration_seconds=70.0,
    )

    assert started_at == 1710000001234


def test_credamo_datetime_window_falls_back_to_init_time_when_unconfigured() -> None:
    config = ExecutionConfig(survey_provider="credamo")

    started_at = credamo_http._sample_answer_start_time_ms(
        config,
        init_started_at_ms=1700000000000,
        duration_seconds=70.0,
    )

    assert started_at == 1700000000000
