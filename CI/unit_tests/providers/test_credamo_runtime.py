from __future__ import annotations
import threading
from types import SimpleNamespace
from unittest.mock import patch
from credamo.provider import runtime

class CredamoRuntimeTests:

    class _FakeQuestionRoot:

        def __init__(self, question_num: int) -> None:
            self.question_num = question_num

    class _FakeChoiceElement:

        def __init__(self, text: str='') -> None:
            self.checked = False
            self.text = text

        def scroll_into_view_if_needed(self, timeout: int=0) -> None:
            return None

        def click(self, timeout: int=0) -> None:
            self.checked = True

        def text_content(self, timeout: int=0) -> str:
            return self.text

    class _FakeDropdownInput:

        def __init__(self) -> None:
            self.value = ''

        def scroll_into_view_if_needed(self, timeout: int=0) -> None:
            return None

        def click(self, timeout: int=0) -> None:
            return None

        def focus(self) -> None:
            return None

    class _FakeDropdownLocator:

        def __init__(self, count_value: int) -> None:
            self._count_value = count_value

        def count(self) -> int:
            return self._count_value

    def test_click_submit_waits_until_dynamic_button_appears(self, restore_credamo_runtime_patchpoints) -> None:
        attempts = iter([False, False, True])
        with patch('credamo.provider.runtime._click_submit_once', side_effect=lambda _page: next(attempts)), patch('credamo.provider.runtime.time.sleep') as sleep_mock:
            clicked = runtime._click_submit(object(), timeout_ms=2000)
        assert clicked
        assert sleep_mock.call_count == 2

    def test_click_submit_stops_waiting_when_abort_requested(self, restore_credamo_runtime_patchpoints) -> None:
        stop_signal = threading.Event()

        def abort_after_first_wait(_seconds: float | None=None) -> bool:
            stop_signal.set()
            return True
        with patch('credamo.provider.runtime._click_submit_once', return_value=False):
            setattr(stop_signal, 'wait', abort_after_first_wait)
            clicked = runtime._click_submit(object(), stop_signal, timeout_ms=2000)
        assert not clicked

    def test_brush_credamo_walks_next_pages_before_submit(self, restore_credamo_runtime_patchpoints) -> None:
        stop_signal = threading.Event()
        state = SimpleNamespace(stop_event=stop_signal, update_thread_step=lambda *args, **kwargs: None, update_thread_status=lambda *args, **kwargs: None)
        config = SimpleNamespace(question_config_index_map={1: ('single', 0), 2: ('dropdown', 0), 3: ('order', -1)}, single_prob=[-1], droplist_prob=[-1], scale_prob=[], multiple_prob=[], texts=[], answer_duration_range_seconds=[0, 0])
        driver = SimpleNamespace(page=object())
        roots_page1 = [self._FakeQuestionRoot(1), self._FakeQuestionRoot(2)]
        roots_page2 = [self._FakeQuestionRoot(3)]
        with patch('credamo.provider.runtime._wait_for_question_roots', side_effect=[roots_page1, roots_page2]), patch('credamo.provider.runtime._wait_for_dynamic_question_roots', side_effect=[roots_page1, roots_page2]), patch('credamo.provider.runtime._question_number_from_root', side_effect=lambda _page, root, _fallback: root.question_num), patch('credamo.provider.runtime._root_text', side_effect=lambda _page, root: f'Q{root.question_num}'), patch('credamo.provider.runtime._navigation_action', side_effect=['next', 'submit']), patch('credamo.provider.runtime._question_signature', side_effect=[(('question-1', 'page1'),)]), patch('credamo.provider.runtime._wait_for_page_change', return_value=True), patch('credamo.provider.runtime._click_navigation', return_value=True) as click_navigation_mock, patch('credamo.provider.runtime._click_submit', return_value=True) as click_submit_mock, patch('credamo.provider.runtime._answer_single_like', return_value=True) as single_mock, patch('credamo.provider.runtime._answer_dropdown', return_value=True) as dropdown_mock, patch('credamo.provider.runtime._answer_order', return_value=True) as order_mock, patch('credamo.provider.runtime.simulate_answer_duration_delay', return_value=False), patch('credamo.provider.runtime.time.sleep'):
            result = runtime.brush_credamo(driver, config, state, stop_signal=stop_signal, thread_name='Worker-1')
        assert result
        assert single_mock.call_count == 1
        assert dropdown_mock.call_count == 1
        assert order_mock.call_count == 1
        click_navigation_mock.assert_called_once_with(driver.page, 'next')
        click_submit_mock.assert_called_once_with(driver.page, stop_signal)

    def test_brush_credamo_answers_questions_revealed_on_same_page(self, restore_credamo_runtime_patchpoints) -> None:
        stop_signal = threading.Event()
        state = SimpleNamespace(stop_event=stop_signal, update_thread_step=lambda *args, **kwargs: None, update_thread_status=lambda *args, **kwargs: None)
        config = SimpleNamespace(question_config_index_map={8: ('single', 0), 9: ('scale', 0)}, single_prob=[[0.0, 1.0, 0.0, 0.0]], droplist_prob=[], scale_prob=[[100.0, 0.0, 0.0, 0.0, 0.0]], multiple_prob=[], texts=[], answer_duration_range_seconds=[0, 0])
        driver = SimpleNamespace(page=object())
        q8 = self._FakeQuestionRoot(8)
        q9 = self._FakeQuestionRoot(9)
        roots_initial = [q8]
        roots_after_reveal = [q8, q9]
        with patch('credamo.provider.runtime._wait_for_question_roots', return_value=roots_initial), patch('credamo.provider.runtime._wait_for_dynamic_question_roots', side_effect=[roots_after_reveal, roots_after_reveal]), patch('credamo.provider.runtime._question_number_from_root', side_effect=lambda _page, root, _fallback: root.question_num), patch('credamo.provider.runtime._root_text', side_effect=lambda _page, root: f'Q{root.question_num}'), patch('credamo.provider.runtime._navigation_action', return_value='submit'), patch('credamo.provider.runtime._click_submit', return_value=True), patch('credamo.provider.runtime._answer_single_like', return_value=True) as single_mock, patch('credamo.provider.runtime._answer_scale', return_value=True) as scale_mock, patch('credamo.provider.runtime.simulate_answer_duration_delay', return_value=False), patch('credamo.provider.runtime.time.sleep'):
            result = runtime.brush_credamo(driver, config, state, stop_signal=stop_signal, thread_name='Worker-1')
        assert result
        assert single_mock.call_count == 1
        assert scale_mock.call_count == 1

    def test_brush_credamo_collects_runtime_snapshot_without_affecting_flow(self, restore_credamo_runtime_patchpoints) -> None:
        stop_signal = threading.Event()
        state = SimpleNamespace(stop_event=stop_signal, update_thread_step=lambda *args, **kwargs: None, update_thread_status=lambda *args, **kwargs: None)
        config = SimpleNamespace(question_config_index_map={8: ('single', 0)}, single_prob=[[-1]], droplist_prob=[], scale_prob=[], multiple_prob=[], texts=[], answer_duration_range_seconds=[0, 0])
        driver = SimpleNamespace(page=object())
        q8 = self._FakeQuestionRoot(8)
        with patch('credamo.provider.runtime._wait_for_question_roots', return_value=[q8]), patch('credamo.provider.runtime._collect_question_root_snapshot', return_value=[{'id': 'q8'}]), patch('credamo.provider.runtime._wait_for_dynamic_question_roots', side_effect=[[q8], [q8]]), patch('credamo.provider.runtime._question_number_from_root', side_effect=lambda _page, root, _fallback: root.question_num), patch('credamo.provider.runtime._root_text', return_value='Q8'), patch('credamo.provider.runtime._navigation_action', return_value='submit'), patch('credamo.provider.runtime._click_submit', return_value=True), patch('credamo.provider.runtime._answer_single_like', return_value=True) as single_mock, patch('credamo.provider.runtime.simulate_answer_duration_delay', return_value=False), patch('credamo.provider.runtime.time.sleep'):
            result = runtime.brush_credamo(driver, config, state, stop_signal=stop_signal, thread_name='Worker-1')
        assert result
        assert single_mock.call_count == 1

    def test_brush_credamo_answers_matrix_with_row_weights(self, restore_credamo_runtime_patchpoints) -> None:
        stop_signal = threading.Event()
        state = SimpleNamespace(stop_event=stop_signal, update_thread_step=lambda *args, **kwargs: None, update_thread_status=lambda *args, **kwargs: None)
        config = SimpleNamespace(question_config_index_map={11: ('matrix', 0)}, questions_metadata={11: SimpleNamespace(rows=3)}, single_prob=[], droplist_prob=[], scale_prob=[], matrix_prob=[[100.0, 0.0, 0.0], [0.0, 100.0, 0.0], [0.0, 0.0, 100.0]], multiple_prob=[], texts=[], answer_duration_range_seconds=[0, 0])
        driver = SimpleNamespace(page=object())
        root = self._FakeQuestionRoot(11)
        with patch('credamo.provider.runtime._wait_for_question_roots', return_value=[root]), patch('credamo.provider.runtime._wait_for_dynamic_question_roots', side_effect=[[root], [root]]), patch('credamo.provider.runtime._question_number_from_root', side_effect=lambda _page, current_root, _fallback: current_root.question_num), patch('credamo.provider.runtime._root_text', return_value='Q11'), patch('credamo.provider.runtime._navigation_action', return_value='submit'), patch('credamo.provider.runtime._click_submit', return_value=True), patch('credamo.provider.runtime._answer_matrix', return_value=True) as matrix_mock, patch('credamo.provider.runtime.simulate_answer_duration_delay', return_value=False), patch('credamo.provider.runtime.time.sleep'):
            result = runtime.brush_credamo(driver, config, state, stop_signal=stop_signal, thread_name='Worker-1')
        assert result
        matrix_mock.assert_called_once_with(driver.page, root, [[100.0, 0.0, 0.0], [0.0, 100.0, 0.0], [0.0, 0.0, 100.0]], 0)

    def test_answer_single_like_does_not_report_success_when_target_stays_unchecked(self, restore_credamo_runtime_patchpoints) -> None:
        input_element = self._FakeChoiceElement()
        root = SimpleNamespace()
        page = SimpleNamespace(evaluate=lambda script, element: bool(getattr(element, 'checked', False)))
        with patch('credamo.provider.runtime._option_inputs', return_value=[input_element]), patch('credamo.provider.runtime._option_click_targets', return_value=[]), patch('credamo.provider.runtime._click_element', return_value=True), patch('credamo.provider.runtime.normalize_droplist_probs', return_value=[100.0]), patch('credamo.provider.runtime.weighted_index', return_value=0):
            answered = runtime._answer_single_like(page, root, [100.0], 1)
        assert not answered

    def test_answer_single_like_prefers_forced_text_match_over_weight_index(self, restore_credamo_runtime_patchpoints) -> None:
        wrong = self._FakeChoiceElement('300')
        correct = self._FakeChoiceElement('200')
        root = SimpleNamespace()
        page = SimpleNamespace(evaluate=lambda script, element: bool(getattr(element, 'checked', False)))
        with patch('credamo.provider.runtime._option_inputs', return_value=[wrong, correct]), patch('credamo.provider.runtime._option_click_targets', return_value=[]), patch('credamo.provider.runtime._resolve_forced_choice_index', return_value=1), patch('credamo.provider.runtime.normalize_droplist_probs', return_value=[100.0, 0.0]), patch('credamo.provider.runtime.weighted_index', return_value=0):
            answered = runtime._answer_single_like(page, root, [100.0, 0.0], 2)
        assert answered
        assert not wrong.checked
        assert correct.checked

    def test_answer_dropdown_uses_keyboard_selection_for_credamo_select(self, restore_credamo_runtime_patchpoints) -> None:
        trigger = self._FakeDropdownInput()
        value_input = self._FakeDropdownInput()
        locator = self._FakeDropdownLocator(4)

        class _FakeKeyboard:

            def __init__(self, input_element: 'CredamoRuntimeTests._FakeDropdownInput') -> None:
                self.input_element = input_element
                self.arrow_down_count = 0

            def press(self, key: str) -> None:
                if key == 'ArrowDown':
                    self.arrow_down_count += 1
                elif key == 'Enter' and self.arrow_down_count > 0:
                    self.input_element.value = f'选项 {self.arrow_down_count}'

        class _FakeRoot:

            def query_selector(self, selector: str):
                if selector in {'.pc-dropdown .el-input', '.el-input'}:
                    return trigger
                if selector == '.el-input__inner':
                    return value_input
                return None

        def _evaluate(script: str, element) -> object:
            if 'el.value' in script:
                return getattr(element, 'value', '')
            return True
        page = SimpleNamespace(evaluate=_evaluate, wait_for_timeout=lambda _ms: None, locator=lambda _selector: locator, keyboard=_FakeKeyboard(value_input))
        with patch('credamo.provider.runtime._click_element', return_value=True), patch('credamo.provider.runtime.normalize_droplist_probs', return_value=[0.0, 100.0, 0.0, 0.0]), patch('credamo.provider.runtime.weighted_index', return_value=1):
            answered = runtime._answer_dropdown(page, _FakeRoot(), [0.0, 100.0, 0.0, 0.0])
        assert answered
        assert value_input.value == '选项 2'

    def test_brush_credamo_passes_multi_select_limits_into_answerer(self, restore_credamo_runtime_patchpoints) -> None:
        stop_signal = threading.Event()
        state = SimpleNamespace(stop_event=stop_signal, update_thread_step=lambda *args, **kwargs: None, update_thread_status=lambda *args, **kwargs: None)
        config = SimpleNamespace(question_config_index_map={5: ('multiple', 0)}, questions_metadata={5: SimpleNamespace(multi_min_limit=2, multi_max_limit=3)}, single_prob=[], droplist_prob=[], scale_prob=[], multiple_prob=[[100.0, 100.0, 100.0, 100.0]], texts=[], answer_duration_range_seconds=[0, 0])
        driver = SimpleNamespace(page=object())
        root = self._FakeQuestionRoot(5)
        with patch('credamo.provider.runtime._wait_for_question_roots', return_value=[root]), patch('credamo.provider.runtime._wait_for_dynamic_question_roots', side_effect=[[root], [root]]), patch('credamo.provider.runtime._question_number_from_root', side_effect=lambda _page, current_root, _fallback: current_root.question_num), patch('credamo.provider.runtime._root_text', return_value='Q5'), patch('credamo.provider.runtime._navigation_action', return_value='submit'), patch('credamo.provider.runtime._click_submit', return_value=True), patch('credamo.provider.runtime._answer_multiple', return_value=True) as multiple_mock, patch('credamo.provider.runtime.simulate_answer_duration_delay', return_value=False), patch('credamo.provider.runtime.time.sleep'):
            result = runtime.brush_credamo(driver, config, state, stop_signal=stop_signal, thread_name='Worker-1')
        assert result
        multiple_mock.assert_called_once_with(driver.page, root, [100.0, 100.0, 100.0, 100.0], min_limit=2, max_limit=3)

    def test_runtime_patchpoint_wrappers_sync_and_delegate(self, restore_credamo_runtime_patchpoints) -> None:
        page = object()
        stop_signal = threading.Event()
        root = object()
        with patch('credamo.provider.runtime._DOM_WAIT_FOR_QUESTION_ROOTS', return_value=['r1']) as wait_roots, \
             patch('credamo.provider.runtime._DOM_UNANSWERED_QUESTION_ROOTS', return_value=['r2']) as unanswered, \
             patch('credamo.provider.runtime._DOM_WAIT_FOR_DYNAMIC_QUESTION_ROOTS', return_value=['r3']) as dynamic_roots, \
             patch('credamo.provider.runtime._DOM_WAIT_FOR_PAGE_CHANGE', return_value=True) as wait_change, \
             patch('credamo.provider.runtime._DOM_CLICK_SUBMIT', return_value=True) as click_submit, \
             patch('credamo.provider.runtime._ANSWER_SINGLE_LIKE', return_value=True) as answer_single, \
             patch('credamo.provider.runtime._ANSWER_MULTIPLE', return_value=True) as answer_multiple, \
             patch('credamo.provider.runtime._ANSWER_TEXT', return_value=True) as answer_text, \
             patch('credamo.provider.runtime._ANSWER_DROPDOWN', return_value=True) as answer_dropdown, \
             patch('credamo.provider.runtime._ANSWER_SCALE', return_value=True) as answer_scale, \
             patch('credamo.provider.runtime._ANSWER_MATRIX', return_value=True) as answer_matrix, \
             patch('credamo.provider.runtime._ANSWER_ORDER', return_value=True) as answer_order:
            assert runtime._wait_for_question_roots(page, stop_signal, timeout_ms=1) == ['r1']
            assert runtime._unanswered_question_roots(page, ['a'], {'b'}, fallback_start=2) == ['r2']
            assert runtime._wait_for_dynamic_question_roots(page, {'a'}, stop_signal, fallback_start=2) == ['r3']
            assert runtime._wait_for_page_change(page, 'sig', stop_signal, timeout_ms=1)
            assert runtime._click_submit(page, stop_signal, timeout_ms=1)
            assert runtime._answer_single_like(page, root, [1], 0)
            assert runtime._answer_multiple(page, root, [1], min_limit=1, max_limit=2)
<<<<<<< HEAD
            assert runtime._answer_text(page, root, ['x'])
=======
            assert runtime._answer_text(root, ['x'])
>>>>>>> aa2599c10157bb3f4694164cada5b32fa5ad00a8
            assert runtime._answer_dropdown(page, root, [1])
            assert runtime._answer_scale(page, root, [1])
            assert runtime._answer_matrix(page, root, [[1]], 3)
            assert runtime._answer_order(page, root)

        wait_roots.assert_called_once_with(page, stop_signal, timeout_ms=1)
        unanswered.assert_called_once_with(page, ['a'], {'b'}, fallback_start=2)
        dynamic_roots.assert_called_once_with(page, {'a'}, stop_signal, fallback_start=2)
        wait_change.assert_called_once_with(page, 'sig', stop_signal, timeout_ms=1)
        click_submit.assert_called_once_with(page, stop_signal, timeout_ms=1)
        answer_single.assert_called_once_with(page, root, [1], 0)
        answer_multiple.assert_called_once_with(page, root, [1], min_limit=1, max_limit=2)
<<<<<<< HEAD
        answer_text.assert_called_once_with(page, root, ['x'], question_num=0, ai_enabled=False, question_title='')
        answer_dropdown.assert_called_once_with(page, root, [1])
        answer_scale.assert_called_once_with(page, root, [1])
        answer_matrix.assert_called_once_with(page, root, [[1]], 3)
        answer_order.assert_called_once_with(page, root, None)
=======
        answer_text.assert_called_once_with(root, ['x'])
        answer_dropdown.assert_called_once_with(page, root, [1])
        answer_scale.assert_called_once_with(page, root, [1])
        answer_matrix.assert_called_once_with(page, root, [[1]], 3)
        answer_order.assert_called_once_with(page, root)
>>>>>>> aa2599c10157bb3f4694164cada5b32fa5ad00a8

    def test_brush_credamo_handles_missing_roots_abort_unknown_type_and_submit_failures(self, restore_credamo_runtime_patchpoints) -> None:
        stop_signal = threading.Event()
        state = SimpleNamespace(stop_event=stop_signal, update_thread_step=lambda *args, **kwargs: None, update_thread_status=lambda *args, **kwargs: None)
        driver = SimpleNamespace(page=object())

        config_missing = SimpleNamespace(question_config_index_map={1: ('single', 0)}, single_prob=[-1], droplist_prob=[], scale_prob=[], multiple_prob=[], texts=[], answer_duration_range_seconds=[0, 0])
        with patch('credamo.provider.runtime._wait_for_question_roots', return_value=[]):
            try:
                runtime.brush_credamo(driver, config_missing, state, stop_signal=stop_signal, thread_name='Worker-1')
            except RuntimeError as exc:
                assert '未识别到题目' in str(exc)
            else:
                raise AssertionError('expected RuntimeError')

        stop_signal2 = threading.Event()
        status_updates: list[tuple[str, bool]] = []
        state2 = SimpleNamespace(
            stop_event=stop_signal2,
            update_thread_step=lambda *args, **kwargs: None,
            update_thread_status=lambda _thread, status_text, *, running: status_updates.append((status_text, running)),
        )
        root = self._FakeQuestionRoot(9)
        config_unknown = SimpleNamespace(question_config_index_map={9: ('mystery', 0)}, single_prob=[], droplist_prob=[], scale_prob=[], multiple_prob=[], texts=[], answer_duration_range_seconds=[0, 0])
        with patch('credamo.provider.runtime._wait_for_question_roots', return_value=[root]), \
             patch('credamo.provider.runtime._wait_for_dynamic_question_roots', side_effect=[[root], [root]]), \
             patch('credamo.provider.runtime._question_number_from_root', side_effect=lambda _page, current_root, _fallback: current_root.question_num), \
             patch('credamo.provider.runtime._root_text', return_value='Q9'), \
             patch('credamo.provider.runtime._navigation_action', return_value='submit'), \
             patch('credamo.provider.runtime.simulate_answer_duration_delay', return_value=True), \
             patch('credamo.provider.runtime.time.sleep'):
            assert not runtime.brush_credamo(driver, config_unknown, state2, stop_signal=stop_signal2, thread_name='Worker-2')
        assert ('提交中', True) not in status_updates

<<<<<<< HEAD
        config_submit_fail = SimpleNamespace(question_config_index_map={9: ('text', 0)}, single_prob=[], droplist_prob=[], scale_prob=[], multiple_prob=[], texts=[['x']], text_ai_flags=[False], text_titles=[''], answer_duration_range_seconds=[0, 0])
=======
        config_submit_fail = SimpleNamespace(question_config_index_map={9: ('text', 0)}, single_prob=[], droplist_prob=[], scale_prob=[], multiple_prob=[], texts=[['x']], answer_duration_range_seconds=[0, 0])
>>>>>>> aa2599c10157bb3f4694164cada5b32fa5ad00a8
        with patch('credamo.provider.runtime._wait_for_question_roots', return_value=[root]), \
             patch('credamo.provider.runtime._wait_for_dynamic_question_roots', side_effect=[[root], [root]]), \
             patch('credamo.provider.runtime._question_number_from_root', side_effect=lambda _page, current_root, _fallback: current_root.question_num), \
             patch('credamo.provider.runtime._root_text', return_value='Q9'), \
             patch('credamo.provider.runtime._navigation_action', return_value='submit'), \
             patch('credamo.provider.runtime._answer_text', return_value=True), \
             patch('credamo.provider.runtime.simulate_answer_duration_delay', return_value=False), \
             patch('credamo.provider.runtime._click_submit', return_value=False), \
             patch('credamo.provider.runtime.time.sleep'):
            try:
                runtime.brush_credamo(driver, config_submit_fail, state, stop_signal=stop_signal, thread_name='Worker-3')
            except RuntimeError as exc:
                assert '提交按钮未找到' in str(exc)
            else:
                raise AssertionError('expected RuntimeError')
