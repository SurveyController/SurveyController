import faulthandler
import importlib
import os
import sys
from typing import Any, Optional, cast

from PySide6.QtCore import qInstallMessageHandler, QtMsgType
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication

from software.app.settings_store import configure_qt_application_metadata
from software.app.user_paths import (
    ensure_user_data_directories,
    get_fatal_crash_log_path,
)
import software.network.http as http_client
from software.logging.log_utils import setup_logging
from software.ui.helpers.qfluent_compat import install_qfluentwidgets_animation_guards

_VELOPACK_MODULE_NAME = "velopack"


_FAULT_HANDLER_STREAM = None


def _get_velopack_module() -> Optional[Any]:
    try:
        return cast(Any, importlib.import_module(_VELOPACK_MODULE_NAME))
    except Exception:
        return None


def _is_velopack_lifecycle_hook(args: list[str]) -> bool:
    hook_args = {
        "--veloapp-install",
        "--veloapp-updated",
        "--veloapp-obsolete",
        "--veloapp-uninstall",
    }
    return any(str(arg).lower() in hook_args for arg in args[1:])


def _run_velopack_startup() -> None:
    
    if not getattr(sys, "frozen", False):
        return
    velopack_module = _get_velopack_module()
    if velopack_module is None:
        return

    try:
        app = velopack_module.App()
        app.set_auto_apply_on_startup(False)
        app.run()
    except Exception:
        return


def _should_run_update_test_probe() -> bool:
    if "--ci-update-probe" not in sys.argv[1:]:
        return False
    if str(os.environ.get("SURVEYCONTROLLER_UPDATE_TEST_MODE", "") or "").strip() != "1":
        return False
    return bool(str(os.environ.get("SURVEYCONTROLLER_UPDATE_TEST_RESULT", "") or "").strip())


def _run_update_test_probe() -> int:
    from software.update.ci_probe import run as run_probe

    return int(run_probe())


def _enable_fault_handler() -> None:
    
    global _FAULT_HANDLER_STREAM

    if faulthandler.is_enabled():
        return

    try:
        fault_log_path = get_fatal_crash_log_path()
        logs_dir = os.path.dirname(fault_log_path)
        os.makedirs(logs_dir, exist_ok=True)
        _FAULT_HANDLER_STREAM = open(fault_log_path, "a", encoding="utf-8", buffering=1)
        faulthandler.enable(_FAULT_HANDLER_STREAM, all_threads=True)
    except Exception:
        try:
            faulthandler.enable(all_threads=True)
        except Exception:
            _FAULT_HANDLER_STREAM = None


def _disable_fault_handler() -> None:
    global _FAULT_HANDLER_STREAM

    try:
        if faulthandler.is_enabled():
            faulthandler.disable()
    except Exception:
        pass

    stream = _FAULT_HANDLER_STREAM
    _FAULT_HANDLER_STREAM = None
    if stream is not None:
        try:
            stream.close()
        except Exception:
            pass


def _qt_message_handler(mode, context, message):
    
    _ = context
    if "QFont::setPointSize" in message:
        return
    if mode == QtMsgType.QtWarningMsg:
        print(f"Qt Warning: {message}")
    elif mode == QtMsgType.QtCriticalMsg:
        print(f"Qt Critical: {message}")
    elif mode == QtMsgType.QtFatalMsg:
        print(f"Qt Fatal: {message}")


def main():
    _run_velopack_startup()
    if _is_velopack_lifecycle_hook(sys.argv):
        return 0
    if _should_run_update_test_probe():
        raise SystemExit(_run_update_test_probe())

    configure_qt_application_metadata()
    ensure_user_data_directories()
    _enable_fault_handler()
    setup_logging()

    qInstallMessageHandler(_qt_message_handler)
    app = QApplication(sys.argv)
    install_qfluentwidgets_animation_guards()

    
    font = QFont("Microsoft YaHei UI" if sys.platform == "win32" else "Sans Serif", 9)
    app.setFont(font)

    
    http_client.prewarm()

    
    from software.ui.shell.main_window import create_window
    window = create_window()
    window.show()

    exit_code = int(app.exec())

    
    from software.logging.log_utils import shutdown_logging
    shutdown_logging()
    _disable_fault_handler()

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())

