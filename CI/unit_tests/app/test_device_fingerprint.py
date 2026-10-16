from __future__ import annotations

import software.system.device_fingerprint as device_fingerprint


class _Settings:
    def __init__(self, value: str = "") -> None:
        self.values = {"random_ip_auth/device_id": value}
        self.synced = 0

    def value(self, key: str):
        return self.values.get(key)

    def setValue(self, key: str, value: str) -> None:
        self.values[key] = value

    def sync(self) -> None:
        self.synced += 1


class _Secret:
    def __init__(self, value: str = "", status: str = "not_found") -> None:
        self.value = value
        self.status = status


class DeviceFingerprintTests:
    def test_build_stable_device_id_reads_existing_settings_value(self, monkeypatch) -> None:
        settings = _Settings("sc-v2-settings")
        monkeypatch.setattr(device_fingerprint, "app_settings", lambda: settings)
        assert device_fingerprint.build_stable_device_id() == "sc-v2-settings"

    def test_build_stable_device_id_generates_and_persists_uuid(self, monkeypatch) -> None:
        settings = _Settings()
        monkeypatch.setattr(device_fingerprint, "app_settings", lambda: settings)
        monkeypatch.setattr(device_fingerprint, "read_secret", lambda _key: _Secret())
        monkeypatch.setattr(
            device_fingerprint.uuid,
            "uuid4",
            lambda: type("UUID", (), {"hex": "1234567890abcdef1234567890abcdef"})(),
        )

        first = device_fingerprint.build_stable_device_id()
        second = device_fingerprint.build_stable_device_id()

        assert first == "sc-v2-1234567890abcdef1234567890abcdef"
        assert second == first
        assert settings.values["random_ip_auth/device_id"] == first

    def test_build_stable_device_id_migrates_legacy_secret(self, monkeypatch) -> None:
        settings = _Settings()
        monkeypatch.setattr(device_fingerprint, "app_settings", lambda: settings)
        monkeypatch.setattr(
            device_fingerprint,
            "read_secret",
            lambda _key: _Secret("sc-v2-legacy", "ok"),
        )

        assert device_fingerprint.build_stable_device_id() == "sc-v2-legacy"
        assert settings.values["random_ip_auth/device_id"] == "sc-v2-legacy"
