from __future__ import annotations

import asyncio

import pytest

from software.network.proxy.session import auth
from software.network.proxy.session import client
from software.network.proxy.session.models import RandomIPAuthError, RandomIPSession


@pytest.fixture(autouse=True)
def isolate_random_ip_auth_storage(monkeypatch: pytest.MonkeyPatch):
    settings = _Settings()
    token_storage = {"value": ""}
    activation_storage = {"value": ""}

    monkeypatch.setattr(auth, "_get_settings", lambda: settings)
    monkeypatch.setattr(auth.store, "load_access_token", lambda: token_storage["value"])
    monkeypatch.setattr(auth.store, "load_activation_token", lambda: activation_storage["value"])
    monkeypatch.setattr(
        auth.store,
        "persist_activation_token",
        lambda value: activation_storage.__setitem__("value", value),
    )
    monkeypatch.setattr(
        auth.store,
        "persist_access_token",
        lambda value: token_storage.__setitem__("value", value),
    )
    auth._session_loaded = False
    auth._session = RandomIPSession()
    auth._session_revision = 0
    auth._authentication_future = None
    yield settings
    auth._session_loaded = False
    auth._session = RandomIPSession()
    auth._session_revision = 0
    auth._authentication_future = None


class _Settings:
    def __init__(self) -> None:
        self.values: dict[str, object] = {}
        self.removed: list[str] = []
        self.synced = 0

    def value(self, key: str):
        return self.values.get(key)

    def setValue(self, key: str, value: object) -> None:
        self.values[key] = value

    def remove(self, key: str) -> None:
        self.removed.append(key)
        self.values.pop(key, None)

    def sync(self) -> None:
        self.synced += 1


class _Response:
    def __init__(self, payload: object, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload


def _reset_auth_state(session: RandomIPSession | None = None) -> None:
    auth._session_loaded = True
    auth._session = session or RandomIPSession(device_id="device-1")


@pytest.mark.parametrize(
    ("detail", "expected"),
    [
        ("invalid_access_token", "登录已失效"),
        ("session_persist_failed:settings.user_id", "没能安全保存"),
        ("device_banned", "当前设备已被封禁"),
        ("user_expired", "随机IP账号已过期"),
        ("invalid_user_id", "用户ID无效"),
        ("minute_not_supported_for_idiot", "限时福利代理源只支持"),
        ("insufficient_quota", "已达到上限"),
        ("network_error: timeout", "网络请求失败：timeout"),
        ("invalid_response:user_id_invalid", "无效的随机IP用户ID"),
        ("invalid_response:bad", "服务端返回格式异常"),
        ("http_503", "503"),
        ("unmapped_detail", "unmapped_detail"),
    ],
)
def test_format_random_ip_error_maps_backend_details(detail: str, expected: str) -> None:
    exc = RandomIPAuthError(detail, retry_after_seconds=9)
    assert expected in auth.format_random_ip_error(exc)


@pytest.mark.asyncio
@pytest.mark.parametrize("stale_user_id", [0, 38852])
async def test_first_redemption_activates_without_an_existing_account(monkeypatch, stale_user_id):
    _reset_auth_state(RandomIPSession(device_id="new-device", user_id=stale_user_id))
    requests = []

    async def post(url, *, json_body, headers):
        requests.append((url, json_body, headers))
        if url == auth.AUTH_TRIAL_ENDPOINT:
            return _Response({"detail": "invalid_user_id"}, 401)
        assert url == auth.CARD_REDEEM_ENDPOINT
        token = json_body["activation_token"]
        assert len(token) == 64
        assert auth.store.load_activation_token() == token
        assert headers["X-Device-ID"] == "new-device"
        assert "Authorization" not in headers
        return _Response(
            {
                "user_id": 73,
                "access_token": token,
                "token_type": "Bearer",
                "redeemed": True,
                "card_quota": 400,
                "remaining_quota": 400,
                "total_quota": 400,
                "detail": "redeem_card_redeemed",
            }
        )

    monkeypatch.setattr(auth, "_apost_json", post)
    result = await auth.redeem_card_async("a" * 16)
    assert result["redeemed"] is True
    assert result["remaining_quota"] == 400
    assert auth.get_session_snapshot()["user_id"] == 73
    assert auth.has_authenticated_session()
    assert auth.store.load_access_token() == auth._session.access_token
    assert auth.store.load_activation_token() == ""
    assert len(requests) == (2 if stale_user_id else 1)


@pytest.mark.asyncio
async def test_activation_recovers_after_lost_response_and_client_restart(monkeypatch):
    _reset_auth_state(RandomIPSession(device_id="new-device"))
    attempted_tokens = []

    async def post(_url, *, json_body, **_kwargs):
        token = json_body["activation_token"]
        attempted_tokens.append(token)
        if len(attempted_tokens) == 1:
            raise RandomIPAuthError("network_error:response_lost")
        return _Response(
            {
                "user_id": 73,
                "access_token": token,
                "token_type": "Bearer",
                "redeemed": False,
                "card_quota": 400,
                "remaining_quota": 400,
                "total_quota": 400,
                "detail": "redeem_card_redeemed",
            }
        )

    monkeypatch.setattr(auth, "_apost_json", post)
    with pytest.raises(RandomIPAuthError, match="response_lost"):
        await auth.redeem_card_async("a" * 16)
    _reset_auth_state(RandomIPSession(device_id="new-device"))
    recovered = await auth.redeem_card_async("a" * 16)
    assert recovered["redeemed"] is False
    assert attempted_tokens[0] == attempted_tokens[1]
    assert auth.has_authenticated_session()


@pytest.mark.asyncio
async def test_activation_does_not_spend_a_card_before_recovery_credential_is_saved(monkeypatch):
    _reset_auth_state(RandomIPSession(device_id="new-device"))

    def fail_save(_token):
        raise RandomIPAuthError("session_persist_failed:token")

    async def post(*_args, **_kwargs):
        pytest.fail("redemption must not reach the server without a saved recovery credential")

    monkeypatch.setattr(auth.store, "persist_activation_token", fail_save)
    monkeypatch.setattr(auth, "_apost_json", post)
    with pytest.raises(RandomIPAuthError, match="session_persist_failed"):
        await auth.redeem_card_async("a" * 16)
    assert not auth.has_authenticated_session()


@pytest.mark.asyncio
async def test_activation_keeps_recovery_credential_when_session_save_fails(monkeypatch):
    _reset_auth_state(RandomIPSession(device_id="new-device"))
    tokens = []

    async def post(_url, *, json_body, **_kwargs):
        token = json_body["activation_token"]
        tokens.append(token)
        return _Response(
            {
                "user_id": 73,
                "access_token": token,
                "token_type": "Bearer",
                "redeemed": len(tokens) == 1,
                "card_quota": 400,
                "remaining_quota": 400,
                "total_quota": 400,
                "detail": "redeem_card_redeemed",
            }
        )

    original_set = auth._set_session

    def fail_save(*_args, **_kwargs):
        raise RandomIPAuthError("session_persist_failed:settings.user_id")

    monkeypatch.setattr(auth, "_apost_json", post)
    monkeypatch.setattr(auth, "_set_session", fail_save)
    with pytest.raises(RandomIPAuthError, match="session_persist_failed"):
        await auth.redeem_card_async("a" * 16)
    assert auth.store.load_activation_token() == tokens[0]
    monkeypatch.setattr(auth, "_set_session", original_set)
    assert (await auth.redeem_card_async("a" * 16))["redeemed"] is False
    assert tokens[0] == tokens[1]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "detail", ["device_banned", "user_banned", "device_not_bound", "network_error:timeout"]
)
async def test_old_account_errors_do_not_fall_back_to_new_activation(monkeypatch, detail):
    _reset_auth_state(RandomIPSession(device_id="old-device", user_id=38852))

    async def post(url, **_kwargs):
        assert url == auth.AUTH_TRIAL_ENDPOINT
        raise RandomIPAuthError(detail)

    monkeypatch.setattr(auth, "_apost_json", post)
    with pytest.raises(RandomIPAuthError, match=detail):
        await auth.redeem_card_async("a" * 16)
    assert auth.get_session_snapshot()["user_id"] == 38852


@pytest.mark.asyncio
async def test_late_activation_response_cannot_replace_a_switched_account(monkeypatch):
    _reset_auth_state(RandomIPSession(device_id="new-device"))
    started = asyncio.Event()
    finish = asyncio.Event()

    async def post(_url, *, json_body, **_kwargs):
        started.set()
        await finish.wait()
        return _Response(
            {
                "user_id": 73,
                "access_token": json_body["activation_token"],
                "token_type": "Bearer",
                "redeemed": True,
                "card_quota": 400,
                "remaining_quota": 400,
                "total_quota": 400,
            }
        )

    monkeypatch.setattr(auth, "_apost_json", post)
    pending = asyncio.create_task(auth.redeem_card_async("a" * 16))
    await started.wait()
    auth._set_session(
        RandomIPSession(
            device_id="other-device",
            user_id=19,
            access_token="b" * 64,
            remaining_quota=10,
            total_quota=10,
            quota_known=True,
        )
    )
    expected = auth.get_session_snapshot()
    finish.set()
    with pytest.raises(RandomIPAuthError, match="session_changed"):
        await pending
    assert auth.get_session_snapshot() == expected
    assert auth.store.load_activation_token()


class RandomIPSessionAuthTests:
    def test_ensure_loaded_builds_stable_device_id_and_reads_quota_from_settings(
        self, patch_attrs
    ) -> None:
        settings = _Settings()
        settings.values = {
            auth._settings_key("user_id"): "12",
            auth._settings_key("remaining_quota"): "3",
            auth._settings_key("total_quota"): "10",
            auth._settings_key("used_quota"): "7",
            auth._settings_key("quota_known"): True,
        }
        auth._session_loaded = False
        patch_attrs(
            (auth, "_get_settings", lambda: settings),
            (auth, "build_stable_device_id", lambda: "sc-v2-generated-device"),
        )

        auth._ensure_loaded()

        assert auth._session.device_id == "sc-v2-generated-device"
        assert auth._session.user_id == 12
        assert auth._session.remaining_quota == 3.0
        assert auth._session.total_quota == 10.0
        assert auth._session.used_quota == 7.0
        assert settings.values[auth._settings_key("device_id")] == "sc-v2-generated-device"

    def test_ensure_loaded_keeps_existing_settings_device_id(self, patch_attrs) -> None:
        settings = _Settings()
        settings.values = {
            auth._settings_key("device_id"): "settings-device",
            auth._settings_key("user_id"): "38852",
        }
        auth._session_loaded = False
        patch_attrs(
            (auth, "_get_settings", lambda: settings),
            (auth, "build_stable_device_id", lambda: "sc-v2-should-not-be-used"),
        )

        auth._ensure_loaded()

        assert auth._session.device_id == "settings-device"
        assert auth._session.user_id == 38852

    def test_set_session_persists_normalized_quota_and_snapshot(self, patch_attrs) -> None:
        settings = _Settings()
        _reset_auth_state(RandomIPSession(device_id="old-device"))
        patch_attrs(
            (auth, "_get_settings", lambda: settings),
        )

        session = auth._set_session(
            RandomIPSession(
                device_id="device-2",
                user_id=9,
                access_token="a" * 64,
                remaining_quota=2,
                total_quota=5,
                used_quota=3,
                quota_known=True,
            ),
            verify_auth_persistence=True,
        )

        assert session.user_id == 9
        assert settings.values[auth._settings_key("user_id")] == 9
        assert settings.values[auth._settings_key("remaining_quota")] == "2"
        assert settings.values[auth._settings_key("device_id")] == "device-2"
        snapshot = auth.get_session_snapshot()
        assert snapshot["authenticated"] is True
        assert snapshot["remaining_quota"] == 2.0

    def test_set_session_persists_device_id_in_settings(self, patch_attrs) -> None:
        settings = _Settings()
        _reset_auth_state(RandomIPSession(device_id="old-device"))
        patch_attrs(
            (auth, "_get_settings", lambda: settings),
        )

        session = auth._set_session(
            RandomIPSession(
                device_id="device-linux",
                user_id=9,
                remaining_quota=2,
                total_quota=5,
                used_quota=3,
                quota_known=True,
            ),
            verify_auth_persistence=True,
        )

        assert session.device_id == "device-linux"
        assert settings.values[auth._settings_key("device_id")] == "device-linux"
        assert settings.synced == 1

    def test_clear_session_preserves_device_id_and_removes_quota_fields(self, patch_attrs) -> None:
        settings = _Settings()
        _reset_auth_state(
            RandomIPSession(
                device_id="device-3", user_id=10, total_quota=1, used_quota=1, quota_known=True
            )
        )
        patch_attrs((auth, "_get_settings", lambda: settings))

        auth.clear_session(reason="unit")

        assert auth._session == RandomIPSession(device_id="device-3")
        assert auth._settings_key("user_id") in settings.removed
        assert settings.synced == 1

    def test_parse_session_payload_requires_user_id_and_complete_server_quota(self) -> None:
        with pytest.raises(RandomIPAuthError, match="user_id_missing"):
            auth._parse_session_payload({}, device_id="device-4")
        with pytest.raises(RandomIPAuthError, match="user_id_invalid"):
            auth._parse_session_payload({"user_id": 0}, device_id="device-4")

        with pytest.raises(RandomIPAuthError, match="invalid_response:quota_missing"):
            auth._parse_session_payload(
                {"user_id": "15", "used_quota": 4},
                device_id="device-4",
                fallback_session=RandomIPSession(
                    user_id=15,
                    remaining_quota=8,
                    total_quota=10,
                    used_quota=2,
                    quota_known=True,
                ),
            )

        session = auth._parse_session_payload(
            {"user_id": "15", "remaining_quota": 6, "total_quota": 10, "used_quota": 4},
            device_id="device-4",
        )

        assert session.user_id == 15
        assert session.remaining_quota == 6.0
        assert session.total_quota == 10.0
        assert session.used_quota == 4.0

    def test_extract_proxy_builds_request_body_and_parses_batch_payload(self, patch_attrs) -> None:
        _reset_auth_state(
            RandomIPSession(
                device_id="device-5",
                user_id=33,
                access_token="a" * 64,
                total_quota=10,
                quota_known=True,
            )
        )
        posted: list[dict[str, object]] = []

        async def fake_post(
            _url: str,
            *,
            json_body: dict[str, object],
            headers: dict[str, str],
            timeout: float = 10,
        ):
            posted.append({"body": json_body, "headers": headers, "timeout": timeout})
            return _Response(
                {
                    "provider": "default",
                    "remaining_quota": 10,
                    "total_quota": 10,
                    "used_quota": 0,
                    "items": [
                        {
                            "host": "8.8.8.8",
                            "port": 8000,
                            "account": "u",
                            "password": "p",
                            "expire_at": "2099-01-01T00:00:00+00:00",
                        }
                    ],
                }
            )

        patch_attrs((auth, "_apost_json", fake_post))

        payload = asyncio.run(
            auth.extract_proxy_async(
                minute=3, pool="quality", area="110100", num=2, upstream="benefit"
            )
        )

        assert posted == [
            {
                "body": {
                    "user_id": 33,
                    "minute": 3,
                    "pool": "quality",
                    "upstream": "benefit",
                    "num": 2,
                    "area": "110100",
                },
                "headers": {
                    "Content-Type": "application/json",
                    **client.DEFAULT_HTTP_HEADERS,
                    "Authorization": f"Bearer {'a' * 64}",
                },
                "timeout": 12.0,
            }
        ]
        assert payload["items"][0]["host"] == "8.8.8.8"

    def test_extract_request_timeout_scales_for_batch_request(self) -> None:
        assert auth._extract_request_timeout_seconds(1) == 10.0
        assert auth._extract_request_timeout_seconds(16) == 40.0
        assert auth._extract_request_timeout_seconds(999) == 60.0

    def test_redeem_card_updates_quota_snapshot(self, patch_attrs) -> None:
        _reset_auth_state(
            RandomIPSession(
                device_id="device-7",
                user_id=55,
                access_token="a" * 64,
                remaining_quota=1,
                total_quota=2,
                used_quota=1,
                quota_known=True,
            )
        )
        settings = _Settings()

        async def fake_redeem_post(_url: str, *, json_body: dict[str, object], **_kwargs):
            assert json_body == {"card_code": "a" * 16}
            return _Response(
                {
                    "redeemed": True,
                    "card_quota": 400,
                    "remaining_quota": 401,
                    "total_quota": 402,
                    "used_quota": 1,
                    "detail": "redeem_card_redeemed",
                }
            )

        patch_attrs(
            (auth, "_get_settings", lambda: settings),
            (auth, "_apost_json", fake_redeem_post),
        )

        result = asyncio.run(auth.redeem_card_async("a" * 16))

        assert result["redeemed"] is True
        assert result["card_quota"] == 400.0
        assert result["remaining_quota"] == 401.0
        assert auth._session.total_quota == 402.0
