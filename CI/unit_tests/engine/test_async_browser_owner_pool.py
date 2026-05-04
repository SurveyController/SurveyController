import asyncio

from software.network.browser.async_owner_pool import _route_runtime_resource


class _FakeRequest:
    def __init__(self, *, url: str, resource_type: str = "xhr") -> None:
        self.url = url
        self.resource_type = resource_type


class _FakeRoute:
    def __init__(self, *, has_fallback: bool = True) -> None:
        self.actions: list[str] = []
        if not has_fallback:
            self.fallback = None

    async def abort(self) -> None:
        self.actions.append("abort")

    async def continue_(self) -> None:
        self.actions.append("continue")

    async def fallback(self) -> None:
        self.actions.append("fallback")


def test_processjq_request_falls_through_to_specific_route() -> None:
    async def _exercise() -> list[str]:
        route = _FakeRoute()

        await _route_runtime_resource(
            route,
            _FakeRequest(url="https://www.wjx.cn/joinnew/processjq.ashx?x=1", resource_type="xhr"),
        )
        return route.actions

    assert asyncio.run(_exercise()) == ["fallback"]


def test_runtime_route_aborts_heavy_resources() -> None:
    async def _exercise() -> list[str]:
        route = _FakeRoute()

        await _route_runtime_resource(
            route,
            _FakeRequest(url="https://example.test/logo.png", resource_type="image"),
        )
        return route.actions

    assert asyncio.run(_exercise()) == ["abort"]
