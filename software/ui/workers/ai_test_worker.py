"""AI 连接测试 Worker - 在独立线程中测试 AI 接口可用性"""

from PySide6.QtCore import QObject, Signal

from software.core.engine.async_engine import AsyncRuntimeEngine
from software.integrations.ai import atest_connection


class AITestWorker(QObject):
    finished = Signal(bool, str)

    def run(self):
        engine = AsyncRuntimeEngine()
        try:
            result = engine.submit_ui_task("ai_test_connection", atest_connection).result()
            success = result.startswith("连接成功")
            self.finished.emit(success, result)
        except Exception as exc:
            self.finished.emit(False, f"连接失败: {exc}")
        finally:
            engine.shutdown(timeout=2.0)
