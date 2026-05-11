from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from software.network.browser.runtime_async import PlaywrightAsyncDriver
from software.network.browser.subprocess_utils import build_local_text_subprocess_kwargs


class BrowserSubprocessUtilsTests:
    def test_build_local_text_subprocess_kwargs_prefers_locale_encoding(self) -> None:
        with patch("software.network.browser.subprocess_utils.locale.getencoding", return_value="cp936"), patch("software.network.browser.subprocess_utils.locale.getpreferredencoding", return_value="utf-8"):
            kwargs = build_local_text_subprocess_kwargs()
        assert kwargs["text"] is True
        assert kwargs["errors"] == "replace"
        assert kwargs["encoding"] == "cp936"

    def test_force_terminate_browser_process_tree_uses_local_text_decode_settings(self) -> None:
        driver = object.__new__(PlaywrightAsyncDriver)
        driver.browser_pids = {2468}
        driver.browser_pid = None
        with patch("software.network.browser.runtime_async.subprocess.run", return_value=SimpleNamespace(returncode=0, stdout="", stderr="")) as run_mock, patch("software.network.browser.runtime_async.build_local_text_subprocess_kwargs", return_value={"text": True, "encoding": "cp936", "errors": "replace"}):
            terminated = PlaywrightAsyncDriver._force_terminate_browser_process_tree(driver)
        assert terminated
        _, kwargs = run_mock.call_args
        assert kwargs["encoding"] == "cp936"
        assert kwargs["errors"] == "replace"
        assert kwargs["text"] is True
