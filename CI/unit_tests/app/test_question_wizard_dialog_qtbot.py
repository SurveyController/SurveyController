from __future__ import annotations

from concurrent.futures import Future

from PySide6.QtCore import QBuffer, QIODevice, Qt
from PySide6.QtGui import QImage
from qfluentwidgets import BodyLabel, InfoBadge, PushButton
from PySide6.QtWidgets import QDialog, QTreeWidgetItem

from software.core.config.codec import deserialize_question_entry, serialize_question_entry
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


def test_multilevel_dropdown_card_edits_complete_path_weights(qtbot) -> None:
    entry = QuestionEntry(
        question_type="multilevel_dropdown",
        probabilities=[1, 1],
        option_count=2,
        distribution_mode="custom",
        custom_weights=[1, 1],
        question_num=1,
    )
    info = [
        SurveyQuestionMeta(
            num=1,
            title="地区",
            type_code="7",
            provider_type="multilevel_dropdown",
            option_texts=["省‐市‐区A", "省‐市‐区B"],
        )
    ]
    dlg = QuestionWizardDialog([entry], info, "多级题")
    qtbot.addWidget(dlg)
    dlg.show()
    qtbot.waitUntil(lambda: bool(dlg.multilevel_map))

    editor = dlg.multilevel_map[0]
    assert 0 not in dlg.slider_map
    editor.paths.select([0], False)
    editor._refresh()
    editor.distribution.sliders[1].setValue(10000)

    dlg.accept()
    assert dlg.result() == QDialog.DialogCode.Accepted
    assert dlg.get_results()[0] == [0, 100]
    entry.custom_weights = dlg.get_results()[0]
    entry.probabilities = entry.custom_weights
    entry.distribution_mode = "custom"
    restored = deserialize_question_entry(serialize_question_entry(entry))
    assert restored.question_type == "multilevel_dropdown"
    assert restored.custom_weights == [0, 100]
    assert editor.paths.selected == {1}


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


def test_question_wizard_dialog_text_fill_mode_selector_switches_contextual_controls(qtbot) -> None:
    from software.ui.pages.workbench.question_editor.fill_mode_selector import FillModeSelector

    entry = QuestionEntry(
        question_type="text",
        probabilities=[1],
        texts=["默认答案"],
        rows=1,
        option_count=1,
        distribution_mode="random",
        custom_weights=None,
        question_num=1,
    )
    info = [
        SurveyQuestionMeta(
            num=1, title="填空题", page=1, logic_parse_status=LOGIC_PARSE_STATUS_COMPLETE
        )
    ]
    dlg = QuestionWizardDialog([entry], info, "demo")
    qtbot.addWidget(dlg)
    dlg.show()

    qtbot.waitUntil(lambda: bool(dlg._entry_card_widgets))
    card = dlg._entry_card_widgets[0]
    selector = card.findChild(FillModeSelector)
    assert selector is not None
    assert selector.current_mode() == "none"
    assert dlg.text_container_map[0].isVisibleTo(card)
    assert not selector.range_widget.isVisibleTo(card)

    selector.combo.setCurrentIndex(selector.combo.findData("ai"))
    assert selector.current_mode() == "ai"
    assert not dlg.text_container_map[0].isVisibleTo(card)
    assert not selector.range_widget.isVisibleTo(card)
    assert dlg.get_ai_flags()[0] is True
    assert dlg.get_text_random_modes()[0] == "none"

    selector.combo.setCurrentIndex(selector.combo.findData("integer"))
    assert selector.current_mode() == "integer"
    assert not dlg.text_container_map[0].isVisibleTo(card)
    assert selector.range_widget.isVisibleTo(card)
    selector.min_edit.setText("5")
    selector.max_edit.setText("15")
    assert dlg.get_ai_flags()[0] is False
    assert dlg.get_text_random_modes()[0] == "integer"
    assert dlg.get_text_random_int_ranges()[0] == [5, 15]


def test_question_wizard_dialog_multi_text_fill_mode_selector_updates_matrix(qtbot) -> None:
    from software.ui.pages.workbench.question_editor.fill_mode_selector import FillModeSelector

    entry = QuestionEntry(
        question_type="multi_text",
        probabilities=[1],
        texts=["甲||乙"],
        rows=1,
        option_count=1,
        distribution_mode="random",
        custom_weights=None,
        question_num=1,
    )
    info = [
        SurveyQuestionMeta(
            num=1,
            title="多项填空",
            page=1,
            text_inputs=2,
            is_multi_text=True,
            logic_parse_status=LOGIC_PARSE_STATUS_COMPLETE,
        )
    ]
    dlg = QuestionWizardDialog([entry], info, "demo")
    qtbot.addWidget(dlg)
    dlg.show()

    qtbot.waitUntil(lambda: bool(dlg._entry_card_widgets))
    card = dlg._entry_card_widgets[0]
    selectors = card.findChildren(FillModeSelector)
    assert len(selectors) == 2

    selectors[1].combo.setCurrentIndex(selectors[1].combo.findData("integer"))
    selectors[1].min_edit.setText("1")
    selectors[1].max_edit.setText("9")
    assert dlg.text_container_map[0].isVisibleTo(card)
    assert dlg.text_edit_map[0][0][0].isEnabled()
    assert not dlg.text_edit_map[0][0][1].isEnabled()
    assert selectors[1].range_widget.isVisibleTo(card)
    assert dlg.get_multi_text_blank_modes()[0] == ["none", "integer"]
    assert dlg.get_multi_text_blank_int_ranges()[0] == [[], [1, 9]]

    selectors[0].combo.setCurrentIndex(selectors[0].combo.findData("ai"))
    selectors[1].combo.setCurrentIndex(selectors[1].combo.findData("name"))
    assert not dlg.text_container_map[0].isVisibleTo(card)
    assert dlg.get_multi_text_blank_ai_flags()[0] == [True, False]
    assert dlg.get_multi_text_blank_modes()[0] == ["none", "name"]


def test_question_wizard_dialog_option_fill_mode_selector_updates_fill_result(qtbot) -> None:
    from software.ui.pages.workbench.question_editor.fill_mode_selector import FillModeSelector

    entry = QuestionEntry(
        question_type="single",
        probabilities=[1, 1],
        texts=None,
        rows=1,
        option_count=2,
        distribution_mode="custom",
        custom_weights=[50, 50],
        question_num=1,
        fillable_option_indices=[0],
        option_fill_texts=[["无", "不便说明\n谢谢"], None],
    )
    info = [
        SurveyQuestionMeta(
            num=1,
            title="带填空单选",
            page=1,
            options=2,
            option_texts=["其他", "B"],
            fillable_options=[0],
            logic_parse_status=LOGIC_PARSE_STATUS_COMPLETE,
        )
    ]
    dlg = QuestionWizardDialog([entry], info, "demo")
    qtbot.addWidget(dlg)
    dlg.show()

    qtbot.waitUntil(lambda: bool(dlg._entry_card_widgets))
    card = dlg._entry_card_widgets[0]
    badges = [widget.text() for widget in card.findChildren(InfoBadge)]
    assert "附带填空" in badges
    selector = card.findChild(FillModeSelector)
    assert selector is not None
    fill_edit = dlg.option_fill_edit_map[0][0]
    assert fill_edit.isVisibleTo(card)
    assert not selector.range_widget.isVisibleTo(card)
    assert fill_edit.toPlainText() == "无\n不便说明\n谢谢"
    assert dlg.get_option_fill_results()[0] == [["无", "不便说明\n谢谢"], None]

    fill_edit.setPlainText("意见一\n\n 意见二 ")
    assert dlg.get_option_fill_results()[0] == [["意见一", "意见二"], None]

    selector.combo.setCurrentIndex(selector.combo.findData("ai"))
    assert fill_edit.isVisibleTo(card)
    assert not fill_edit.isEnabled()
    assert fill_edit.placeholderText() == "AI 生成"
    assert dlg.get_option_fill_results()[0] == ["__AI_FILL__", None]

    selector.combo.setCurrentIndex(selector.combo.findData("integer"))
    assert not fill_edit.isVisibleTo(card)
    assert selector.range_widget.isVisibleTo(card)
    selector.min_edit.setText("10")
    selector.max_edit.setText("20")
    assert dlg.get_option_fill_results()[0] == ["__RANDOM_INT__:10:20", None]

    selector.combo.setCurrentIndex(selector.combo.findData("name"))
    assert fill_edit.isVisibleTo(card)
    assert not fill_edit.isEnabled()
    assert fill_edit.placeholderText() == "随机姓名"
    assert dlg.get_option_fill_results()[0] == ["__RANDOM_NAME__", None]


def test_question_wizard_dialog_order_question_shows_forced_random_status(qtbot) -> None:
    from qfluentwidgets import ComboBox

    entry = QuestionEntry(
        question_type="order",
        probabilities=[1, 1, 1],
        texts=None,
        rows=1,
        option_count=3,
        distribution_mode="random",
        custom_weights=None,
        question_num=1,
    )
    info = [
        SurveyQuestionMeta(
            num=1,
            title="排序题",
            page=1,
            option_texts=["甲", "乙", "丙"],
            logic_parse_status=LOGIC_PARSE_STATUS_COMPLETE,
        )
    ]
    dlg = QuestionWizardDialog([entry], info, "demo")
    qtbot.addWidget(dlg)
    dlg.show()

    qtbot.waitUntil(lambda: bool(dlg._entry_card_widgets))
    card = dlg._entry_card_widgets[0]
    assert card.findChild(ComboBox) is None
    badges = [badge.text() for badge in card.findChildren(InfoBadge)]
    labels = [label.text() for label in card.findChildren(BodyLabel)]
    assert "强制随机排列" in badges
    assert "不支持手动配置" in labels
