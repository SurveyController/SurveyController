from __future__ import annotations

from PySide6.QtCore import Qt

from software.ui.widgets.no_wheel import NoWheelSpinBox


def test_no_wheel_spinbox_editor_accepts_mouse_and_keyboard_input(qtbot) -> None:
    spin_box = NoWheelSpinBox()
    spin_box.setRange(1, 99999)
    spin_box.resize(272, 36)
    qtbot.addWidget(spin_box)
    spin_box.show()
    spin_box.activateWindow()
    qtbot.waitUntil(spin_box.isActiveWindow)

    editor = spin_box.lineEdit()
    assert editor.width() > 100
    assert spin_box.upButton.isVisible()
    assert spin_box.downButton.isVisible()

    qtbot.mouseClick(editor, Qt.MouseButton.LeftButton)
    assert editor.hasFocus()

    editor.selectAll()
    qtbot.keyClicks(editor, "123")
    assert spin_box.value() == 123
