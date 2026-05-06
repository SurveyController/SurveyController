from __future__ import annotations

import json
import os

import software.app.legacy_data_migration as migration


class LegacyDataMigrationTests:
    def _patch_user_dirs(self, monkeypatch, tmp_path) -> dict[str, str]:
        config_root = tmp_path / "roaming" / "SurveyController"
        local_root = tmp_path / "local" / "SurveyController"
        monkeypatch.setattr(migration, "get_default_runtime_config_path", lambda: str(config_root / "config.json"))
        monkeypatch.setattr(migration, "get_user_config_directory", lambda: str(config_root / "configs"))
        monkeypatch.setattr(migration, "get_user_logs_directory", lambda: str(local_root / "logs"))
        monkeypatch.setattr(migration, "get_legacy_migration_marker_path", lambda: str(local_root / "migration" / "legacy_inno_v1.json"))
        monkeypatch.setattr(migration, "ensure_user_data_directories", lambda: ())
        return {
            "config_root": str(config_root),
            "local_root": str(local_root),
        }

    def test_migration_copies_legacy_files_without_overwrite(self, monkeypatch, tmp_path) -> None:
        self._patch_user_dirs(monkeypatch, tmp_path)
        legacy_dir = tmp_path / "legacy"
        (legacy_dir / "configs" / "nested").mkdir(parents=True)
        (legacy_dir / "logs").mkdir(parents=True)
        (legacy_dir / "config.json").write_text('{"old": true}', encoding="utf-8")
        (legacy_dir / "configs" / "default.json").write_text("legacy-config", encoding="utf-8")
        (legacy_dir / "configs" / "nested" / "keep.json").write_text("nested", encoding="utf-8")
        (legacy_dir / "logs" / "session.log").write_text("legacy-log", encoding="utf-8")
        monkeypatch.setattr(migration, "_find_legacy_install_directory", lambda: str(legacy_dir))

        result = migration.ensure_legacy_data_migrated()

        assert result.source_found
        assert result.copied_files >= 4
        assert os.path.exists(migration.get_default_runtime_config_path())
        assert os.path.exists(os.path.join(migration.get_user_config_directory(), "default.json"))
        assert os.path.exists(os.path.join(migration.get_user_logs_directory(), "session.log"))
        with open(migration.get_legacy_migration_marker_path(), "r", encoding="utf-8") as file:
            marker = json.load(file)
        assert marker["source_found"] is True

    def test_migration_skips_missing_source_and_marks_once(self, monkeypatch, tmp_path) -> None:
        self._patch_user_dirs(monkeypatch, tmp_path)
        monkeypatch.setattr(migration, "_find_legacy_install_directory", lambda: "")

        first = migration.ensure_legacy_data_migrated()
        second = migration.ensure_legacy_data_migrated()

        assert not first.already_migrated
        assert not first.source_found
        assert second.already_migrated
        assert os.path.exists(migration.get_legacy_migration_marker_path())

    def test_existing_target_files_are_not_overwritten(self, monkeypatch, tmp_path) -> None:
        self._patch_user_dirs(monkeypatch, tmp_path)
        os.makedirs(os.path.dirname(migration.get_default_runtime_config_path()), exist_ok=True)
        os.makedirs(migration.get_user_config_directory(), exist_ok=True)
        os.makedirs(migration.get_user_logs_directory(), exist_ok=True)
        with open(migration.get_default_runtime_config_path(), "w", encoding="utf-8") as file:
            file.write("current")
        with open(os.path.join(migration.get_user_config_directory(), "default.json"), "w", encoding="utf-8") as file:
            file.write("current-config")

        legacy_dir = tmp_path / "legacy"
        (legacy_dir / "configs").mkdir(parents=True)
        (legacy_dir / "logs").mkdir(parents=True)
        (legacy_dir / "config.json").write_text("legacy", encoding="utf-8")
        (legacy_dir / "configs" / "default.json").write_text("legacy-config", encoding="utf-8")
        monkeypatch.setattr(migration, "_find_legacy_install_directory", lambda: str(legacy_dir))

        migration.ensure_legacy_data_migrated()

        with open(migration.get_default_runtime_config_path(), "r", encoding="utf-8") as file:
            assert file.read() == "current"
        with open(os.path.join(migration.get_user_config_directory(), "default.json"), "r", encoding="utf-8") as file:
            assert file.read() == "current-config"
