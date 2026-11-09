from __future__ import annotations

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QDialog, QWidget
from qfluentwidgets import TextBrowser, Theme, qconfig, setTheme

from software.ui.dialogs.terms_of_service import (
    LEGAL_TEXT_FILES,
    TermsOfServiceDialog,
    _load_terms_content,
    _read_legal_text,
    _resolve_dialog_size,
)


def test_load_terms_content_keeps_legal_text_without_divider_lines() -> None:
    content = _load_terms_content()
    source_sections = [_read_legal_text(path) for path in LEGAL_TEXT_FILES]
    expected = "\n\n".join(
        "\n".join(
            line
            for line in section.splitlines()
            if not (line.strip() and set(line.strip()) == {"─"})
        )
        for section in source_sections
        if section
    ).strip()

    assert content == expected
    assert "服务条款" in content
    assert "隐私声明" in content
    assert "【第一条 接受条款】" in content
    assert "【信息收集】" in content
    assert not any(line.strip() and set(line.strip()) == {"─"} for line in content.splitlines())


@pytest.mark.parametrize("theme", [Theme.LIGHT, Theme.DARK])
def test_terms_dialog_uses_read_only_document_view(qtbot, monkeypatch, theme) -> None:
    monkeypatch.setattr(
        "software.ui.dialogs.terms_of_service._load_terms_content",
        lambda: ("服务条款\n\n隐私声明\n" * 300).strip(),
    )
    app = QApplication.instance() or QApplication([])
    previous_theme = qconfig.get(qconfig.themeMode)
    setTheme(theme)
    parent = QWidget()
    qtbot.addWidget(parent)
    parent.resize(900, 640)
    parent.show()
    qtbot.waitUntil(parent.isVisible)
    dialog = TermsOfServiceDialog(parent)
    qtbot.addWidget(dialog)

    try:
        assert app is QApplication.instance()
        assert isinstance(dialog.contentBrowser, TextBrowser)
        assert dialog.contentBrowser.isReadOnly()
        assert dialog.contentBrowser.toPlainText().startswith("服务条款\n\n隐私声明")
        assert dialog.yesButton.text() == "关闭"
        assert dialog.cancelButton.isHidden()
        assert dialog.widget.size().width() == 702
        assert dialog.widget.size().height() == 520
        assert dialog.contentBrowser.horizontalScrollBarPolicy() == (
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )

        size = _resolve_dialog_size(parent)
        assert size.width() == 702
        assert size.height() == 520

        dialog.open()
        qtbot.waitUntil(lambda: dialog.isVisible())
        assert dialog.contentBrowser.verticalScrollBar().maximum() > 0
        dialog.contentBrowser.verticalScrollBar().setValue(
            dialog.contentBrowser.verticalScrollBar().maximum()
        )
        assert dialog.contentBrowser.verticalScrollBar().value() == (
            dialog.contentBrowser.verticalScrollBar().maximum()
        )
        dialog.yesButton.click()
        qtbot.waitUntil(lambda: dialog.result() == QDialog.DialogCode.Accepted)
        assert dialog.result() == QDialog.DialogCode.Accepted
    finally:
        dialog.close()
        setTheme(previous_theme)
