from __future__ import annotations

from concurrent.futures import Future

from PySide6.QtCore import QBuffer, QIODevice, Qt
from PySide6.QtGui import QImage
from qfluentwidgets import BodyLabel, InfoBadge, PushButton, ScrollArea
from PySide6.QtWidgets import QDialog, QTreeWidgetItem

from software.app.config import DEFAULT_FILL_TEXT
from surveycore.core.questions.config import QuestionEntry
from surveycore.providers.contracts import (
    LOGIC_PARSE_STATUS_COMPLETE,
    LOGIC_PARSE_STATUS_UNKNOWN,
    SurveyQuestionMeta,
)
from software.ui.pages.workbench.question_editor.wizard_dialog import (
    QuestionWizardDialog,
)
from software.ui.pages.workbench.question_editor.question_media_preview import (
    QuestionMediaStrip,
    QuestionMediaThumbnail,
)


def _build_entries() -> list[QuestionEntry]:
    return [
        QuestionEntry(
            question_type="single",
            probabilities=[1, 1],
            texts=None,
            rows=1,
            option_count=2,
            distribution_mode="custom",
            custom_weights=[50, 50],
            question_num=1,
        ),
        QuestionEntry(
            question_type="text",
            probabilities=[1],
            texts=["默认值"],
            rows=1,
            option_count=1,
            distribution_mode="random",
            custom_weights=None,
            question_num=2,
        ),
    ]


def test_question_wizard_dialog_shows_logic_view_and_switches_question(qtbot) -> None:
    info = [
        SurveyQuestionMeta(
            num=1,
            title="第一题",
            page=1,
            option_texts=["显示下一题", "结束"],
            has_dependent_display_logic=True,
            controls_display_targets=[{"condition_option_indices": [0], "target_question_num": 2}],
            logic_parse_status=LOGIC_PARSE_STATUS_COMPLETE,
        ),
        SurveyQuestionMeta(
            num=2,
            title="第二题",
            page=1,
            has_display_condition=True,
            display_conditions=[{"condition_question_num": 1, "condition_option_indices": [0]}],
            logic_parse_status=LOGIC_PARSE_STATUS_COMPLETE,
        ),
    ]
    dlg = QuestionWizardDialog(_build_entries(), info, "demo")
    qtbot.addWidget(dlg)
    dlg.show()

    qtbot.waitUntil(lambda: dlg._tree_widget.topLevelItemCount() > 0)
    assert dlg._content_splitter is not None
    assert dlg._content_splitter.count() == 2
    assert dlg._content_splitter.handleWidth() >= 6
    assert dlg._current_view_mode == "logic"

    page_item = dlg._tree_widget.topLevelItem(0)
    question_item = page_item.child(1)
    dlg._on_tree_item_clicked(question_item, 0)
    assert dlg._current_question_idx == 1

    relation_item = page_item.child(0).child(0)
    assert isinstance(relation_item, QTreeWidgetItem)
    assert page_item.child(0).isExpanded()
    dlg._on_tree_item_clicked(relation_item, 0)
    assert dlg._current_question_idx == 1


def test_question_wizard_dialog_tree_uses_compact_question_label_and_type_badge(qtbot) -> None:
    info = [
        SurveyQuestionMeta(
            num=1,
            title="图片选项题",
            page=1,
            option_texts=["A"],
            required=True,
            has_jump=True,
            jump_rules=[{"option_index": 0, "jumpto": 99}],
            question_media=[
                {
                    "kind": "image",
                    "scope": "option",
                    "index": 0,
                    "source_url": "https://example.com/a.png",
                    "label": "选项A",
                }
            ],
            logic_parse_status=LOGIC_PARSE_STATUS_COMPLETE,
        )
    ]
    dlg = QuestionWizardDialog(_build_entries()[:1], info, "demo")
    qtbot.addWidget(dlg)
    dlg.show()

    qtbot.waitUntil(lambda: dlg._tree_widget.topLevelItemCount() > 0)
    page_item = dlg._tree_widget.topLevelItem(0)
    question_item = page_item.child(0)
    assert question_item.text(0) == ""

    row = dlg._tree_widget.itemWidget(question_item, 0)
    assert row is not None
    labels = [label.text() for label in row.findChildren(BodyLabel)]
    badges = [badge.text() for badge in row.findChildren(InfoBadge)]
    assert labels[0] == "1."
    assert badges == ["单选题"]

    relation_item = question_item.child(0)
    assert relation_item.text(0) == ""
    relation_row = dlg._tree_widget.itemWidget(relation_item, 0)
    assert relation_row is not None
    relation_badges = [badge.text() for badge in relation_row.findChildren(InfoBadge)]
    relation_labels = [label.text() for label in relation_row.findChildren(BodyLabel)]
    assert relation_badges == ["跳题"]
    assert relation_labels == ["选中“A” -> 结束"]


def test_question_wizard_dialog_tree_marks_display_relation_and_expands(qtbot) -> None:
    info = [
        SurveyQuestionMeta(
            num=1,
            title="入口题",
            page=1,
            option_texts=["显示下一题", "不显示"],
            has_dependent_display_logic=True,
            controls_display_targets=[{"condition_option_indices": [0], "target_question_num": 2}],
            logic_parse_status=LOGIC_PARSE_STATUS_COMPLETE,
        ),
        SurveyQuestionMeta(
            num=2,
            title="条件题",
            page=1,
            has_display_condition=True,
            display_conditions=[{"condition_question_num": 1, "condition_option_indices": [0]}],
            logic_parse_status=LOGIC_PARSE_STATUS_COMPLETE,
        ),
    ]
    dlg = QuestionWizardDialog(_build_entries(), info, "demo")
    qtbot.addWidget(dlg)
    dlg.show()

    qtbot.waitUntil(lambda: dlg._tree_widget.topLevelItemCount() > 0)
    question_item = dlg._tree_widget.topLevelItem(0).child(0)
    assert question_item.isExpanded()

    relation_item = question_item.child(0)
    relation_row = dlg._tree_widget.itemWidget(relation_item, 0)
    assert relation_row is not None
    relation_badges = [badge.text() for badge in relation_row.findChildren(InfoBadge)]
    relation_labels = [label.text() for label in relation_row.findChildren(BodyLabel)]
    assert relation_badges == ["条件"]
    assert relation_labels == ["选中“显示下一题” -> 显示第2题"]


def test_question_wizard_dialog_tree_uses_real_question_num_when_display_num_repeats(qtbot) -> None:
    info = [
        SurveyQuestionMeta(
            num=1,
            display_num=1,
            title="入口题",
            page=1,
            option_texts=["显示下一题"],
            logic_parse_status=LOGIC_PARSE_STATUS_COMPLETE,
        ),
        SurveyQuestionMeta(
            num=2,
            display_num=1,
            title="条件题",
            page=1,
            logic_parse_status=LOGIC_PARSE_STATUS_COMPLETE,
        ),
    ]
    dlg = QuestionWizardDialog(_build_entries(), info, "demo")
    qtbot.addWidget(dlg)
    dlg.show()

    qtbot.waitUntil(lambda: dlg._tree_widget.topLevelItemCount() > 0)
    page_item = dlg._tree_widget.topLevelItem(0)
    first_row = dlg._tree_widget.itemWidget(page_item.child(0), 0)
    second_row = dlg._tree_widget.itemWidget(page_item.child(1), 0)

    assert first_row is not None
    assert second_row is not None
    assert [label.text() for label in first_row.findChildren(BodyLabel)][0] == "1."
    assert [label.text() for label in second_row.findChildren(BodyLabel)][0] == "2."


def test_question_wizard_dialog_hides_logic_view_when_unknown(qtbot) -> None:
    info = [
        SurveyQuestionMeta(
            num=1,
            title="第一题",
            page=1,
            logic_parse_status=LOGIC_PARSE_STATUS_UNKNOWN,
        )
    ]
    entries = [
        QuestionEntry(
            question_type="text",
            probabilities=[1],
            texts=["a"],
            rows=1,
            option_count=1,
            distribution_mode="random",
            custom_weights=None,
            question_num=1,
        )
    ]
    dlg = QuestionWizardDialog(entries, info, "demo")
    qtbot.addWidget(dlg)
    dlg.show()

    qtbot.waitUntil(lambda: dlg._tree_widget.topLevelItemCount() > 0)
    assert dlg._current_view_mode == "sequential"


def test_question_wizard_dialog_search_shows_realtime_suggestions(qtbot) -> None:
    info = [
        SurveyQuestionMeta(
            num=1,
            title="第一题",
            page=1,
            option_texts=["苹果", "香蕉"],
            logic_parse_status=LOGIC_PARSE_STATUS_COMPLETE,
        ),
        SurveyQuestionMeta(
            num=2,
            title="第二题",
            page=1,
            option_texts=["西瓜"],
            logic_parse_status=LOGIC_PARSE_STATUS_COMPLETE,
        ),
    ]
    dlg = QuestionWizardDialog(_build_entries(), info, "demo")
    qtbot.addWidget(dlg)
    dlg.show()

    qtbot.waitUntil(lambda: dlg._search_edit is not None and dlg._search_edit.isVisible())
    dlg._search_edit.setText("苹果")

    qtbot.waitUntil(lambda: dlg._search_popup is not None and dlg._search_popup.isVisible())
    assert dlg._search_popup.count() == 1
    assert "第一题" in dlg._search_popup.item(0).text()


def test_question_wizard_dialog_detail_keeps_visible_content_width(qtbot) -> None:
    info = [
        SurveyQuestionMeta(
            num=1,
            title="第一题",
            page=1,
            option_texts=["A", "B"],
            logic_parse_status=LOGIC_PARSE_STATUS_COMPLETE,
        ),
        SurveyQuestionMeta(
            num=2,
            title="第二题",
            page=1,
            logic_parse_status=LOGIC_PARSE_STATUS_COMPLETE,
        ),
    ]
    dlg = QuestionWizardDialog(_build_entries(), info, "demo")
    qtbot.addWidget(dlg)
    dlg.show()

    qtbot.waitUntil(lambda: bool(dlg._entry_card_widgets))
    assert dlg._detail_stack is not None
    assert dlg._detail_scroll is not None
    assert dlg._detail_stack.currentWidget() is dlg._question_cards[0]

    dlg._sync_detail_content_width()
    card = dlg._entry_card_widgets[0]
    viewport_width = dlg._detail_scroll.viewport().width()
    if viewport_width >= 320:
        assert card.maximumWidth() == viewport_width
    assert card.maximumWidth() <= dlg._detail_scroll.viewport().width()
    assert card.maximumWidth() >= 320

    dlg._select_question(1)
    qtbot.waitUntil(lambda: 1 in dlg._entry_card_widgets)
    assert dlg._detail_stack.currentWidget() is dlg._question_cards[1]


def test_question_wizard_dialog_detail_height_follows_current_question(qtbot) -> None:
    entries = [
        QuestionEntry(
            question_type="multiple",
            probabilities=[50] * 22,
            texts=None,
            rows=1,
            option_count=22,
            distribution_mode="custom",
            custom_weights=[50] * 22,
            question_num=1,
        ),
        QuestionEntry(
            question_type="single",
            probabilities=[50, 50],
            texts=None,
            rows=1,
            option_count=2,
            distribution_mode="custom",
            custom_weights=[50, 50],
            question_num=2,
        ),
    ]
    info = [
        SurveyQuestionMeta(
            num=1,
            title="长题",
            page=1,
            option_texts=[f"选项{i}" for i in range(22)],
            logic_parse_status=LOGIC_PARSE_STATUS_COMPLETE,
        ),
        SurveyQuestionMeta(
            num=2,
            title="短题",
            page=1,
            option_texts=["A", "B"],
            logic_parse_status=LOGIC_PARSE_STATUS_COMPLETE,
        ),
    ]
    dlg = QuestionWizardDialog(entries, info, "demo")
    qtbot.addWidget(dlg)
    dlg.resize(1000, 620)
    dlg.show()

    qtbot.waitUntil(lambda: 0 in dlg._entry_card_widgets)
    assert dlg._detail_scroll is not None

    dlg._sync_detail_content_width()
    qtbot.waitUntil(lambda: dlg._detail_scroll.verticalScrollBar().maximum() > 0)
    long_scroll_max = dlg._detail_scroll.verticalScrollBar().maximum()

    dlg._select_question(1)
    qtbot.waitUntil(lambda: 1 in dlg._entry_card_widgets)
    qtbot.waitUntil(
        lambda: dlg._detail_scroll.verticalScrollBar().maximum() < long_scroll_max,
        timeout=2000,
    )
    assert dlg._detail_stack is not None
    assert dlg._detail_stack.currentWidget() is dlg._question_cards[1]


def test_question_wizard_dialog_keeps_controls_alive_after_accept(qtbot) -> None:
    info = [
        SurveyQuestionMeta(
            num=1,
            title="第一题",
            page=1,
            option_texts=["A", "B"],
            logic_parse_status=LOGIC_PARSE_STATUS_COMPLETE,
        )
    ]
    dlg = QuestionWizardDialog(_build_entries()[:1], info, "demo")
    qtbot.addWidget(dlg)
    dlg.show()

    qtbot.waitUntil(lambda: bool(dlg.slider_map))
    dlg.accept()
    qtbot.wait(50)

    assert dlg.result() == QDialog.DialogCode.Accepted
    assert dlg.get_results()[0] == [50, 50]


def test_question_wizard_dialog_matrix_rows_use_outer_detail_scroll(qtbot) -> None:
    entries = [
        QuestionEntry(
            question_type="matrix",
            probabilities=[1],
            texts=None,
            rows=4,
            option_count=4,
            distribution_mode="custom",
            custom_weights=[
                [20, 10, 8, 80],
                [1, 1, 1, 1],
                [5, 10, 15, 20],
                [30, 25, 20, 15],
            ],
            question_num=1,
        )
    ]
    info = [
        SurveyQuestionMeta(
            num=1,
            title="矩阵题",
            page=1,
            row_texts=["外观", "性能", "服务", "价格"],
            option_texts=["1", "2", "3", "4"],
            logic_parse_status=LOGIC_PARSE_STATUS_COMPLETE,
        )
    ]
    dlg = QuestionWizardDialog(entries, info, "demo")
    qtbot.addWidget(dlg)
    dlg.show()

    qtbot.waitUntil(lambda: bool(dlg._entry_card_widgets))
    card = dlg._entry_card_widgets[0]
    inner_scrolls = [
        scroll for scroll in card.findChildren(ScrollArea) if scroll is not dlg._detail_scroll
    ]
    assert inner_scrolls == []
    assert len(dlg.matrix_row_slider_map[0]) == 4


def test_question_wizard_dialog_accept_shows_validation_error_without_navigation_crash(
    qtbot,
) -> None:
    entries = [
        QuestionEntry(
            question_type="text",
            probabilities=[1],
            texts=["默认答案"],
            rows=1,
            option_count=1,
            distribution_mode="random",
            custom_weights=None,
            question_num=1,
        )
    ]
    info = [
        SurveyQuestionMeta(
            num=1,
            title="随机整数测试",
            page=1,
            logic_parse_status=LOGIC_PARSE_STATUS_COMPLETE,
        )
    ]
    dlg = QuestionWizardDialog(entries, info, "demo")
    qtbot.addWidget(dlg)
    dlg.text_random_mode_map[0] = "integer"
    dlg.show()

    dlg.accept()

    qtbot.waitUntil(lambda: dlg._validation_error_dialog is not None)
    assert dlg._validation_error_dialog is not None
    assert dlg._current_question_idx == 0


def test_question_media_thumbnail_can_be_deleted_before_fetch_finishes(qtbot) -> None:
    pending: Future[bytes] = Future()
    widget = QuestionMediaThumbnail(
        {"source_url": "https://example.com/a.png", "label": "题干图"},
        media_fetcher=lambda _url: pending,
    )
    qtbot.addWidget(widget)
    widget.show()

    widget.deleteLater()
    qtbot.wait(10)
    assert pending.cancelled()


def test_question_media_thumbnail_displays_application_result(qtbot) -> None:
    future: Future[bytes] = Future()
    calls: list[str] = []

    def fetch_media(url: str) -> Future[bytes]:
        calls.append(url)
        return future

    widget = QuestionMediaThumbnail(
        {"source_url": "https://example.com/a.png", "label": "题干图"},
        media_fetcher=fetch_media,
    )
    qtbot.addWidget(widget)
    assert widget.image_label.text() == "图片"

    image = QImage(2, 2, QImage.Format.Format_RGBA8888)
    image.fill(Qt.GlobalColor.red)
    buffer = QBuffer()
    assert buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    assert image.save(buffer, "PNG")
    future.set_result(bytes(buffer.data()))

    qtbot.waitUntil(lambda: widget.image_label.text() == "")
    assert calls == ["https://example.com/a.png"]
    assert widget.image_label.text() == ""


def test_question_media_thumbnail_keeps_placeholder_when_fetch_fails(qtbot) -> None:
    future: Future[bytes] = Future()
    widget = QuestionMediaThumbnail(
        {"source_url": "https://example.com/a.png", "label": "题干图"},
        media_fetcher=lambda _url: future,
    )
    qtbot.addWidget(widget)

    future.set_exception(RuntimeError("download failed"))

    assert widget.image_label.text() == "图片"


def test_question_media_strip_can_hide_item_labels(qtbot) -> None:
    widget = QuestionMediaStrip(
        "题干图片",
        [{"source_url": "https://example.com/a.png", "label": "题干图"}],
        show_item_labels=False,
    )
    qtbot.addWidget(widget)

    labels = [label.text() for label in widget.findChildren(BodyLabel)]
    assert "题干图片" in labels
    assert "题干图" not in labels


def test_question_wizard_dialog_multi_text_ignores_empty_answer_group(qtbot) -> None:
    entries = [
        QuestionEntry(
            question_type="multi_text",
            probabilities=[1],
            texts=["甲||乙"],
            rows=1,
            option_count=1,
            distribution_mode="random",
            custom_weights=None,
            question_num=1,
        )
    ]
    info = [
        SurveyQuestionMeta(
            num=1,
            title="多项填空测试",
            page=1,
            text_inputs=2,
            is_multi_text=True,
            logic_parse_status=LOGIC_PARSE_STATUS_COMPLETE,
        )
    ]
    dlg = QuestionWizardDialog(entries, info, "demo")
    qtbot.addWidget(dlg)
    dlg.show()

    qtbot.waitUntil(lambda: bool(dlg.text_edit_map))
    row_edits = dlg.text_edit_map[0][0]
    for edit in row_edits:
        edit.setText("")

    assert dlg.get_text_results()[0] == [DEFAULT_FILL_TEXT]


def test_question_wizard_dialog_shows_media_badge_for_option_image(qtbot) -> None:
    info = [
        SurveyQuestionMeta(
            num=1,
            title="图片选项题",
            page=1,
            option_texts=["A"],
            question_media=[
                {
                    "kind": "image",
                    "scope": "option",
                    "index": 0,
                    "source_url": "https://example.com/a.png",
                    "label": "选项A",
                }
            ],
            logic_parse_status=LOGIC_PARSE_STATUS_COMPLETE,
        )
    ]
    calls: list[str] = []

    def fetch_media(url: str) -> Future[bytes]:
        calls.append(url)
        future: Future[bytes] = Future()
        future.set_result(b"")
        return future

    dlg = QuestionWizardDialog(
        _build_entries()[:1],
        info,
        "demo",
        media_fetcher=fetch_media,
    )
    qtbot.addWidget(dlg)
    dlg.show()

    qtbot.waitUntil(lambda: bool(dlg._entry_card_widgets))
    card = dlg._entry_card_widgets[0]
    badges = [widget.text() for widget in card.findChildren(InfoBadge)]
    assert "图片题" in badges
    assert calls == ["https://example.com/a.png"]


def test_question_wizard_dialog_delete_answer_row_renumbers(qtbot) -> None:
    entry = QuestionEntry(
        question_type="text",
        probabilities=[1],
        texts=["甲", "乙"],
        rows=1,
        option_count=1,
        distribution_mode="random",
        custom_weights=None,
        question_num=1,
    )
    info = [
        SurveyQuestionMeta(
            num=1, title="普通填空测试", page=1, logic_parse_status=LOGIC_PARSE_STATUS_COMPLETE
        )
    ]
    dlg = QuestionWizardDialog([entry], info, "demo")
    qtbot.addWidget(dlg)
    dlg.show()

    qtbot.waitUntil(lambda: bool(dlg.text_edit_map))
    container = dlg.text_container_map[0]
    buttons = [btn for btn in container.findChildren(PushButton) if btn.text() == "×"]
    assert len(buttons) == 2

    buttons[0].click()
    qtbot.wait(50)

    labels = [
        label.text() for label in container.findChildren(BodyLabel) if label.text().endswith(".")
    ]
    assert labels[0] == "1."
