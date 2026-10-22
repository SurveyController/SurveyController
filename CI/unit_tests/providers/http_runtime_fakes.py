from __future__ import annotations


class _FakeResponse:
    def __init__(self, *, text: str = "success", payload=None) -> None:
        self.text = text
        self._payload = payload if payload is not None else {"code": "OK"}

    def raise_for_status(self) -> None:
        return None

    def json(self):
        return self._payload


def _async_result(value):
    async def _runner(*_args, **_kwargs):
        return value

    return _runner
