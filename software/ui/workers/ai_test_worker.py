from PySide6.QtCore import QObject, Signal

from software.core.engine.async_engine import AsyncRuntimeEngine


class AITestWorker(QObject):
    finished = Signal(bool, str)

    def __init__(self, *, test_connection):
        super().__init__()
        self._test_connection = test_connection

    def run(self):
        engine = AsyncRuntimeEngine()
        try:
            result = engine.submit_ui_task(
                "ai_test_connection",
                self._test_connection,
            ).result()
            success = result.startswith("连接成功")
            self.finished.emit(success, result)
        except Exception as exc:
            self.finished.emit(False, f"连接失败: {exc}")
        finally:
            engine.shutdown(timeout=2.0)
