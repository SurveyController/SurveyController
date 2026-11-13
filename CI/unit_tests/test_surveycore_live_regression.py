from __future__ import annotations

from types import SimpleNamespace

import pytest

from CI.live_tests import surveycore_regression as regression


@pytest.mark.parametrize("failed_provider", [None, "qq"])
async def test_live_regression_submits_once_per_survey_and_fails_closed(
    monkeypatch, failed_provider
) -> None:
    parsed = []
    submitted = []

    class Client:
        def __init__(self, http):
            self.http = http

        async def parse(self, url):
            provider = next(name for name, value in regression.SURVEYS.items() if value == url)
            parsed.append(provider)
            return SimpleNamespace(provider=provider, questions=(object(),))

        async def submit(self, request):
            submitted.append(request)
            return SimpleNamespace(
                success=request.config.provider != failed_provider,
                error="submission rejected",
            )

    monkeypatch.setattr(regression, "SurveyClient", Client)

    assert await regression.run_regression() == int(failed_provider is not None)
    assert sorted(parsed) == sorted(regression.SURVEYS)
    assert len(submitted) == len(regression.SURVEYS)
    assert {request.config.provider for request in submitted} == set(regression.SURVEYS)
    assert all(request.config.target == request.config.concurrency == 1 for request in submitted)
    assert all(request.survey.provider == request.config.provider for request in submitted)


async def test_parse_failure_prevents_submission_and_fails_regression(monkeypatch) -> None:
    class Client:
        def __init__(self, http):
            self.http = http

        async def parse(self, url):
            raise RuntimeError("unparseable survey")

        async def submit(self, request):
            pytest.fail("A parse failure must not submit a response")

    monkeypatch.setattr(regression, "SurveyClient", Client)

    assert await regression.run_regression() == 1
