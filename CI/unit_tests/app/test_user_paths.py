from __future__ import annotations

import os

from PySide6.QtCore import QCoreApplication, QStandardPaths

import software.app.user_paths as user_paths


class _FakeSettings:
    def __init__(self, configured_path: str = "") -> None:
        self._configured_path = configured_path

    def value(self, key: str):
        if key == user_paths.CONFIG_DIRECTORY_SETTING_KEY:
            return self._configured_path
        return None


class UserPathsTests:
    def test_standard_roots_strip_qt_app_suffix(self, monkeypatch, tmp_path) -> None:
        config_root = tmp_path / "config-root" / "SurveyController" / "Settings"
        local_root = tmp_path / "local-root" / "SurveyController" / "Settings"

        monkeypatch.setattr(user_paths, "configure_qt_application_metadata", lambda: None)
        monkeypatch.setattr(QCoreApplication, "applicationName", lambda: "Settings")
        monkeypatch.setattr(QCoreApplication, "organizationName", lambda: "SurveyController")

        def fake_writable_location(location) -> str:
            if location == QStandardPaths.StandardLocation.AppDataLocation:
                return str(config_root)
            if location == QStandardPaths.StandardLocation.AppLocalDataLocation:
                return str(local_root)
            raise AssertionError(f"unexpected location: {location}")

        monkeypatch.setattr(QStandardPaths, "writableLocation", fake_writable_location)

        assert user_paths.get_roaming_app_data_root() == str(config_root.parent.parent)
        assert user_paths.get_local_app_data_root() == str(local_root.parent.parent)
        assert user_paths.get_user_config_root() == str(config_root.parent)
        assert user_paths.get_user_local_data_root() == str(local_root.parent)
        assert user_paths.get_user_logs_directory() == str(local_root.parent / "logs")
        assert user_paths.get_user_cache_directory() == str(local_root.parent / "cache")
        assert user_paths.get_user_updates_directory() == str(local_root.parent / "updates")
        assert user_paths.get_default_runtime_config_path() == str(
            config_root.parent / "configs" / "config.json"
        )
        assert user_paths.get_legacy_runtime_config_path() == str(
            config_root.parent / "config.json"
        )

    def test_standard_roots_fall_back_to_home_when_qt_returns_empty(
        self, monkeypatch, tmp_path
    ) -> None:
        monkeypatch.setattr(user_paths, "configure_qt_application_metadata", lambda: None)
        monkeypatch.setattr(QStandardPaths, "writableLocation", lambda _location: "")
        monkeypatch.setattr(user_paths.os.path, "expanduser", lambda _path: str(tmp_path))

        assert user_paths.get_roaming_app_data_root() == str(tmp_path / "AppData" / "Roaming")
        assert user_paths.get_local_app_data_root() == str(tmp_path / "AppData" / "Local")

    def test_ensure_user_data_directories_creates_expected_tree(
        self, monkeypatch, tmp_path
    ) -> None:
        monkeypatch.setattr(
            user_paths, "get_user_config_root", lambda: str(tmp_path / "config-root")
        )
        monkeypatch.setattr(
            user_paths,
            "get_user_config_directory",
            lambda: str(tmp_path / "config-root" / "configs"),
        )
        monkeypatch.setattr(
            user_paths, "get_user_local_data_root", lambda: str(tmp_path / "local-root")
        )
        monkeypatch.setattr(
            user_paths, "get_user_logs_directory", lambda: str(tmp_path / "local-root" / "logs")
        )
        monkeypatch.setattr(
            user_paths, "get_user_cache_directory", lambda: str(tmp_path / "local-root" / "cache")
        )
        monkeypatch.setattr(
            user_paths,
            "get_user_updates_directory",
            lambda: str(tmp_path / "local-root" / "updates"),
        )

        created = user_paths.ensure_user_data_directories()

        assert created
        for path in created:
            assert os.path.isdir(path)

    def test_user_config_directory_can_follow_qsettings_override(self, tmp_path) -> None:
        override_dir = tmp_path / "custom-configs"

        assert user_paths.resolve_user_config_directory(_FakeSettings(str(override_dir))) == str(
            override_dir.resolve()
        )

    def test_default_user_config_directory_uses_standard_config_root(
        self, monkeypatch, tmp_path
    ) -> None:
        monkeypatch.setattr(
            user_paths, "get_user_config_root", lambda: str(tmp_path / "SurveyController")
        )

        assert user_paths.get_default_user_config_directory() == str(
            tmp_path / "SurveyController" / "configs"
        )

    def test_default_runtime_config_path_follows_selected_config_directory(
        self,
        tmp_path,
    ) -> None:
        selected_directory = tmp_path / "selected-configs"
        settings = _FakeSettings(str(selected_directory))

        assert user_paths.get_default_runtime_config_path(settings) == str(
            selected_directory.resolve() / "config.json"
        )

    def test_runtime_config_avoids_overwriting_legacy_file_when_directory_matches(
        self,
        monkeypatch,
        tmp_path,
    ) -> None:
        legacy_directory = tmp_path / "SurveyController"
        monkeypatch.setattr(user_paths, "get_user_config_root", lambda: str(legacy_directory))
        settings = _FakeSettings(str(legacy_directory))

        assert user_paths.get_default_runtime_config_path(settings) == str(
            legacy_directory.resolve() / "runtime-config.json"
        )
