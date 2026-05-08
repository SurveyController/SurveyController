from __future__ import annotations

import software.system.device_fingerprint as device_fingerprint


class DeviceFingerprintTests:
    def test_build_stable_device_id_uses_machine_guid_and_user_sid(self, patch_attrs) -> None:
        patch_attrs(
            (device_fingerprint, "_read_machine_guid", lambda: "MACHINE-GUID"),
            (device_fingerprint, "_read_user_sid", lambda: "S-1-5-21-1000"),
        )

        first = device_fingerprint.build_stable_device_id()
        second = device_fingerprint.build_stable_device_id()

        assert first == second
        assert first.startswith("sc-v2-")
        assert len(first) == 38

    def test_build_stable_device_id_changes_when_user_sid_changes(self, patch_attrs) -> None:
        user_sid = "S-1-5-21-1000"
        patch_attrs(
            (device_fingerprint, "_read_machine_guid", lambda: "MACHINE-GUID"),
            (device_fingerprint, "_read_user_sid", lambda: user_sid),
        )

        first = device_fingerprint.build_stable_device_id()
        user_sid = "S-1-5-21-2000"
        second = device_fingerprint.build_stable_device_id()

        assert first != second

    def test_build_stable_device_id_falls_back_to_random_when_machine_guid_missing(self, patch_attrs) -> None:
        patch_attrs(
            (device_fingerprint, "_read_machine_guid", lambda: ""),
            (device_fingerprint, "_read_user_sid", lambda: "S-1-5-21-1000"),
            (device_fingerprint.uuid, "uuid4", lambda: type("UUID", (), {"hex": "random-device"})()),
        )

        assert device_fingerprint.build_stable_device_id() == "random-device"

