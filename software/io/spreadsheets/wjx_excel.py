"""Read WJX Excel exports into a normalized raw structure."""

from __future__ import annotations

import os
import re
from typing import Any, Dict, Iterable, List

from software.core.reverse_fill.schema import (
    REVERSE_FILL_FORMAT_AUTO,
    REVERSE_FILL_FORMAT_WJX_SCORE,
    REVERSE_FILL_FORMAT_WJX_SEQUENCE,
    REVERSE_FILL_FORMAT_WJX_TEXT,
    ReverseFillColumn,
    ReverseFillRawRow,
    WjxExcelExport,
)

_QUESTION_HEADER_RE = re.compile(r"^\s*(\d+)\s*[、,.，．]\s*(.*?)\s*$")
_SEQUENCE_SUFFIX_RE = re.compile(r"^\(\s*选项\s*\d+\s*\)$")


def _cell_text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    return text


def _iter_question_values(raw_rows: Iterable[ReverseFillRawRow], question_columns: Dict[int, List[ReverseFillColumn]]) -> Iterable[Any]:
    column_indexes: List[int] = []
    for columns in question_columns.values():
        for column in columns:
            column_indexes.append(int(column.column_index))
    seen = set(column_indexes)
    if not seen:
        return []
    collected: List[Any] = []
    for row in raw_rows:
        values_by_column = row.values_by_column if isinstance(row.values_by_column, dict) else {}
        for column_index in column_indexes:
            collected.append(values_by_column.get(column_index))
    return collected


def _detect_wjx_export_format(question_columns: Dict[int, List[ReverseFillColumn]], raw_rows: List[ReverseFillRawRow]) -> str:
    for columns in question_columns.values():
        if len(columns) <= 1:
            continue
        if any(_SEQUENCE_SUFFIX_RE.match(str(column.suffix or "").strip()) for column in columns):
            return REVERSE_FILL_FORMAT_WJX_SEQUENCE

    has_numeric_type = False
    has_numeric_string = False
    has_string_marker = False
    for value in _iter_question_values(raw_rows[:5], question_columns):
        if value is None:
            continue
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float)):
            has_numeric_type = True
            continue
        text = _cell_text(value)
        if not text:
            continue
        if "〖" in text and "〗" in text:
            has_string_marker = True
        if re.fullmatch(r"\d+(?:\.0+)?", text):
            has_numeric_string = True
            continue
        has_string_marker = True
    if has_string_marker and not has_numeric_type and has_numeric_string:
        return REVERSE_FILL_FORMAT_WJX_TEXT
    if has_numeric_type:
        return REVERSE_FILL_FORMAT_WJX_SCORE
    return REVERSE_FILL_FORMAT_WJX_TEXT


def load_wjx_excel_export(source_path: str, *, preferred_format: str = REVERSE_FILL_FORMAT_AUTO) -> WjxExcelExport:
    from openpyxl import load_workbook

    path = os.path.abspath(str(source_path or "").strip())
    if not path:
        raise ValueError("未提供 Excel 文件路径")
    if not os.path.exists(path):
        raise ValueError(f"Excel 文件不存在：{path}")

    workbook = load_workbook(path, read_only=True, data_only=True)
    try:
        if not workbook.sheetnames:
            raise ValueError("Excel 中没有可读取的工作表")
        worksheet = workbook[workbook.sheetnames[0]]
        rows_iter = worksheet.iter_rows(values_only=False)
        header_cells = next(rows_iter, None)
        if not header_cells:
            raise ValueError("Excel 缺少表头，无法识别问卷列")

        question_columns: Dict[int, List[ReverseFillColumn]] = {}
        for cell in list(header_cells):
            header = _cell_text(cell.value)
            match = _QUESTION_HEADER_RE.match(header)
            if not match:
                continue
            question_num = int(match.group(1))
            suffix = str(match.group(2) or "").strip()
            raw_column = cell.column
            if raw_column is None:
                continue
            column_index = int(raw_column)
            question_columns.setdefault(question_num, []).append(
                ReverseFillColumn(
                    column_index=column_index,
                    header=header,
                    question_num=question_num,
                    suffix=suffix,
                )
            )

        raw_rows: List[ReverseFillRawRow] = []
        for data_row_number, row_cells in enumerate(rows_iter, start=1):
            values_by_column: Dict[int, Any] = {}
            for column_list in question_columns.values():
                for column in column_list:
                    position = int(column.column_index) - 1
                    raw_value = row_cells[position].value if position < len(row_cells) else None
                    values_by_column[int(column.column_index)] = raw_value
            raw_rows.append(
                ReverseFillRawRow(
                    data_row_number=data_row_number,
                    worksheet_row_number=data_row_number + 1,
                    values_by_column=values_by_column,
                )
            )

        detected_format = _detect_wjx_export_format(question_columns, raw_rows)
        selected_format = str(preferred_format or REVERSE_FILL_FORMAT_AUTO).strip().lower()
        if selected_format == REVERSE_FILL_FORMAT_AUTO:
            selected_format = detected_format
        return WjxExcelExport(
            source_path=path,
            detected_format=detected_format,
            selected_format=selected_format,
            header_row_number=1,
            total_data_rows=len(raw_rows),
            question_columns=question_columns,
            raw_rows=raw_rows,
        )
    finally:
        workbook.close()
