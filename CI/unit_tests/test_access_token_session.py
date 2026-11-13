from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from software.network.proxy.session import auth
from software.network.proxy.session.models import RandomIPAuthError, RandomIPSession


class _Settings:
    def __init__(self) -> None:
        self.values: dict[str, object] = {}

    def value(self, key: str):
        return self.values.get(key)

    def setValue(self, key: str, value: object) -> None:
        self.values[key] = value

    def remove(self, key: str) -> None:
        self.values.pop(key, None)

    def sync(self) -> None:
        return None


def _response(payload: object, status_code: int = 200):
    return SimpleNamespace(status_code=status_code, json=lambda: payload)


@pytest.fixture
def session_state(monkeypatch):
    settings = _Settings()
    token = {"value": ""}
    monkeypatch.setattr(auth, "_get_settings", lambda: settings)
    monkeypatch.setattr(auth.store, "load_access_token", lambda: token["value"])
    monkeypatch.setattr(
        auth.store,
        "persist_access_token",
        lambda value: token.__setitem__("value", value),
    )
    auth._session_loaded = True
    auth._session_revision = 0
    auth._authentication_future = None
    auth._session = RandomIPSession(device_id="legacy-device", user_id=19)
    yield settings, token
    auth._session = RandomIPSession()
    auth._session_loaded = False


@pytest.mark.asyncio
async def test_migrates_legacy_session_and_hides_token(session_state, monkeypatch):
    settings, token_storage = session_state
    calls = []

    async def post(url, **kwargs):
        calls.append((url, kwargs))
        return _response(
            {
                "user_id": 19,
                "remaining_quota": 4,
                "total_quota": 10,
                "access_token": "a" * 64,
                "token_type": "Bearer",
            }
        )

    monkeypatch.setattr(auth, "_apost_json", post)
    session = await auth.ensure_authenticated_session_async()

    assert session.access_token == "a" * 64
    assert session.used_quota == 6
    assert token_storage["value"] == "a" * 64
    assert all("access_token" not in key for key in settings.values)
    assert calls[0][1]["json_body"] == {"user_id": 19}
    assert calls[0][1]["headers"]["X-Device-ID"] == "legacy-device"
    assert auth.get_session_snapshot()["authenticated"] is True
    assert "access_token" not in auth.get_session_snapshot()

    auth._session_loaded = False
    auth._session = RandomIPSession()
    restored = await auth.ensure_authenticated_session_async()

    assert restored.user_id == 19
    assert restored.device_id == "legacy-device"
    assert (restored.remaining_quota, restored.total_quota, restored.used_quota) == (4, 10, 6)
    assert restored.access_token == "a" * 64
    assert len(calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "quota_payload",
    [
        {"total_quota": 10},
        {"remaining_quota": 4},
        {"remaining_quota": "invalid", "total_quota": 10},
        {"remaining_quota": 4, "total_quota": "invalid"},
    ],
)
async def test_migration_rejects_incomplete_server_quota_without_persisting_token(
    session_state, monkeypatch, quota_payload
):
    _settings, token_storage = session_state

    async def post(_url, **_kwargs):
        return _response(
            {
                "user_id": 19,
                "access_token": "a" * 64,
                "token_type": "Bearer",
                **quota_payload,
            }
        )

    monkeypatch.setattr(auth, "_apost_json", post)

    with pytest.raises(RandomIPAuthError, match="invalid_response:quota_missing"):
        await auth.ensure_authenticated_session_async()

    assert token_storage["value"] == ""
    assert auth.has_authenticated_session() is False


@pytest.mark.asyncio
async def test_missing_legacy_user_does_not_send_migration_request(session_state, monkeypatch):
    auth._session = RandomIPSession(device_id="device-without-account")
    monkeypatch.setattr(
        auth,
        "_apost_json",
        lambda *_args, **_kwargs: pytest.fail("no account must not be migrated"),
    )

    with pytest.raises(RandomIPAuthError, match="not_authenticated"):
        await auth.ensure_authenticated_session_async()


def test_secure_store_failure_is_not_treated_as_missing_token(session_state, monkeypatch):
    settings, _token_storage = session_state
    settings.values[auth._settings_key("device_id")] = "legacy-device"
    settings.values[auth._settings_key("user_id")] = 19

    def fail_load_access_token():
        raise RandomIPAuthError("session_store_unavailable")

    monkeypatch.setattr(auth.store, "load_access_token", fail_load_access_token)
    auth._session_loaded = False

    with pytest.raises(RandomIPAuthError, match="session_store_unavailable"):
        auth._ensure_loaded()


def test_access_token_readback_failure_rolls_back_authentication(session_state, monkeypatch):
    settings, _token_storage = session_state

    def fail_persist(_token):
        raise RandomIPAuthError("session_persist_failed:access_token")

    monkeypatch.setattr(auth.store, "persist_access_token", fail_persist)
    candidate = RandomIPSession(
        device_id="legacy-device",
        user_id=19,
        access_token="d" * 64,
        remaining_quota=4,
        total_quota=10,
        used_quota=6,
        quota_known=True,
    )

    with pytest.raises(RandomIPAuthError, match="session_persist_failed"):
        auth._set_session(candidate, verify_auth_persistence=True)

    assert auth.has_authenticated_session() is False
    assert auth.get_session_snapshot()["user_id"] == 19
    assert auth._settings_key("user_id") in settings.values


@pytest.mark.asyncio
async def test_concurrent_migration_uses_one_request(session_state, monkeypatch):
    started = asyncio.Event()
    finish = asyncio.Event()
    requests = 0

    async def post(_url, **_kwargs):
        nonlocal requests
        requests += 1
        started.set()
        await finish.wait()
        return _response(
            {
                "user_id": 19,
                "remaining_quota": 4,
                "total_quota": 10,
                "access_token": "b" * 64,
                "token_type": "Bearer",
            }
        )

    monkeypatch.setattr(auth, "_apost_json", post)
    first = asyncio.create_task(auth.ensure_authenticated_session_async())
    await started.wait()
    second = asyncio.create_task(auth.ensure_authenticated_session_async())
    finish.set()

    await asyncio.gather(first, second)
    assert requests == 1


def test_invalid_token_only_clears_matching_session(session_state):
    session = RandomIPSession(device_id="device", user_id=19, access_token="c" * 64)
    auth._set_session(session)

    error = auth._response_error(_response({"detail": "invalid_access_token"}, 401), session)

    assert isinstance(error, RandomIPAuthError)
    assert auth.get_session_snapshot()["user_id"] == 19
    assert auth.has_authenticated_session() is False


def test_quota_parser_preserves_server_remaining_quota():
    session = auth._parse_session_payload(
        {
            "user_id": 19,
            "remaining_quota": 4,
            "total_quota": 10,
            "used_quota": 3,
        },
        device_id="device",
    )

    assert session.remaining_quota == 4
    assert session.used_quota == 3


def test_zero_quota_response_is_known():
    session = auth._parse_session_payload(
        {"user_id": 19, "remaining_quota": 0, "total_quota": 0},
        device_id="device",
    )

    assert session.quota_known is True
    assert auth.is_quota_exhausted(
        {"authenticated": True, "remaining_quota": 0, "quota_known": True}
    )
