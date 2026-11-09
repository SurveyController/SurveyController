from __future__ import annotations

from qfluentwidgets import HyperlinkButton

from software.ui.pages.more.about import AboutPage


def test_about_page_shows_new_contributor_and_fits_narrow_width(monkeypatch, qtbot) -> None:
    monkeypatch.setattr(AboutPage, "_load_publish_time", lambda self: None)
    page = AboutPage()
    qtbot.addWidget(page)
    page.resize(900, 640)
    page.show()
    qtbot.wait(20)

    contributor = next(
        button for button in page.findChildren(HyperlinkButton) if button.text() == "@Quchaosheng"
    )

    assert contributor.url.toString() == "https://github.com/Quchaosheng"
    assert page.horizontalScrollBar().maximum() == 0
    assert contributor.geometry().right() <= contributor.parentWidget().width()
