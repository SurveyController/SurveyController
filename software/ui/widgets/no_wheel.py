from PySide6.QtGui import QWheelEvent
from qfluentwidgets import Slider, SpinBox


class NoWheelSlider(Slider):
    

    def wheelEvent(self, event: QWheelEvent) -> None:
        event.ignore()


class NoWheelSpinBox(SpinBox):
    

    def wheelEvent(self, event: QWheelEvent) -> None:
        event.ignore()
