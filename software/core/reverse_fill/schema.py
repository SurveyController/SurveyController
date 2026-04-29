"""Reverse fill schema and shared constants."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Any, Deque, Dict, List, Optional

REVERSE_FILL_FORMAT_AUTO = "auto"
REVERSE_FILL_FORMAT_WJX_SEQUENCE = "wjx_sequence"
REVERSE_FILL_FORMAT_WJX_SCORE = "wjx_score"
REVERSE_FILL_FORMAT_WJX_TEXT = "wjx_text"
REVERSE_FILL_SUPPORTED_FORMATS = {
    REVERSE_FILL_FORMAT_AUTO,
    REVERSE_FILL_FORMAT_WJX_SEQUENCE,
    REVERSE_FILL_FORMAT_WJX_SCORE,
    REVERSE_FILL_FORMAT_WJX_TEXT,
}

REVERSE_FILL_STATUS_REVERSE = "reverse_fill"
REVERSE_FILL_STATUS_FALLBACK = "fallback_config"
REVERSE_FILL_STATUS_BLOCKED = "blocked"

REVERSE_FILL_KIND_CHOICE = "choice"
REVERSE_FILL_KIND_TEXT = "text"
REVERSE_FILL_KIND_MULTI_TEXT = "multi_text"
REVERSE_FILL_KIND_MATRIX = "matrix"

REVERSE_FILL_RUNTIME_SUPPORTED_TYPES = {
    "single",
    "dropdown",
    "scale",
    "score",
    "text",
    "multi_text",
    "matrix",
}


def reverse_fill_format_label(format_key: str) -> str:
    normalized = str(format_key or REVERSE_FILL_FORMAT_AUTO).strip().lower()
    return {
        REVERSE_FILL_FORMAT_AUTO: "自动识别",
        REVERSE_FILL_FORMAT_WJX_SEQUENCE: "问卷星按序号",
        REVERSE_FILL_FORMAT_WJX_SCORE: "问卷星按分数",
        REVERSE_FILL_FORMAT_WJX_TEXT: "问卷星按文本",
    }.get(normalized, "未知格式")


@dataclass(frozen=True)
class ReverseFillColumn:
    column_index: int
    header: str
    question_num: int
    suffix: str = ""


@dataclass(frozen=True)
class ReverseFillRawRow:
    data_row_number: int
    worksheet_row_number: int
    values_by_column: Dict[int, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class WjxExcelExport:
    source_path: str
    detected_format: str
    selected_format: str
    header_row_number: int
    total_data_rows: int
    question_columns: Dict[int, List[ReverseFillColumn]] = field(default_factory=dict)
    raw_rows: List[ReverseFillRawRow] = field(default_factory=list)


@dataclass(frozen=True)
class ReverseFillAnswer:
    question_num: int
    kind: str
    choice_index: Optional[int] = None
    text_value: str = ""
    text_values: List[str] = field(default_factory=list)
    matrix_choice_indexes: List[int] = field(default_factory=list)


@dataclass(frozen=True)
class ReverseFillSampleRow:
    data_row_number: int
    worksheet_row_number: int
    answers: Dict[int, ReverseFillAnswer] = field(default_factory=dict)


@dataclass(frozen=True)
class ReverseFillIssue:
    question_num: int
    title: str
    severity: str
    category: str
    reason: str
    suggestion: str
    sample_rows: List[int] = field(default_factory=list)


@dataclass(frozen=True)
class ReverseFillQuestionPlan:
    question_num: int
    title: str
    question_type: str
    status: str
    column_headers: List[str] = field(default_factory=list)
    detail: str = ""
    fallback_ready: bool = False


@dataclass(frozen=True)
class ReverseFillSpec:
    source_path: str
    selected_format: str
    detected_format: str
    start_row: int
    total_samples: int
    available_samples: int
    target_num: int
    question_plans: List[ReverseFillQuestionPlan] = field(default_factory=list)
    issues: List[ReverseFillIssue] = field(default_factory=list)
    samples: List[ReverseFillSampleRow] = field(default_factory=list)

    @property
    def blocking_issues(self) -> List[ReverseFillIssue]:
        return [issue for issue in self.issues if str(issue.severity or "").strip().lower() == "block"]

    @property
    def blocking_issue_count(self) -> int:
        return len(self.blocking_issues)


@dataclass
class ReverseFillRuntimeState:
    spec: ReverseFillSpec
    queued_row_numbers: Deque[int] = field(default_factory=deque)
    samples_by_row_number: Dict[int, ReverseFillSampleRow] = field(default_factory=dict)
    reserved_row_by_thread: Dict[str, int] = field(default_factory=dict)
    failure_count_by_row: Dict[int, int] = field(default_factory=dict)
    committed_row_numbers: set[int] = field(default_factory=set)
    discarded_row_numbers: set[int] = field(default_factory=set)


@dataclass(frozen=True)
class ReverseFillAcquireResult:
    status: str
    sample: Optional[ReverseFillSampleRow] = None
    message: str = ""

