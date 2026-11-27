from __future__ import annotations

from PySide6.QtWidgets import QDialog, QWidget

from software.ui.dialogs.terms_of_service import TermsOfServiceDialog


def test_terms_dialog_displays_terms_and_privacy_notice_and_can_close(qtbot) -> None:
    parent = QWidget()
    qtbot.addWidget(parent)
    parent.show()
    dialog = TermsOfServiceDialog(parent)
    qtbot.addWidget(dialog)

    dialog.open()
    assert dialog.isVisible()
    content = dialog.contentBrowser.toPlainText()
    assert "【第一条 接受条款】" in content
    assert "【信息收集】" in content
    assert dialog.contentBrowser.isReadOnly()

    dialog.yesButton.click()
    qtbot.waitUntil(lambda: dialog.result() == QDialog.DialogCode.Accepted)
