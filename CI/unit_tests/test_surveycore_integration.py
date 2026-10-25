from __future__ import annotations

import json
import threading
from collections import deque
from datetime import datetime
from importlib.metadata import version
from pathlib import Path

import pytest
import surveycore
from openpyxl import Workbook

from surveycore.core.questions.default_builder import build_default_question_entries
from surveycore.core.questions.distribution import (
    record_pending_distribution_choice,
    resolve_distribution_probabilities,
)
from surveycore.core.questions.normalization import configure_probabilities
from surveycore.core.questions.schema import QuestionEntry
from surveycore.core.questions.utils import _load_id_card_area_codes, generate_random_id_card
from surveycore.core.reverse_fill.schema import (
    REVERSE_FILL_FORMAT_WJX_SEQUENCE,
    REVERSE_FILL_KIND_TEXT,
    REVERSE_FILL_STATUS_REVERSE,
    ReverseFillAnswer,
    ReverseFillSampleRow,
    ReverseFillSpec,
)
from surveycore.providers.answering import AnswerAction
from surveycore.providers.answering.recording import record_answer_action
from surveycore.providers.contracts import build_survey_definition
from surveycore.wjx.provider.html_parser import parse_survey_questions_from_html

from software.core.config.codec import deserialize_runtime_config, serialize_runtime_config
from software.core.config.schema import RuntimeConfig
from software.core.engine.run_stop_policy import RunStopPolicy
from software.core.reverse_fill.validation import build_reverse_fill_spec
from software.core.task import ExecutionConfig, ExecutionState, ProxyLease


def test_library_parser_output_survives_application_config_and_reverse_fill(tmp_path: Path) -> None:
    questions = build_survey_definition(
        "wjx",
        "日常调查",
        parse_survey_questions_from_html(
            """
            <div id="divQuestion"><fieldset>
              <div topic="1" id="div1" type="3">
                <div class="topichtml">1. 使用频率</div>
                <div class="ui-controlgroup">
                  <div><span class="label">每天</span></div>
                  <div><span class="label">每周</span></div>
                </div>
              </div>
              <div topic="2" id="div2" type="1">
                <div class="topichtml">2. 职业</div><input type="text" />
              </div>
            </fieldset></div>
            """
        ),
    ).questions
    entries = build_default_question_entries(questions)
    entries[1].ai_enabled = True
    config = RuntimeConfig(
        url="https://www.wjx.cn/vm/offline.aspx",
        questions_info=questions,
        question_entries=entries,
        target=1,
        random_ip_enabled=True,
        proxy_source="custom",
        custom_proxy_api="https://proxy.example.test/api",
        answer_datetime_window=("2026-10-12 09:00:00", "2026-10-12 10:00:00"),
    )

    restored = deserialize_runtime_config(json.loads(json.dumps(serialize_runtime_config(config))))

    assert [(question.num, question.title) for question in restored.questions_info or []] == [
        (1, "使用频率"),
        (2, "职业"),
    ]
    assert restored.questions_info[0].option_texts == ["每天", "每周"]
    assert [entry.question_type for entry in restored.question_entries] == ["single", "text"]
    assert restored.question_entries[1].ai_enabled is True
    assert restored.random_ip_enabled is True
    assert restored.custom_proxy_api == "https://proxy.example.test/api"
    assert restored.answer_datetime_window == config.answer_datetime_window

    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["序号", "1、使用频率", "2、职业"])
    sheet.append([1, 2, "教师"])
    source = tmp_path / "sample.xlsx"
    workbook.save(source)
    workbook.close()
    spec = build_reverse_fill_spec(
        source_path=str(source),
        survey_provider=restored.survey_provider,
        questions_info=restored.questions_info or [],
        question_entries=restored.question_entries,
        selected_format=REVERSE_FILL_FORMAT_WJX_SEQUENCE,
        target_num=restored.target,
    )

    assert spec.blocking_issue_count == 0
    assert [plan.status for plan in spec.question_plans] == [REVERSE_FILL_STATUS_REVERSE] * 2
    assert spec.samples[0].answers[1].choice_index == 1
    assert spec.samples[0].answers[2].text_value == "教师"


def test_library_answers_commit_shared_samples_and_keep_application_proxy_state() -> None:
    lease = ProxyLease(address="http://127.0.0.1:8123", source="custom")
    spec = ReverseFillSpec(
        source_path="offline.xlsx",
        selected_format=REVERSE_FILL_FORMAT_WJX_SEQUENCE,
        detected_format=REVERSE_FILL_FORMAT_WJX_SEQUENCE,
        start_row=1,
        total_samples=2,
        available_samples=2,
        target_num=2,
        samples=[
            ReverseFillSampleRow(
                data_row_number=row,
                worksheet_row_number=row + 1,
                answers={2: ReverseFillAnswer(2, REVERSE_FILL_KIND_TEXT, text_value=text)},
            )
            for row, text in [(1, "第一份"), (2, "第二份")]
        ],
    )
    config = ExecutionConfig(
        target_num=2,
        random_proxy_ip_enabled=True,
        proxy_source="custom",
        proxy_ip_pool=deque([lease]),
        answer_datetime_window_ms=(1000, 2000),
        reverse_fill_spec=spec,
    )
    configure_probabilities(
        [
            QuestionEntry(
                "single", [75, 25], option_count=2, question_num=1, distribution_mode="custom"
            )
        ],
        config,
        reliability_mode_enabled=False,
    )
    assert config.single_prob == [[0.75, 0.25]]
    assert config.question_strict_ratio_map == {1: True}
    assert config.answer_datetime_window_ms == (1000, 2000)
    assert list(config.proxy_ip_pool)[0].address == lease.address

    state = ExecutionState(config=config)
    state.initialize_reverse_fill_runtime()
    worker = threading.current_thread().name
    state.mark_proxy_in_use(worker, lease)
    policy = RunStopPolicy(config, state)
    stop = threading.Event()
    recorded_answers: list[tuple[int, str, dict]] = []

    def record_answer(number: int, kind: str, **values: object) -> None:
        recorded_answers.append((number, kind, values))

    for sample_index, selected_index in [(0, 0), (1, 1)]:
        assert state.reserve_joint_sample(2, worker) == sample_index
        acquired = state.acquire_reverse_fill_sample(worker)
        assert acquired.sample is not None
        assert acquired.sample.data_row_number == sample_index + 1
        record_answer_action(
            state,
            AnswerAction(
                question_num=1,
                kind="choice",
                record_type="single",
                selected_indices=(selected_index,),
                pending_distribution_choices=((selected_index, 2, None),),
            ),
            record_answer_fn=record_answer,
            record_pending_distribution_choice_fn=record_pending_distribution_choice,
            default_fill_text="已填写",
        )
        assert state.snapshot_distribution_stats("q:1", 2)[0] == sample_index
        assert policy.record_success(stop, thread_name=worker) is (sample_index == 1)
        if sample_index == 0:
            corrected = resolve_distribution_probabilities(config.single_prob[0], 2, state, 1)
            assert corrected[0] < 0.75
            assert corrected[1] > 0.25
            assert not stop.is_set()

    assert [answer[2]["selected_indices"] for answer in recorded_answers] == [[0], [1]]
    assert state.snapshot_distribution_stats("q:1", 2) == (2, [1, 1])
    assert state.joint_committed_sample_indexes == {0, 1}
    assert state.reverse_fill_runtime is not None
    assert state.reverse_fill_runtime.committed_row_numbers == {1, 2}
    assert state.snapshot_active_proxy_addresses() == {lease.address}
    assert state.release_proxy_in_use(worker) == lease
    assert state.snapshot_active_proxy_addresses() == set()
    assert state.get_terminal_stop_snapshot()[0] == "target_reached"
    with pytest.raises(AttributeError, match="state.config.proxy_source"):
        state.proxy_source = "default"


def test_application_target_counts_successful_submissions_after_failures() -> None:
    config = ExecutionConfig(target_num=3, fail_threshold=5)
    state = ExecutionState(config=config)
    policy = RunStopPolicy(config, state)
    stop = threading.Event()

    assert policy.record_success(stop) is False
    assert policy.record_failure(stop) is False
    assert state.cur_num == 1
    assert state.cur_fail == 1
    assert not stop.is_set()
    assert policy.record_success(stop) is False
    assert state.cur_num == 2
    assert state.cur_fail == 0
    assert not stop.is_set()
    assert policy.record_success(stop) is True
    assert state.cur_num == 3
    assert stop.is_set()
    assert policy.record_success(stop) is True
    assert state.cur_num == 3


def test_installed_core_resources_and_version_support_id_card_generation() -> None:
    assert surveycore.__version__ == version("surveycore-py") == "0.1.0"
    _load_id_card_area_codes.cache_clear()
    area_codes = _load_id_card_area_codes()
    assert len(area_codes) >= 300
    assert {"320500", "650100"}.issubset(area_codes)

    id_card = generate_random_id_card()

    assert len(id_card) == 18
    assert id_card[:17].isdigit()
    assert id_card[:6] in area_codes
    datetime.strptime(id_card[6:14], "%Y%m%d")
    # GB 11643 的 MOD 11-2 校验关系，独立于核心库的生成函数。
    weights = (7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2)
    checksum = sum(int(digit) * weight for digit, weight in zip(id_card[:17], weights, strict=True))
    assert id_card[-1] == "10X98765432"[checksum % 11]
