from __future__ import annotations

from qfluentwidgets import HyperlinkButton

from software.ui.pages.more.about import AboutPage


def test_about_page_shows_new_contributor_and_fits_narrow_width(monkeypatch, qtbot) -> None:
    monkeypatch.setattr(AboutPage, "_load_publish_time", lambda self: None)
    page = AboutPage()
    qtbot.addWidget(page)
    page.resize(1200, 640)
    page.show()
    qtbot.wait(20)

    contributors = {
        button.text(): button
        for button in page.findChildren(HyperlinkButton)
        if button.text().startswith("@")
    }
    first = contributors["@HUNGRY_M0"]
    new_contributor = contributors["@Quchaosheng"]

    assert new_contributor.url.toString() == "https://github.com/Quchaosheng"
    wide_rows: dict[int, list[HyperlinkButton]] = {}
    for button in contributors.values():
        wide_rows.setdefault(button.geometry().y(), []).append(button)
    assert first.geometry().x() == 0
    assert max(len(row) for row in wide_rows.values()) >= 2

    page.resize(900, 640)
    qtbot.wait(20)

    assert page.horizontalScrollBar().maximum() == 0
    buttons = list(contributors.values())
    assert all(button.geometry().right() <= button.parentWidget().width() for button in buttons)
    rows: dict[int, list[HyperlinkButton]] = {}
    for button in buttons:
        rows.setdefault(button.geometry().y(), []).append(button)
    assert len(rows) > 1
    assert max(len(row) for row in rows.values()) >= 2
    for row in rows.values():
        row.sort(key=lambda button: button.geometry().x())
        assert row[0].geometry().x() == 0
        assert all(
            left.geometry().right() < right.geometry().x() for left, right in zip(row, row[1:])
        )
