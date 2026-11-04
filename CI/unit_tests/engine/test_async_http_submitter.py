from __future__ import annotations

import pytest

import software.core.engine.async_http_submitter as http_submitter
from software.core.task import ExecutionConfig, ExecutionState
from software.providers.contracts import (
    ProviderErrorCategory,
    ProviderFailure,
    ProviderSubmissionResult,
)


@pytest.mark.asyncio
async def test_submit_preserves_provider_failure_category_and_exception(
    monkeypatch, caplog
) -> None:
    config = ExecutionConfig(survey_provider="wjx")
    exception = RuntimeError("代理不可用")
    failure = ProviderFailure(
        provider="wjx",
        category=ProviderErrorCategory.UNAVAILABLE,
        message=str(exception),
        exception=exception,
    )

    async def return_failure(*_args, **_kwargs):
        return ProviderSubmissionResult(provider="wjx", submitted=False, failure=failure)

    monkeypatch.setattr(http_submitter, "fill_survey_http", return_failure)
    submitter = http_submitter.AsyncHttpSubmitter(
        config=config,
        state=ExecutionState(config=config),
        slot_label="Slot-1",
    )

    with pytest.raises(RuntimeError) as raised:
        await submitter.submit(
            stop_signal=object(),
            proxy_address=None,
            user_agent=None,
        )

    assert raised.value is exception
    assert raised.value.__notes__ == ["provider=wjx; category=unavailable"]
    assert any("category=unavailable" in record.message for record in caplog.records)
