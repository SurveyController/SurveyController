from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from software.update import updater


class UpdateHelperTests:
    def test_preview_release_notes_strips_markdown_and_truncates(self) -> None:
        preview = updater._preview_release_notes('# 标题\n\n---\n\n**加粗** 和 ~~删除线~~\n\n* 列表项\n\n普通段落', 18)
        assert preview == '标题\n\n加粗 和 删除线\n- 列表项\n...'

    def test_check_updates_falls_back_to_github_when_velopack_manager_missing(self) -> None:
        with (
            patch.object(updater, "__VERSION__", "3.1.1"),
            patch.object(updater, "_safe_create_update_manager", return_value=None),
            patch.object(updater, "_fetch_latest_github_release", return_value={"tag_name": "v3.1.2", "body": "GitHub 说明", "html_url": "https://example.com/release"}),
        ):
            result = updater.UpdateManager.check_updates()
        assert result["status"] == "outdated"
        assert result["has_update"] is True
        assert result["version"] == "3.1.2"
        assert result["release_notes"] == "GitHub 说明"
        assert result["manual_only"] is True
        assert result["manual_release_url"] == "https://example.com/release"

    def test_check_updates_returns_unknown_when_github_fallback_missing(self) -> None:
        with (
            patch.object(updater, "_safe_create_update_manager", return_value=None),
            patch.object(updater, "_fetch_latest_github_release", return_value=None),
        ):
            result = updater.UpdateManager.check_updates()
        assert result["status"] == "unknown"
        assert result["has_update"] is False

    def test_check_updates_returns_preview_when_github_latest_is_older(self) -> None:
        with (
            patch.object(updater, "_safe_create_update_manager", return_value=None),
            patch.object(updater, "_fetch_latest_github_release", return_value={"tag_name": "v3.1.0", "body": "旧版本说明", "html_url": "https://example.com/release"}),
            patch.object(updater, "__VERSION__", "3.1.2b1"),
        ):
            result = updater.UpdateManager.check_updates()
        assert result["status"] == "preview"
        assert result["has_update"] is False
        assert result["latest_version"] == "3.1.0"

    def test_check_updates_returns_latest_when_no_release_available(self) -> None:
        manager = MagicMock()
        manager.get_current_version.return_value = "3.1.2"
        manager.check_for_updates.return_value = None
        with patch.object(updater, "_safe_create_update_manager", return_value=manager):
            result = updater.UpdateManager.check_updates()
        assert result == {"has_update": False, "status": "latest", "current_version": "3.1.2"}

    def test_check_updates_returns_outdated_when_release_exists(self) -> None:
        asset = SimpleNamespace(Version="3.2.0", NotesMarkdown="修复一堆破事")
        manager = MagicMock()
        manager.get_current_version.return_value = "3.1.2"
        manager.check_for_updates.return_value = SimpleNamespace(TargetFullRelease=asset)
        with patch.object(updater, "_safe_create_update_manager", return_value=manager):
            result = updater.UpdateManager.check_updates()
        assert result["status"] == "outdated"
        assert result["has_update"] is True
        assert result["version"] == "3.2.0"
        assert result["release_notes"] == "修复一堆破事"

    def test_check_updates_falls_back_to_github_release_body_when_velopack_notes_missing(self) -> None:
        asset = SimpleNamespace(Version="3.2.0", NotesMarkdown="", NotesHtml="")
        manager = MagicMock()
        manager.get_current_version.return_value = "3.1.2"
        manager.check_for_updates.return_value = SimpleNamespace(TargetFullRelease=asset)
        with (
            patch.object(updater, "_safe_create_update_manager", return_value=manager),
            patch.object(updater, "_fetch_github_release_by_tag", return_value={"body": "GitHub 里的发行说明"}),
        ):
            result = updater.UpdateManager.check_updates()
        assert result["status"] == "outdated"
        assert result["release_notes"] == "GitHub 里的发行说明"

    def test_check_updates_falls_back_to_release_list_when_tag_lookup_missing(self) -> None:
        asset = SimpleNamespace(Version="3.2.0", NotesMarkdown="", NotesHtml="")
        manager = MagicMock()
        manager.get_current_version.return_value = "3.1.2"
        manager.check_for_updates.return_value = SimpleNamespace(TargetFullRelease=asset)
        with (
            patch.object(updater, "_safe_create_update_manager", return_value=manager),
            patch.object(updater, "_fetch_github_release_by_tag", return_value=None),
            patch.object(updater, "_fetch_github_release_from_list", return_value={"body": "列表里的发行说明"}),
        ):
            result = updater.UpdateManager.check_updates()
        assert result["status"] == "outdated"
        assert result["release_notes"] == "列表里的发行说明"

    def test_check_updates_keeps_empty_notes_when_github_release_body_missing(self) -> None:
        asset = SimpleNamespace(Version="3.2.0", NotesMarkdown="", NotesHtml="")
        manager = MagicMock()
        manager.get_current_version.return_value = "3.1.2"
        manager.check_for_updates.return_value = SimpleNamespace(TargetFullRelease=asset)
        with (
            patch.object(updater, "_safe_create_update_manager", return_value=manager),
            patch.object(updater, "_fetch_github_release_by_tag", return_value=None),
            patch.object(updater, "_fetch_github_release_from_list", return_value=None),
        ):
            result = updater.UpdateManager.check_updates()
        assert result["status"] == "outdated"
        assert result["release_notes"] == ""

    def test_check_updates_returns_preview_when_local_version_is_newer(self) -> None:
        manager = MagicMock()
        manager.get_current_version.return_value = "3.1.1"
        manager.check_for_updates.return_value = None
        with patch.object(updater, "_safe_create_update_manager", return_value=manager), patch.object(updater, "__VERSION__", "3.1.2b1"):
            result = updater.UpdateManager.check_updates()
        assert result["status"] == "preview"
        assert result["current_version"] == "3.1.2b1"

    def test_check_updates_returns_unknown_when_manager_raises(self) -> None:
        manager = MagicMock()
        manager.get_current_version.return_value = "3.1.2"
        manager.check_for_updates.side_effect = RuntimeError("network down")
        with patch.object(updater, "_safe_create_update_manager", return_value=manager):
            result = updater.UpdateManager.check_updates()
        assert result["status"] == "unknown"

    def test_download_update_reports_progress(self) -> None:
        manager = MagicMock()
        progress_values: list[tuple[int, int, float]] = []
        def on_progress(downloaded: int, total: int, speed: float) -> None:
            progress_values.append((downloaded, total, speed))

        def fake_download(_update_info, callback):
            callback(5)
            callback(100)

        manager.download_updates.side_effect = fake_download
        with patch.object(updater, "_safe_create_update_manager", return_value=manager):
            assert updater.UpdateManager.download_update(object(), progress_callback=on_progress)
        assert progress_values == [(5, 100, 0.0), (100, 100, 0.0)]

    def test_apply_downloaded_update_uses_wait_exit_then_apply(self) -> None:
        manager = MagicMock()
        update_info = object()
        with patch.object(updater, "_safe_create_update_manager", return_value=manager):
            updater.UpdateManager.apply_downloaded_update(update_info)
        manager.wait_exit_then_apply_updates.assert_called_once_with(update_info, silent=True, restart=True)
