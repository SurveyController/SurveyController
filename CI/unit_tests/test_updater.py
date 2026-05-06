from __future__ import annotations
import tempfile
from collections import OrderedDict
from pathlib import Path
from unittest.mock import patch
from software.update import updater

class UpdateHelperTests:

    def test_get_download_source_returns_default_when_setting_is_blank(self, make_settings_mock) -> None:
        settings = make_settings_mock(value_return='  ')
        with patch.object(updater, 'app_settings', return_value=settings):
            assert updater._get_download_source() == updater.DEFAULT_DOWNLOAD_SOURCE

    def test_get_download_source_falls_back_to_default_when_settings_raise(self) -> None:
        with patch.object(updater, 'app_settings', side_effect=RuntimeError('boom')):
            assert updater._get_download_source() == updater.DEFAULT_DOWNLOAD_SOURCE

    def test_set_download_source_persists_value(self, make_settings_mock) -> None:
        settings = make_settings_mock()
        with patch.object(updater, 'app_settings', return_value=settings):
            updater._set_download_source('github')
        settings.setValue.assert_called_once_with('download_source', 'github')

    def test_get_next_download_source_walks_sources_in_order(self) -> None:
        with patch.object(updater, 'DOWNLOAD_SOURCES', OrderedDict([('official', {}), ('github', {}), ('mirror', {})])):
            assert updater._get_next_download_source('unknown') == 'official'
            assert updater._get_next_download_source('official') == 'github'
            assert updater._get_next_download_source('github') == 'mirror'
            assert updater._get_next_download_source('mirror') is None

    def test_apply_download_source_to_url_prefers_direct_download_url(self) -> None:
        with patch.object(updater, 'DOWNLOAD_SOURCES', {'official': {'direct_download_url': 'https://dl.example.com/app.exe'}}):
            assert updater._apply_download_source_to_url('https://github.com/org/repo/releases/download/app.exe', 'official') == 'https://dl.example.com/app.exe'

    def test_apply_download_source_to_url_prefixes_github_link_for_mirror(self) -> None:
        with patch.object(updater, 'DOWNLOAD_SOURCES', {'mirror': {'download_prefix': 'https://mirror.example/'}}):
            assert updater._apply_download_source_to_url('https://github.com/org/repo/releases/download/app.exe', 'mirror') == 'https://mirror.example/https://github.com/org/repo/releases/download/app.exe'
            assert updater._apply_download_source_to_url('https://example.com/app.exe', 'mirror') == 'https://example.com/app.exe'

    def test_preview_release_notes_strips_markdown_and_truncates(self) -> None:
        preview = updater._preview_release_notes('# 标题\n\n---\n\n**加粗** 和 ~~删除线~~\n\n* 列表项\n\n普通段落', 18)
        assert preview == '标题\n\n加粗 和 删除线\n- 列表项\n...'

    def test_cleanup_old_executables_only_removes_other_surveycontroller_exes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            keep = directory / 'SurveyController_latest.exe'
            old = directory / 'SurveyController_1.0.exe'
            unrelated_exe = directory / 'OtherTool.exe'
            note = directory / 'SurveyController_notes.txt'
            for path in (keep, old, unrelated_exe, note):
                path.write_text('x', encoding='utf-8')
            updater.UpdateManager.cleanup_old_executables(str(keep))
            assert keep.exists()
            assert not old.exists()
            assert unrelated_exe.exists()
            assert note.exists()
