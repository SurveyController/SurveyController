from __future__ import annotations

import asyncio
import traceback

import httpx
from surveycore import RunConfig, SubmissionRequest, SurveyClient

from CI.python_checks.common import configure_console_encoding

SURVEYS = {
    "wjx": "https://v.wjx.cn/vm/ei3sVrE.aspx",
    "qq": "https://wj.qq.com/s2/26070328/fa89/",
    "credamo": "https://www.credamo.com/s/A73QR3ano",
}


async def run_case(provider: str, url: str) -> None:
    async with asyncio.timeout(240), httpx.AsyncClient(timeout=60, follow_redirects=True) as http:
        client = SurveyClient(http)
        survey = await client.parse(url)
        if survey.provider != provider or not survey.questions:
            raise RuntimeError(f"{provider}: 解析结果平台不匹配或没有题目")
        print(f"{provider}: parsed {len(survey.questions)} questions", flush=True)
        config = RunConfig(
            url=url,
            provider=provider,
            target=1,
            concurrency=1,
            answer_duration=(0, 0),
            submit_interval=(0, 0),
        )
        result = await client.submit(SubmissionRequest(config=config, survey=survey))
        if not result.success:
            raise RuntimeError(f"{provider}: {result.error}")
        print(f"[PASS] {provider}: submitted 1 response", flush=True)


async def run_regression() -> int:
    results = await asyncio.gather(
        *(run_case(provider, url) for provider, url in SURVEYS.items()),
        return_exceptions=True,
    )
    failed = False
    for provider, result in zip(SURVEYS, results, strict=True):
        if isinstance(result, BaseException):
            failed = True
            print(f"[FAIL] {provider}", flush=True)
            traceback.print_exception(result)
    return int(failed)


def main() -> int:
    configure_console_encoding()
    return asyncio.run(run_regression())


if __name__ == "__main__":
    raise SystemExit(main())
