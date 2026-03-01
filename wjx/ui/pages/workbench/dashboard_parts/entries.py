"""DashboardPage 题目表格与批量编辑相关方法。"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, List, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QTableWidgetItem
from qfluentwidgets import MessageBox

from wjx.core.questions.config import QuestionEntry
from wjx.ui.pages.workbench.question import QuestionWizardDialog, _get_entry_type_label
from wjx.ui.pages.workbench.question.psycho_config import PSYCHO_SUPPORTED_TYPES

_TEXT_RANDOM_NAME_TOKEN = "__RANDOM_NAME__"
_TEXT_RANDOM_MOBILE_TOKEN = "__RANDOM_MOBILE__"


def _pretty_text_answer(value: Any) -> str:
    text = str(value or "").strip()
    if text == _TEXT_RANDOM_NAME_TOKEN:
        return "随机姓名"
    if text == _TEXT_RANDOM_MOBILE_TOKEN:
        return "随机手机号"
    return text


def question_summary(entry: QuestionEntry) -> str:
    """生成题目配置摘要"""
    if getattr(entry, "question_type", "") in PSYCHO_SUPPORTED_TYPES and bool(getattr(entry, "psycho_enabled", False)):
        bias_text = {
            "left": "低分倾向",
            "center": "中立",
            "right": "高分倾向",
        }.get(str(getattr(entry, "psycho_bias", "center") or "center"), "中立")
        return f"倾向模式: {bias_text}"

    if entry.question_type in ("text", "multi_text"):
        if entry.question_type == "text":
            random_mode = str(getattr(entry, "text_random_mode", "none") or "none").strip().lower()
            if random_mode == "name":
                return "答案: 随机姓名"
            if random_mode == "mobile":
                return "答案: 随机手机号"
        texts = entry.texts or []
        if texts:
            preview = [_pretty_text_answer(text) for text in texts[:2]]
            summary = f"答案: {' | '.join(preview)}"
            if len(texts) > 2:
                summary += f" (+{len(texts)-2})"
            if entry.question_type == "text" and getattr(entry, "ai_enabled", False):
                summary += " | AI"
            return summary
        summary = "答案: 无"
        if entry.question_type == "text" and getattr(entry, "ai_enabled", False):
            summary += " | AI"
        return summary
    if entry.question_type == "matrix":
        rows = max(1, int(entry.rows or 1))
        cols = max(1, int(entry.option_count or 1))
        if isinstance(entry.custom_weights, list) or isinstance(entry.probabilities, list):
            return f"{rows} 行 × {cols} 列 - 按行配比"
        return f"{rows} 行 × {cols} 列 - 完全随机"
    if entry.question_type == "order":
        return "排序题 - 自动随机排序"
    if entry.custom_weights and not isinstance(entry.custom_weights[0], list):
        weights = entry.custom_weights
        if entry.question_type == "multiple":
            summary = f"自定义概率: {','.join(f'{int(w)}%' for w in weights[:4] if isinstance(w, (int, float)))}"
        else:
            summary = f"自定义配比: {','.join(str(int(w)) for w in weights[:4] if isinstance(w, (int, float)))}"
        if len(weights) > 4:
            summary += "..."
        return summary

    strategy = entry.distribution_mode or "random"
    if strategy not in ("random", "custom"):
        strategy = "random"
    if getattr(entry, "probabilities", None) == -1:
        strategy = "random"
    if entry.question_type == "multiple":
        return "完全随机" if strategy == "random" else "自定义概率"
    return "完全随机" if strategy == "random" else "自定义配比"


class DashboardEntriesMixin:
    """题目配置表与编辑向导相关方法。"""

    if TYPE_CHECKING:
        question_page: Any
        _toast: Any
        entry_table: Any
        count_label: Any
        _sync_start_button_state: Any
        _survey_title: Any
        runtime_page: Any
        window: Any

    def _show_add_question_dialog(self):
        """新增题目 - 委托给 QuestionPage"""
        self.question_page._add_entry()
        self._refresh_entry_table()

    def _open_question_wizard(self):
        if self._run_question_wizard(self.question_page.entries, self.question_page.questions_info):
            self._refresh_entry_table()

    def _edit_selected_entries(self):
        selected_rows = self._checked_rows()
        if not selected_rows:
            self._toast("请先勾选要编辑的题目", "warning")
            return
        entries = self.question_page.get_entries()
        info = self.question_page.questions_info or []
        selected_rows = [row for row in sorted(set(selected_rows)) if 0 <= row < len(entries)]
        if not selected_rows:
            self._toast("未找到可编辑的题目", "warning")
            return
        selected_entries = [entries[row] for row in selected_rows]
        selected_info = [info[row] if row < len(info) else {} for row in selected_rows]
        if self._run_question_wizard(selected_entries, selected_info):
            self._refresh_entry_table()

    def _apply_wizard_results(self, entries: List[QuestionEntry], dlg: QuestionWizardDialog) -> None:
        def _build_bias_weights(option_count: int, bias: str) -> List[float]:
            count = max(1, int(option_count or 1))
            if count == 1:
                return [1.0]
            if bias == "left":
                return [float(count - i) for i in range(count)]
            if bias == "right":
                return [float(i + 1) for i in range(count)]
            center = (count - 1) / 2.0
            return [float(count - abs(i - center)) for i in range(count)]

        def _normalize_weights(raw: Any) -> Any:
            if isinstance(raw, list) and any(isinstance(item, (list, tuple)) for item in raw):
                cleaned: List[List[float]] = []
                for row in raw:
                    if not isinstance(row, (list, tuple)):
                        continue
                    cleaned.append([float(max(0, v)) for v in row])
                return cleaned
            if isinstance(raw, list):
                return [float(max(0, v)) for v in raw]
            return raw

        answer_mode = str(getattr(dlg, "get_answer_mode", lambda: "weights")() or "weights")
        if answer_mode not in ("weights", "tendency"):
            answer_mode = "weights"

        updates = dlg.get_results() if answer_mode == "weights" else {}
        for idx, weights in updates.items():
            if 0 <= idx < len(entries):
                entry = entries[idx]
                normalized = _normalize_weights(weights)
                if entry.question_type == "matrix":
                    entry.custom_weights = normalized
                    entry.probabilities = normalized
                    entry.distribution_mode = "custom"
                elif isinstance(normalized, list):
                    entry.custom_weights = normalized
                    entry.probabilities = normalized
                    entry.distribution_mode = "custom"
        text_updates = dlg.get_text_results()
        for idx, texts in text_updates.items():
            if 0 <= idx < len(entries):
                entries[idx].texts = texts
        random_mode_updates = dlg.get_text_random_modes()
        for idx, random_mode in random_mode_updates.items():
            if 0 <= idx < len(entries):
                entry = entries[idx]
                entry.text_random_mode = str(random_mode or "none") if entry.question_type == "text" else "none"
        ai_updates = dlg.get_ai_flags()
        for idx, enabled in ai_updates.items():
            if 0 <= idx < len(entries):
                entry = entries[idx]
                entry.ai_enabled = bool(enabled) if entry.question_type == "text" else False
        reverse_updates = dlg.get_reverse_results()
        for idx, rev_val in reverse_updates.items():
            if 0 <= idx < len(entries):
                entry = entries[idx]
                if isinstance(rev_val, list):
                    # 矩阵题：按行存储
                    entry.row_reverse_flags = [bool(v) for v in rev_val]
                    entry.is_reverse = any(entry.row_reverse_flags)
                else:
                    entry.is_reverse = bool(rev_val)
        
        # 应用潜变量模式配置
        psycho_updates = dlg.get_psycho_results()
        for idx, psycho_config in psycho_updates.items():
            if 0 <= idx < len(entries):
                entry = entries[idx]
                entry.psycho_enabled = psycho_config.get("psycho_enabled", False)
                entry.psycho_bias = psycho_config.get("psycho_bias", "center")

        # 互斥生效：作答时只能使用一种模式
        if answer_mode == "weights":
            for entry in entries:
                entry.psycho_enabled = False
        else:
            for idx, entry in enumerate(entries):
                if entry.question_type not in PSYCHO_SUPPORTED_TYPES:
                    continue
                psycho_config = psycho_updates.get(idx, {})
                enabled = bool(psycho_config.get("psycho_enabled", False))
                bias = str(psycho_config.get("psycho_bias", "center") or "center")
                entry.psycho_enabled = enabled
                entry.psycho_bias = bias
                if not enabled:
                    entry.distribution_mode = "random"
                    entry.custom_weights = None
                    entry.probabilities = -1
                    continue
                option_count = max(1, int(getattr(entry, "option_count", 1) or 1))
                bias_weights = _build_bias_weights(option_count, bias)
                if entry.question_type == "matrix":
                    rows = max(1, int(getattr(entry, "rows", 1) or 1))
                    matrix_weights = [list(bias_weights) for _ in range(rows)]
                    entry.custom_weights = matrix_weights
                    entry.probabilities = matrix_weights
                else:
                    entry.custom_weights = list(bias_weights)
                    entry.probabilities = list(bias_weights)
                entry.distribution_mode = "custom"

    def _run_question_wizard(self, entries: List[QuestionEntry], info: List[Dict[str, Any]], survey_title: Optional[str] = None) -> bool:
        if not entries:
            self._toast("请先解析问卷或手动添加题目", "warning")
            return False
        title = survey_title if survey_title is not None else self._survey_title
        reliability_mode_enabled = getattr(self.runtime_page.reliability_mode_switch, "isChecked", lambda: True)()
        try:
            ai_master_enabled = self.runtime_page.ai_section.ai_enabled_card.isChecked()
        except Exception:
            ai_master_enabled = True
        dlg = QuestionWizardDialog(entries, info, title, self, reliability_mode_enabled=reliability_mode_enabled, ai_master_enabled=ai_master_enabled)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._apply_wizard_results(entries, dlg)
            return True
        return False

    def _delete_selected_entries(self):
        selected_rows = self._checked_rows()
        if not selected_rows:
            self._toast("请先勾选要删除的题目", "warning")
            return

        count = len(selected_rows)
        box = MessageBox(
            "确认删除",
            f"确定要删除选中的 {count} 个题目吗？\n此操作无法撤销。",
            self.window() or self,
        )
        box.yesButton.setText("确定")
        box.cancelButton.setText("取消")
        if not box.exec():
            return

        entries = self.question_page.get_entries()
        for row in sorted(selected_rows, reverse=True):
            if 0 <= row < len(entries):
                entries.pop(row)
        self.question_page.set_entries(entries, self.question_page.questions_info)
        self._refresh_entry_table()
        self._toast(f"已删除 {count} 个题目", "success")

    def _refresh_entry_table(self):
        entries = self.question_page.get_entries()
        self.entry_table.setRowCount(len(entries))
        self.count_label.setText(f"{len(entries)} 题")
        for idx, entry in enumerate(entries):
            # 序号列（从1开始）
            seq_item = QTableWidgetItem(str(idx + 1))
            seq_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.entry_table.setItem(idx, 0, seq_item)
            
            # 类型列
            type_label = _get_entry_type_label(entry)
            type_item = QTableWidgetItem(type_label)
            type_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.entry_table.setItem(idx, 1, type_item)
            
            # 策略列
            summary = question_summary(entry)
            self.entry_table.setItem(idx, 2, QTableWidgetItem(summary))
        self._sync_start_button_state()

    def _checked_rows(self) -> List[int]:
        return [idx.row() for idx in self.entry_table.selectionModel().selectedRows()]
