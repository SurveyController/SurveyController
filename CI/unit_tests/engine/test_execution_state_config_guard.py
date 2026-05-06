from __future__ import annotations
import pytest
from software.core.task import ExecutionConfig, ExecutionState

class ExecutionStateConfigGuardTests:

    def test_setting_config_field_on_state_raises_clear_error(self) -> None:
        state = ExecutionState(config=ExecutionConfig())
        with pytest.raises(AttributeError, match='state.config.target_num'):
            state.target_num = 10
