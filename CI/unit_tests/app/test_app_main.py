from __future__ import annotations

from software.app import main as app_main


class AppMainTests:
    def test_velopack_lifecycle_hook_args_are_detected(self) -> None:
        assert app_main._is_velopack_lifecycle_hook(["SurveyController.exe", "--veloapp-install", "3.1.4"])
        assert app_main._is_velopack_lifecycle_hook(["SurveyController.exe", "--veloapp-updated", "3.1.4"])
        assert app_main._is_velopack_lifecycle_hook(["SurveyController.exe", "--veloapp-obsolete", "3.1.3"])
        assert app_main._is_velopack_lifecycle_hook(["SurveyController.exe", "--veloapp-uninstall", "3.1.4"])

    def test_normal_app_start_args_are_not_lifecycle_hooks(self) -> None:
        assert not app_main._is_velopack_lifecycle_hook(["SurveyController.exe"])
        assert not app_main._is_velopack_lifecycle_hook(["SurveyController.exe", "--user-option"])
