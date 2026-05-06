from __future__ import annotations

import asyncio

import pytest


@pytest.fixture
async def async_loop_identity() -> asyncio.AbstractEventLoop:
    await asyncio.sleep(0)
    return asyncio.get_running_loop()


async def test_async_fixture_shares_running_loop(async_loop_identity: asyncio.AbstractEventLoop) -> None:
    assert async_loop_identity is asyncio.get_running_loop()
