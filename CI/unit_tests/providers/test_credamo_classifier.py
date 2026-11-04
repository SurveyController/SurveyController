from __future__ import annotations

from types import SimpleNamespace

import pytest

from software.providers.contracts import ProviderSubmissionRejectedError
from credamo.provider import http_runtime as credamo_http


def test_credamo_api_payload_classifier() -> None:
    assert (
        credamo_http.classify_credamo_api_payload({"success": True})
        == credamo_http.CredamoSubmitResult.SUCCESS
    )
    assert (
        credamo_http.classify_credamo_api_payload({"data": {}})
        == credamo_http.CredamoSubmitResult.SUCCESS
    )
    assert (
        credamo_http.classify_credamo_api_payload({"success": False})
        == credamo_http.CredamoSubmitResult.FAILED
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("is_error", [False, True])
async def test_credamo_submit_failure_uses_submission_rejected_contract(is_error: bool) -> None:
    response = SimpleNamespace(
        json=lambda: {"success": False, "message": "答案格式无效"},
        is_error=is_error,
        raise_for_status=lambda: None,
    )

    class FakeSession:
        async def post(self, *_args, **_kwargs):
            return response

    init_data = SimpleNamespace(answer_token="token", time_code="time")

    with pytest.raises(
        ProviderSubmissionRejectedError, match="见数提交失败：答案格式无效"
    ) as rejected:
        await credamo_http._save_answers(
            FakeSession(),
            origin="https://www.credamo.com",
            short_url="demoano",
            init_data=init_data,
            body={},
            user_agent="UA",
        )

    assert isinstance(rejected.value, RuntimeError)
