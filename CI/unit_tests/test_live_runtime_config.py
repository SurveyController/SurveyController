from types import SimpleNamespace

from CI.live_tests import run_async_engine_once
from CI.live_tests.test_live_runtime_regression import (
    DEFAULT_LIVE_SURVEY_CASES,
    LIVE_URL_ENV,
    _resolve_live_survey_cases,
)
from software.providers.contracts import SurveyQuestionMeta


def test_resolve_live_survey_cases_uses_hardcoded_defaults(monkeypatch):
    monkeypatch.delenv(LIVE_URL_ENV, raising=False)

    cases = _resolve_live_survey_cases()

    assert cases == list(DEFAULT_LIVE_SURVEY_CASES)


def test_resolve_live_survey_cases_accepts_single_env_url(monkeypatch):
    monkeypatch.setenv(LIVE_URL_ENV, "https://www.wjx.cn/vm/demo.aspx")

    cases = _resolve_live_survey_cases()

    assert len(cases) == 1
    assert cases[0].url == "https://www.wjx.cn/vm/demo.aspx"


def test_build_live_test_config_uses_defaults_and_parsed_questions(monkeypatch):
    definition = SimpleNamespace(
        provider="wjx",
        title="演示问卷",
        questions=[
            SurveyQuestionMeta(num=1, title="单选题", type_code="3", options=2),
        ],
    )
    monkeypatch.setattr(run_async_engine_once, "parse_survey_sync", lambda _url: definition)

    config = run_async_engine_once._build_live_test_config(
        "https://www.wjx.cn/vm/demo.aspx",
        headless=True,
    )

    assert config.url == "https://www.wjx.cn/vm/demo.aspx"
    assert config.target == 1
    assert config.threads == 1
    assert config.random_ip_enabled is False
    assert config.random_ua_enabled is False
    assert config.question_entries
