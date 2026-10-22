from __future__ import annotations

import pytest

from software.providers.contracts import ProviderSubmissionRejectedError
from tencent.provider import http_runtime as qq_http


def test_qq_submit_payload_classifier_and_message() -> None:
    assert qq_http.classify_qq_submit_payload({"code": "OK"}) == qq_http.QqSubmitResult.SUCCESS
    assert qq_http.classify_qq_submit_payload({"code": "0"}) == qq_http.QqSubmitResult.SUCCESS
    assert qq_http.classify_qq_submit_payload({"code": "NEED_LOGIN", "message": "需要登录"}) == qq_http.QqSubmitResult.FAILED

    with pytest.raises(ProviderSubmissionRejectedError, match="需要登录") as rejected:
        qq_http._raise_qq_submit_failed({"code": "NEED_LOGIN", "message": "需要登录"})
    assert isinstance(rejected.value, RuntimeError)
