from pathlib import Path

import pytest
from openpyxl import Workbook

from software.core.reverse_fill.validation import build_reverse_fill_spec
from surveycore.core.reverse_fill.schema import (
    ReverseFillAnswer,
    ReverseFillSampleRow,
    ReverseFillSpec,
)
from surveycore.providers.contracts import SurveyQuestionMeta
from surveycore.core.questions.schema import QuestionEntry
from software.core.task import ExecutionConfig, ExecutionState
from wjx.provider.answering_builders import build_answer_action
from wjx.provider.http_runtime import _submitdata_answer


@pytest.fixture(params=["sequence", "text"])
def multiple_export(tmp_path: Path, request) -> Path:
    path = tmp_path / "multiple.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    assert sheet is not None
    if request.param == "sequence":
        sheet.append(["序号", "5、标题(选项1)", "5、(选项2)", "5、(选项3)"])
    else:
        sheet.append(["序号", "5、标题"])
    for number, values in enumerate(
        [[1, 0, 0], [0, 1, 0], [0, 0, 1], [1, 1, 0], [1, 0, 1], [0, 1, 1], [1, 1, 1]],
        start=1,
    ):
        if request.param == "sequence":
            sheet.append([number, *values])
        else:
            text = "┋".join(f"选项{index + 1}" for index, selected in enumerate(values) if selected)
            sheet.append([number, text])
    workbook.save(path)
    workbook.close()
    return path


def test_multiple_preflight_covers_every_nonempty_combination(multiple_export: Path) -> None:
    spec = build_reverse_fill_spec(
        source_path=str(multiple_export),
        survey_provider="wjx",
        questions_info=[
            {
                "num": 5,
                "title": "标题",
                "type_code": "4",
                "required": True,
                "option_texts": ["选项1", "选项2", "选项3"],
            }
        ],
        question_entries=[],
    )
    assert not spec.issues
    assert spec.question_plans[0].status == "reverse_fill"
    assert [sample.answers[5].choice_indexes for sample in spec.samples] == [
        [0],
        [1],
        [2],
        [0, 1],
        [0, 2],
        [1, 2],
        [0, 1, 2],
    ]


@pytest.mark.asyncio
async def test_multiple_reverse_fill_replays_exact_selected_indexes() -> None:
    question = SurveyQuestionMeta(
        num=5,
        title="标题",
        type_code="4",
        options=3,
        option_texts=["选项1", "选项2", "选项3"],
        multi_min_limit=1,
        multi_max_limit=3,
    )
    config = ExecutionConfig()
    config.question_config_index_map[5] = ("multiple", 0)
    config.multiple_prob = [[100.0, 100.0, 100.0]]
    config.reverse_fill_spec = ReverseFillSpec(
        source_path="demo.xlsx",
        selected_format="wjx_sequence",
        detected_format="wjx_sequence",
        start_row=1,
        total_samples=1,
        available_samples=1,
        target_num=1,
        samples=[
            ReverseFillSampleRow(
                data_row_number=1,
                worksheet_row_number=2,
                answers={
                    5: ReverseFillAnswer(question_num=5, kind="choices", choice_indexes=[2, 0])
                },
            )
        ],
    )
    state = ExecutionState(config=config)
    state.initialize_reverse_fill_runtime()
    state.acquire_reverse_fill_sample("Worker-1")
    action = await build_answer_action(
        None, question, state, psycho_plan=None, thread_name="Worker-1"
    )
    assert action is not None
    assert action.selected_indices == (2, 0)
    assert _submitdata_answer(action) == "3|1"


@pytest.mark.parametrize("fallback_ready", [False, True])
def test_multiple_preflight_rejects_out_of_limit_samples(
    multiple_export: Path, fallback_ready: bool
) -> None:
    entries = (
        [
            QuestionEntry(
                question_type="multiple",
                probabilities=[100.0, 100.0, 0.0],
                option_count=3,
                question_num=5,
                question_title="标题",
            )
        ]
        if fallback_ready
        else []
    )
    spec = build_reverse_fill_spec(
        source_path=str(multiple_export),
        survey_provider="wjx",
        questions_info=[
            {
                "num": 5,
                "title": "标题",
                "type_code": "4",
                "required": True,
                "option_texts": ["选项1", "选项2", "选项3"],
                "multi_max_limit": 2,
            }
        ],
        question_entries=entries,
    )
    assert spec.issues[0].category == "unsupported_value"
    assert spec.issues[0].sample_rows == [7]
    assert spec.blocking_issue_count == (0 if fallback_ready else 1)
    assert spec.question_plans[0].status == ("fallback_config" if fallback_ready else "blocked")
    assert all(5 not in sample.answers for sample in spec.samples)
