from __future__ import annotations

import unittest
from collections import OrderedDict
from unittest.mock import MagicMock, patch

from software.update import updater


class UpdateHelperTests(unittest.TestCase):
    def test_get_download_source_returns_default_when_setting_is_blank(self) -> None:
        settings = MagicMock()
        settings.value.return_value = "  "

        with patch.object(updater, "app_settings", return_value=settings):
            self.assertEqual(updater._get_download_source(), updater.DEFAULT_DOWNLOAD_SOURCE)

    def test_get_download_source_falls_back_to_default_when_settings_raise(self) -> None:
        with patch.object(updater, "app_settings", side_effect=RuntimeError("boom")):
            self.assertEqual(updater._get_download_source(), updater.DEFAULT_DOWNLOAD_SOURCE)

    def test_set_download_source_persists_value(self) -> None:
        settings = MagicMock()

        with patch.object(updater, "app_settings", return_value=settings):
            updater._set_download_source("github")

        settings.setValue.assert_called_once_with("download_source", "github")

    def test_get_next_download_source_walks_sources_in_order(self) -> None:
        with patch.object(
            updater,
            "DOWNLOAD_SOURCES",
            OrderedDict(
                [
                    ("official", {}),
                    ("github", {}),
                    ("mirror", {}),
                ]
            ),
        ):
            self.assertEqual(updater._get_next_download_source("unknown"), "official")
            self.assertEqual(updater._get_next_download_source("official"), "github")
            self.assertEqual(updater._get_next_download_source("github"), "mirror")
            self.assertIsNone(updater._get_next_download_source("mirror"))

    def test_apply_download_source_to_url_prefers_direct_download_url(self) -> None:
        with patch.object(
            updater,
            "DOWNLOAD_SOURCES",
            {"official": {"direct_download_url": "https://dl.example.com/app.exe"}},
        ):
            self.assertEqual(
                updater._apply_download_source_to_url(
                    "https://github.com/org/repo/releases/download/app.exe",
                    "official",
                ),
                "https://dl.example.com/app.exe",
            )

    def test_apply_download_source_to_url_prefixes_github_link_for_mirror(self) -> None:
        with patch.object(
            updater,
            "DOWNLOAD_SOURCES",
            {"mirror": {"download_prefix": "https://mirror.example/"}},
        ):
            self.assertEqual(
                updater._apply_download_source_to_url(
                    "https://github.com/org/repo/releases/download/app.exe",
                    "mirror",
                ),
                "https://mirror.example/https://github.com/org/repo/releases/download/app.exe",
            )
            self.assertEqual(
                updater._apply_download_source_to_url("https://example.com/app.exe", "mirror"),
                "https://example.com/app.exe",
            )

    def test_preview_release_notes_strips_markdown_and_truncates(self) -> None:
        preview = updater._preview_release_notes(
            "# 标题\n\n---\n\n**加粗** 和 ~~删除线~~\n\n* 列表项\n\n普通段落",
            18,
        )

        self.assertEqual(preview, "标题\n\n加粗 和 删除线\n- 列表项\n...")


if __name__ == "__main__":
    unittest.main()
