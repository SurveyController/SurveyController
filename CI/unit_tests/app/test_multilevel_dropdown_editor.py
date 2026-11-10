from __future__ import annotations

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QDialog, QWidget
from qfluentwidgets import (
    Slider,
    Theme,
    TreeView,
    setTheme,
)
from surveycore.core.questions.config import QuestionEntry
from surveycore.providers.contracts import SurveyQuestionMeta

from software.core.config.codec import deserialize_question_entry, serialize_question_entry
from software.ui.pages.workbench.question_editor.multilevel_editor import MultilevelDropdownEditor
from software.ui.pages.workbench.question_editor.multilevel_paths import MultilevelPaths
from software.ui.pages.workbench.question_editor.wizard_dialog import QuestionWizardDialog

SEPARATOR = chr(0x2010)
PATHS = [
    ("湖南省", "长沙市", "岳麓区", "湖南大学"),
    ("湖南省", "长沙市", "岳麓区", "中南大学"),
    ("湖南省", "株洲市", "天元区"),
    ("广东省", "深圳市", "南山区", "深圳大学"),
]


def _editor(qtbot, weights=None):
    weights = [1.0] * len(PATHS) if weights is None else weights
    entry = QuestionEntry(
        "multilevel_dropdown", weights, option_count=len(PATHS), custom_weights=weights
    )
    editor = MultilevelDropdownEditor(entry, [SEPARATOR.join(parts) for parts in PATHS])
    qtbot.addWidget(editor)
    editor.resize(780, 520)
    editor.show()
    return editor


def test_selection_preserves_saved_distribution_and_original_path_order():
    paths = MultilevelPaths([SEPARATOR.join(p) for p in PATHS], [2.5, 7.5, 0, 30])
    paths.select([3], False)
    assert paths.values == [2.5, 7.5, 0, 0]
    paths.select([2], True)
    assert paths.values == [2.5, 7.5, 1, 0]


def test_groups_handle_same_names_duplicates_and_uneven_terminal_paths(qtbot):
    texts = [SEPARATOR.join(p) for p in [("省-A", "市"), ("省-A", "市", "校"), ("省-B", "市")]]
    weights = [1, 0, 0, 2]
    entry = QuestionEntry("multilevel_dropdown", weights, option_count=4)
    editor = MultilevelDropdownEditor(entry, [*texts, texts[0]])
    qtbot.addWidget(editor)
    assert editor.paths.parts == [
        ("省-A", "市"),
        ("省-A", "市", "校"),
        ("省-B", "市"),
        ("省-A", "市"),
    ]
    assert list(editor.distribution.group_cards) == [("省-A",), ("省-A", "市"), ("省-B",)]
    editor.distribution.sliders[3].setValue(400)
    assert editor.get_weights() == [1, 0, 0, 4]


def test_search_and_group_selection_keep_hidden_choices(qtbot):
    editor = _editor(qtbot, [0, 0, 0, 1])
    distribution = editor.distribution
    editor.search_edit.setText("长沙市")
    qtbot.mouseClick(editor.select_button, Qt.MouseButton.LeftButton)
    assert editor.get_weights() == [1, 1, 0, 1]
    assert set(distribution.sliders) == {0, 1}
    editor.search_edit.clear()
    editor._filter()
    assert len(distribution.sliders) == 4
    checkbox = distribution.option_checks[0]
    qtbot.mouseClick(checkbox, Qt.MouseButton.LeftButton)
    assert editor.get_weights() == [0, 1, 0, 1]
    group_checkbox = distribution.group_checks[PATHS[0][:-1]]
    assert group_checkbox.checkState() == Qt.CheckState.PartiallyChecked
    qtbot.mouseClick(group_checkbox, Qt.MouseButton.LeftButton)
    assert editor.get_weights() == [1, 1, 0, 1]
    qtbot.mouseClick(group_checkbox, Qt.MouseButton.LeftButton)
    assert editor.get_weights() == [0, 0, 0, 1]
    province_checkbox = distribution.group_checks[("湖南省",)]
    qtbot.mouseClick(province_checkbox, Qt.MouseButton.LeftButton)
    assert editor.get_weights() == [1, 1, 1, 1]
    qtbot.mouseClick(group_checkbox, Qt.MouseButton.LeftButton)
    assert editor.get_weights() == [0, 0, 1, 1]
    assert province_checkbox.checkState() == Qt.CheckState.PartiallyChecked
    qtbot.mouseClick(province_checkbox, Qt.MouseButton.LeftButton)
    assert editor.get_weights() == [1, 1, 1, 1]
    qtbot.mouseClick(province_checkbox, Qt.MouseButton.LeftButton)
    assert editor.get_weights() == [0, 0, 0, 1]
    editor.only_selected.setChecked(True)
    assert set(distribution.sliders) == {3}
    assert list(distribution.group_cards) == [
        ("广东省",),
        ("广东省", "深圳市"),
        ("广东省", "深圳市", "南山区"),
    ]


def test_empty_custom_weights_restore_existing_probabilities(qtbot):
    entry = QuestionEntry("multilevel_dropdown", [0, 2.5], option_count=2, custom_weights=[])
    editor = MultilevelDropdownEditor(entry, ["甲省", "乙省"])
    qtbot.addWidget(editor)
    assert editor.get_weights() == [0, 2.5]


def test_grouped_sliders_update_global_ratios_and_reject_zero_weights(qtbot):
    editor = _editor(qtbot)
    distribution = editor.distribution
    assert not editor.findChildren(TreeView)
    assert list(distribution.group_cards) == [
        ("湖南省",),
        ("湖南省", "长沙市"),
        ("湖南省", "长沙市", "岳麓区"),
        ("湖南省", "株洲市"),
        ("广东省",),
        ("广东省", "深圳市"),
        ("广东省", "深圳市", "南山区"),
    ]
    for branch, card in distribution.group_cards.items():
        if len(branch) > 1:
            assert card.parentWidget() is distribution.group_cards[branch[:-1]]
    school_group = distribution.group_cards[("湖南省", "长沙市", "岳麓区")]
    assert distribution.sliders[0].parentWidget().parentWidget() is school_group
    distribution.sliders[0].setValue(300)
    assert editor.get_weights() == [3, 1, 1, 1]
    assert [label.text() for label in distribution.ratio_labels.values()] == [
        "50.0%",
        "16.7%",
        "16.7%",
        "16.7%",
    ]
    assert distribution.ratio_labels[0].lightColor == QColor("#107c10")
    assert distribution.ratio_labels[1].lightColor == QColor("#f7630c")
    for slider in distribution.sliders.values():
        slider.setValue(0)
    assert editor.paths.selected == {0, 1, 2, 3}
    with pytest.raises(ValueError, match="权重"):
        editor.get_weights()
    assert editor.error_bar.isVisible()
    assert all(
        label.lightColor == QColor("#d13438") for label in distribution.ratio_labels.values()
    )
    distribution.sliders[1].setValue(100)
    assert editor.get_weights() == [0, 1, 0, 0]
    assert distribution.ratio_labels[1].text() == "100.0%"
    assert distribution.ratio_labels[1].lightColor == QColor("#107c10")
    editor._clear()
    assert editor.validation_message() == "请选择至少一条路径"
    assert all(not checkbox.isChecked() for checkbox in distribution.option_checks.values())


def test_individual_sliders_save_immediately_without_changing_other_paths(qtbot):
    entry = QuestionEntry("multilevel_dropdown", [1, 1], option_count=2, question_num=1)
    info = [SurveyQuestionMeta(num=1, title="地区", option_texts=["甲省", "乙省"])]
    dialog = QuestionWizardDialog([entry], info)
    qtbot.addWidget(dialog)
    dialog.show()
    editor = dialog.multilevel_map[0]
    first = editor.distribution.sliders[0]
    second = editor.distribution.sliders[1]
    assert type(first) is Slider
    first.setValue(300)
    first.setFocus()
    qtbot.keyClick(first, Qt.Key.Key_Right)
    assert editor.paths.values == [3.01, 1]
    second.setValue(500)
    dialog.accept()
    assert dialog.result() == QDialog.DialogCode.Accepted
    assert dialog.get_results()[0] == [3.01, 5]


def test_slider_sync_preserves_fractional_and_large_saved_weights(qtbot):
    weights = [0.125, 0.375, 0, 12345.6789]
    editor = _editor(qtbot, weights)
    distribution = editor.distribution
    assert distribution.sliders[3].value() == distribution.sliders[3].maximum()
    assert editor.get_weights() == weights
    distribution.sliders[0].setValue(5000)
    assert editor.get_weights() == [12345.6789 / 2, 0.375, 0, 12345.6789]


def test_sliders_select_unchecked_paths_and_only_selected_filter_tracks_selection(qtbot):
    editor = _editor(qtbot, [0, 2, 0, 3])
    distribution = editor.distribution
    assert set(distribution.sliders) == {0, 1, 2, 3}
    distribution.sliders[0].setValue(500)
    assert editor.get_weights() == [5, 2, 0, 3]
    assert distribution.option_checks[0].isChecked()
    editor.only_selected.setChecked(True)
    assert set(distribution.sliders) == {0, 1, 3}
    qtbot.mouseClick(distribution.group_checks[PATHS[0][:-1]], Qt.MouseButton.LeftButton)
    assert editor.get_weights() == [0, 0, 0, 3]
    assert set(distribution.sliders) == {3}


def test_multilevel_controls_fill_taller_question_viewport(qtbot):
    entry = QuestionEntry("multilevel_dropdown", [1] * len(PATHS), option_count=len(PATHS))
    info = [
        SurveyQuestionMeta(num=1, title="地区", option_texts=[SEPARATOR.join(p) for p in PATHS])
    ]
    dialog = QuestionWizardDialog([entry], info)
    qtbot.addWidget(dialog)
    dialog.show()
    qtbot.wait(20)
    dialog.setMaximumSize(1600, 1400)
    dialog.resize(1100, 850)
    dialog._sync_detail_content_width()
    qtbot.wait(20)
    editor = dialog.multilevel_map[0]
    before_height = editor.distribution.scroll_area.height()
    dialog.resize(1100, 1100)
    qtbot.waitUntil(lambda: editor.distribution.scroll_area.height() >= before_height + 200)
    assert dialog._entry_card_widgets[0].height() >= dialog._detail_scroll.viewport().height() - 2


@pytest.mark.parametrize("matrix_first", [True, False])
def test_multilevel_fills_viewport_after_switching_from_matrix(qtbot, matrix_first):
    entries = [
        QuestionEntry("matrix", [1] * 5, rows=4, option_count=5),
        QuestionEntry("multilevel_dropdown", [1] * len(PATHS), option_count=len(PATHS)),
    ]
    info = [
        SurveyQuestionMeta(num=1, title="矩阵题", option_texts=[str(i) for i in range(5)]),
        SurveyQuestionMeta(num=2, title="地区", option_texts=[SEPARATOR.join(p) for p in PATHS]),
    ]
    dialog = QuestionWizardDialog(entries, info)
    qtbot.addWidget(dialog)
    dialog.show()
    qtbot.wait(30)
    dialog.setMaximumSize(1600, 1400)
    dialog.resize(1180, 1100)
    qtbot.wait(30)
    if not matrix_first:
        dialog._select_question(1)
        qtbot.wait(300)
        dialog._content_splitter.setSizes([480, 660])
        qtbot.wait(30)
        dialog._content_splitter.setSizes([240, 900])
        qtbot.wait(30)
    for index in [1, 0, 1, 0, 1]:
        dialog._select_question(index)
        qtbot.wait(300)
    editor = dialog.multilevel_map[1]
    viewport = dialog._detail_scroll.viewport()
    card = dialog._entry_card_widgets[1]
    assert card.height() >= viewport.height() - 2
    assert editor.distribution.scroll_area.height() >= viewport.height() - 260
    assert card.mapTo(viewport, card.rect().bottomLeft()).y() >= viewport.height() - 2
    assert dialog._detail_scroll.widget() is dialog._detail_stack
    assert card.parentWidget().maximumHeight() > viewport.height()
    assert dialog._detail_stack.maximumHeight() > viewport.height()
    dialog.resize(1180, 700)
    qtbot.wait(300)
    dialog.resize(1180, 1100)
    qtbot.wait(300)
    assert editor.distribution.scroll_area.height() >= viewport.height() - 260
    assert card.mapTo(viewport, card.rect().bottomLeft()).y() >= viewport.height() - 2


def test_wizard_roundtrip_and_cancel_preserve_original_entry(qtbot):
    weights = [0, 2.5, 7.5, 30]
    entry = QuestionEntry(
        "multilevel_dropdown", weights, option_count=4, custom_weights=list(weights), question_num=1
    )
    info = [
        SurveyQuestionMeta(num=1, title="地区", option_texts=[SEPARATOR.join(p) for p in PATHS])
    ]
    dialog = QuestionWizardDialog([entry], info)
    qtbot.addWidget(dialog)
    assert dialog.get_results()[0] == weights
    dialog.multilevel_map[0]._clear()
    dialog.reject()
    assert entry.custom_weights == weights
    dialog = QuestionWizardDialog([entry], info)
    qtbot.addWidget(dialog)
    dialog.accept()
    assert dialog.result() == QDialog.DialogCode.Accepted
    entry.custom_weights = dialog.get_results()[0]
    entry.probabilities = entry.custom_weights
    restored = deserialize_question_entry(serialize_question_entry(entry))
    assert restored.custom_weights == weights


def test_large_selection_pages_sliders_and_preserves_offscreen_edits(qtbot):
    count = 8000
    entry = QuestionEntry("multilevel_dropdown", -1, option_count=count)
    editor = MultilevelDropdownEditor(
        entry,
        [SEPARATOR.join((f"省{i // 1000}", f"市{i // 50}", f"学校{i}")) for i in range(count)],
    )
    qtbot.addWidget(editor)
    editor.resize(900, 700)
    editor.show()
    distribution = editor.distribution
    assert len(distribution.sliders) == 60
    assert len(editor.findChildren(QWidget)) < 500
    distribution.sliders[0].setValue(300)
    qtbot.mouseClick(distribution.next_button, Qt.MouseButton.LeftButton)
    assert 0 not in distribution.sliders
    distribution.sliders[60].setValue(500)
    editor.search_edit.setText("学校7999")
    editor._filter()
    assert set(distribution.sliders) == {7999}
    distribution.sliders[7999].setValue(700)
    editor.search_edit.clear()
    editor._filter()
    assert distribution.sliders[0].value() == 300
    assert editor.get_weights()[0] == 3
    assert editor.get_weights()[60] == 5
    assert editor.get_weights()[-1] == 7
    editor.paths.select(list(range(50, count)), False)
    editor.only_selected.setChecked(True)
    assert not distribution.pager.isVisible()
    assert len(distribution.sliders) == 50
    assert sum(editor.get_weights()) == 52


@pytest.mark.parametrize("theme", [Theme.LIGHT, Theme.DARK])
def test_editor_reflows_at_narrow_width(qtbot, theme):
    setTheme(theme)
    try:
        editor = _editor(qtbot)
        editor.resize(420, 700)
        qtbot.wait(20)
        assert editor.distribution.width() <= editor.width()
        assert editor.distribution.sliders[0].isVisible()
        ratio = editor.distribution.ratio_labels[0]
        assert ratio.text() == "25.0%"
        assert ratio.lightColor == QColor("#ffb900")
        assert ratio.darkColor == QColor("#ffb900")
        assert editor.distribution.scroll_area.horizontalScrollBar().maximum() == 0
    finally:
        setTheme(Theme.AUTO)
