from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from software.network.config import AUTH_SESSION_ENDPOINT
from software.network.proxy.session import auth
from software.network.proxy.session.models import RandomIPAuthError, RandomIPSession


@pytest.fixture
def session_settings(monkeypatch):
    values = {}
    settings = SimpleNamespace(
        setValue=lambda key, value: values.__setitem__(key, value),
        value=values.get,
        remove=lambda key: values.pop(key, None),
        sync=lambda: None,
    )
    monkeypatch.setattr(auth, "_get_settings", lambda: settings)
    monkeypatch.setattr(auth.store, "persist_access_token", lambda _token: None)
    monkeypatch.setattr(auth, "_session_loaded", True)
    monkeypatch.setattr(auth, "_session_revision", 0)
    monkeypatch.setattr(
        auth,
        "_session",
        RandomIPSession(
            device_id="unit-device",
            user_id=17,
            access_token="t" * 64,
            remaining_quota=1,
            total_quota=1,
            used_quota=0,
            quota_known=True,
        ),
    )
    return settings


def response(payload):
    return SimpleNamespace(status_code=200, json=lambda: payload)


@pytest.mark.asyncio
async def test_late_sync_does_not_restore_quota_consumed_by_extraction(
    session_settings, monkeypatch
):
    sync_started = asyncio.Event()
    finish_sync = asyncio.Event()

    async def post(url, **_kwargs):
        if url == AUTH_SESSION_ENDPOINT:
            sync_started.set()
            await finish_sync.wait()
            return response({"user_id": 17, "total_quota": 1, "used_quota": 0})
        return response(
            {
                "host": "1.1.1.1",
                "port": 8000,
                "account": "unit",
                "password": "unit",
                "total_quota": 1,
                "used_quota": 1,
            }
        )

    monkeypatch.setattr(auth, "_apost_json", post)
    monkeypatch.setattr(auth, "_aget_json", post)
    sync_task = asyncio.create_task(auth.sync_quota_snapshot_from_server_async(emit_logs=False))
    await sync_started.wait()
    await auth.extract_proxy_async(minute=1, pool="quality", area=None)
    assert auth.is_quota_exhausted()
    finish_sync.set()
    snapshot = await sync_task

    assert snapshot["used_quota"] == 1
    assert snapshot["remaining_quota"] == 0
    assert auth.is_quota_exhausted()


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["sync", "extract", "extract_batch", "redeem"])
@pytest.mark.parametrize("replacement_user_id", [0, 17, 23])
async def test_old_response_does_not_restore_or_overwrite_changed_session(
    session_settings, monkeypatch, operation, replacement_user_id
):
    request_started = asyncio.Event()
    finish_request = asyncio.Event()

    async def post(_url, **_kwargs):
        request_started.set()
        await finish_request.wait()
        return response(
            {
                "user_id": 17,
                "total_quota": 10,
                "used_quota": 0,
                "host": "1.1.1.1",
                "port": 8000,
                "account": "unit",
                "password": "unit",
                "redeemed": True,
                "items": [
                    {
                        "host": "1.1.1.1",
                        "port": 8000,
                        "account": "unit",
                        "password": "unit",
                    }
                ],
            }
        )

    monkeypatch.setattr(auth, "_apost_json", post)
    monkeypatch.setattr(auth, "_aget_json", post)
    operations = {
        "sync": lambda: auth.sync_quota_snapshot_from_server_async(emit_logs=False),
        "extract": lambda: auth.extract_proxy_async(minute=1, pool="quality", area=None),
        "extract_batch": lambda: auth.extract_proxy_async(
            minute=1, pool="quality", area=None, num=2
        ),
        "redeem": lambda: auth.redeem_card_async("a" * 16),
    }
    pending = asyncio.create_task(operations[operation]())
    await request_started.wait()
    if replacement_user_id:
        auth._set_session(
            RandomIPSession(
                device_id="unit-device",
                user_id=replacement_user_id,
                access_token="r" * 64,
                remaining_quota=3,
                total_quota=5,
                used_quota=2,
                quota_known=True,
            )
        )
    else:
        auth.clear_session(reason="unit")
    expected = auth.get_session_snapshot()
    finish_request.set()
    if replacement_user_id:
        await pending
    else:
        with pytest.raises(RandomIPAuthError, match="session_changed"):
            await pending

    assert auth.get_session_snapshot() == expected
