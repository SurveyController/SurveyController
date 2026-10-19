from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import QSpinBox
from qfluentwidgets import Slider, SpinBox, setCustomStyleSheet

_HIDDEN_NATIVE_SPIN_BUTTONS_QSS = """
SpinBox::up-button,
SpinBox::down-button {
    width: 0px;
    height: 0px;
    padding: 0px;
    border: none;
}
"""


class NoWheelSlider(Slider):
    

    def wheelEvent(self, event: QWheelEvent) -> None:
        event.ignore()


class NoWheelSpinBox(SpinBox):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setButtonSymbols(QSpinBox.ButtonSymbols.UpDownArrows)
        setCustomStyleSheet(
            self,
            _HIDDEN_NATIVE_SPIN_BUTTONS_QSS,
            _HIDDEN_NATIVE_SPIN_BUTTONS_QSS,
        )

    def wheelEvent(self, event: QWheelEvent) -> None:
        event.ignore()
