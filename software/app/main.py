import faulthandler
import logging
import os
import sys

from PySide6.QtCore import qInstallMessageHandler, QtMsgType
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication

from software.app.app_info import APP_VERSION
from software.app.settings_store import configure_qt_application_metadata
from software.app.user_paths import (
    ensure_user_data_directories,
    get_fatal_crash_log_path,
)
import software.network.http as http_client
from software.logging.log_utils import setup_logging
from software.ui.helpers.qfluent_compat import install_qfluentwidgets_animation_guards

_FAULT_HANDLER_STREAM = None


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
    from software.io.runtime_environment import configure_runtime_environment
    from software.app.settings_store import app_settings
    from software.app.user_paths import (
        get_default_runtime_config_path,
        get_legacy_runtime_config_path,
    )

    configure_runtime_environment(
        app_settings,
        get_default_runtime_config_path,
        get_legacy_runtime_config_path,
    )
    configure_qt_application_metadata()
    ensure_user_data_directories()
    _enable_fault_handler()
    setup_logging()

    qInstallMessageHandler(_qt_message_handler)
    app = QApplication(sys.argv)
    app.setApplicationVersion(APP_VERSION)
    install_qfluentwidgets_animation_guards()

    
    font = QFont("Microsoft YaHei UI" if sys.platform == "win32" else "Sans Serif", 9)
    app.setFont(font)

    
    http_client.prewarm()

    
    from software.ui.shell.main_window import create_window
    window = create_window()
    window.show()

    try:
        exit_code = int(app.exec())
    finally:
        try:
            if not window.controller.wait_for_shutdown(timeout_seconds=6.0):
                logging.warning("应用退出时仍有后台资源未完成关闭")
        except Exception:
            logging.warning("等待应用后台资源关闭失败", exc_info=True)
        finally:
            from software.logging.log_utils import shutdown_logging

            shutdown_logging()
            _disable_fault_handler()

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())

