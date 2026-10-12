from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from software.update import updater


class UpdateHelperTests:
    def test_check_updates_returns_unsupported_on_macos(self) -> None:
        with (
            patch.object(updater.sys, "platform", "darwin"),
            patch.object(updater, "__VERSION__", "4.0.0"),
        ):
            result = updater.UpdateManager.check_updates()
        assert result == {
            "has_update": False,
            "status": "unsupported",
            "current_version": "4.0.0",
        }

    def test_preview_release_notes_strips_markdown_and_truncates(self) -> None:
        preview = updater._preview_release_notes('# 标题\n\n---\n\n**加粗** 和 ~~删除线~~\n\n* 列表项\n\n普通段落', 18)
        assert preview == '标题\n\n加粗 和 删除线\n- 列表项\n...'

    def test_check_updates_queries_github_release(self) -> None:
        response = MagicMock()
        response.json.return_value = {
            "tag_name": "v3.2.0", "body": "发行说明", "html_url": "https://example.com/release",
        }
        with (
            patch.object(updater, "__VERSION__", "3.1.2"),
            patch.object(updater.sys, "platform", "win32"),
            patch.object(updater.http_client, "get", return_value=response) as get,
        ):
            result = updater.UpdateManager.check_updates()
        get.assert_called_once_with(
            updater.GITHUB_API_URL,
            headers={"Accept": "application/vnd.github.v3+json"},
            timeout=(10, 30),
        )
        assert result == {
            "has_update": True, "status": "outdated", "version": "3.2.0",
            "latest_version": "3.2.0", "current_version": "3.1.2", "release_notes": "发行说明",
            "manual_only": True, "manual_release_url": "https://example.com/release",
        }

    def test_check_updates_returns_unknown_when_github_request_fails(self) -> None:
        with (
            patch.object(updater.sys, "platform", "win32"),
            patch.object(updater.http_client, "get", side_effect=RuntimeError("network down")),
        ):
            result = updater.UpdateManager.check_updates()
        assert result["status"] == "unknown"
        assert result["has_update"] is False

    def test_build_github_update_result_returns_unknown_when_version_cannot_be_parsed(self) -> None:
        with (
            patch.object(updater, "__VERSION__", "3.1.2"),
            patch.object(updater, "_fetch_latest_github_release", return_value={"tag_name": "???", "body": "说明"}),
        ):
            result = updater._build_github_update_result("3.1.2")
        assert result["status"] == "unknown"
        assert result["latest_version"] == "???"

    def test_build_remote_version_result_covers_unknown_latest_preview_and_outdated(self) -> None:
        assert updater._build_remote_version_result("3.1.2", "???", release_notes="说明") == {
            "has_update": False,
            "status": "unknown",
            "current_version": "3.1.2",
            "latest_version": "???",
            "release_notes": "说明",
        }
        assert updater._build_remote_version_result("3.1.2", "3.1.2", release_notes="说明") == {
            "has_update": False,
            "status": "latest",
            "current_version": "3.1.2",
            "latest_version": "3.1.2",
            "release_notes": "说明",
        }
        assert updater._build_remote_version_result("3.1.3", "3.1.2")["status"] == "preview"
        outdated = updater._build_remote_version_result("3.1.2", "3.1.4")
        assert outdated["status"] == "outdated"
        assert outdated["manual_release_url"].endswith("/v3.1.4")

    def test_get_all_releases_returns_empty_when_request_fails(self) -> None:
        with patch.object(updater.http_client, "get", side_effect=RuntimeError("boom")):
            assert updater.UpdateManager.get_all_releases() == []

    def test_get_all_releases_normalizes_payload(self) -> None:
        response = MagicMock()
        response.json.return_value = [
            {
                "tag_name": "v3.2.0",
                "name": "稳定版",
                "body": "修复说明",
                "published_at": "2026-05-08T00:00:00Z",
                "prerelease": False,
                "html_url": "https://example.com/release",
            }
        ]
        with patch.object(updater.http_client, "get", return_value=response):
            result = updater.UpdateManager.get_all_releases()
        assert result == [
            {
                "version": "3.2.0",
                "name": "稳定版",
                "body": "修复说明",
                "published_at": "2026-05-08T00:00:00Z",
                "prerelease": False,
                "html_url": "https://example.com/release",
            }
        ]

    def test_show_update_notification_opens_browser_for_manual_only_update(self) -> None:
        gui = SimpleNamespace(
            update_info={
                "version": "3.2.0",
                "current_version": "3.1.2",
                "release_notes": "修了几个坑",
                "manual_only": True,
                "manual_release_url": "https://example.com/release",
            },
            show_confirm_dialog=MagicMock(return_value=True),
        )
        with patch.object(updater, "log_action"), patch.object(updater.webbrowser, "open") as open_mock:
            updater.show_update_notification(gui)
        open_mock.assert_called_once_with("https://example.com/release")


    def test_show_update_notification_does_not_open_release_when_declined(self) -> None:
        gui = SimpleNamespace(
            update_info={"version": "3.2.0", "current_version": "3.1.2"},
            show_confirm_dialog=MagicMock(return_value=False),
        )
        with patch.object(updater.webbrowser, "open") as open_mock:
            updater.show_update_notification(gui)
        open_mock.assert_not_called()
        assert "自动更新" not in gui.show_confirm_dialog.call_args.args[1]
