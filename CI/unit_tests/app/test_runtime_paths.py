from __future__ import annotations
from unittest.mock import patch
import software.app.runtime_paths as runtime_paths

class RuntimePathsTests:

    def test_get_runtime_directory_returns_repo_root_in_dev_mode(self) -> None:
        with patch.object(runtime_paths.sys, 'frozen', False, create=True), patch('software.app.runtime_paths._get_repo_root', return_value='D:/repo'):
            result = runtime_paths.get_runtime_directory()
        assert result == 'D:/repo'

    def test_get_runtime_directory_uses_parent_when_frozen_exe_is_inside_lib(self) -> None:
        with patch.object(runtime_paths.sys, 'frozen', True, create=True), patch.object(runtime_paths.sys, 'executable', 'D:/App/lib/SurveyController.exe', create=True):
            result = runtime_paths.get_runtime_directory()
        assert result.replace('\\', '/') == 'D:/App'

    def test_get_bundle_resource_root_prefers_meipass_when_frozen(self) -> None:
        with patch.object(runtime_paths.sys, 'frozen', True, create=True), patch.object(runtime_paths.sys, '_MEIPASS', 'D:/bundle', create=True), patch.object(runtime_paths.sys, 'executable', 'D:/App/SurveyController.exe', create=True):
            result = runtime_paths.get_bundle_resource_root()
        assert result.replace('\\', '/') == 'D:/bundle'

    def test_get_assets_directory_prefers_existing_exe_assets_in_frozen_mode(self) -> None:
        existing = {'D:/bundle/assets': False, 'D:/App/assets': True, 'D:/App/_internal/assets': False}

        def fake_isdir(path: str) -> bool:
            return existing.get(path.replace('\\', '/'), False)
        with patch('software.app.runtime_paths.get_bundle_resource_root', return_value='D:/bundle'), patch.object(runtime_paths.sys, 'frozen', True, create=True), patch.object(runtime_paths.sys, 'executable', 'D:/App/SurveyController.exe', create=True), patch('software.app.runtime_paths.os.path.isdir', side_effect=fake_isdir):
            result = runtime_paths.get_assets_directory()
        assert result.replace('\\', '/') == 'D:/App/assets'

    def test_get_assets_directory_falls_back_to_bundle_assets_when_none_exist(self) -> None:
        with patch('software.app.runtime_paths.get_bundle_resource_root', return_value='D:/bundle'), patch.object(runtime_paths.sys, 'frozen', False, create=True), patch('software.app.runtime_paths.os.path.isdir', return_value=False):
            result = runtime_paths.get_assets_directory()
        assert result.replace('\\', '/') == 'D:/bundle/assets'

    def test_get_resource_path_joins_bundle_root_and_relative_path(self) -> None:
        with patch('software.app.runtime_paths.get_bundle_resource_root', return_value='D:/bundle'):
            result = runtime_paths.get_resource_path('assets/../assets/icon.ico')
        assert result.replace('\\', '/') == 'D:/bundle/assets/icon.ico'
