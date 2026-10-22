from __future__ import annotations

from hypothesis import given, strategies as st

from software.core.config.codec import normalize_runtime_config_payload


@given(
    st.dictionaries(
        keys=st.sampled_from(["wechat", "mobile", "pc", "legacy"]),
        values=st.integers(min_value=-1000, max_value=1000),
        max_size=8,
    )
)
def test_random_user_agent_ratios_are_always_a_valid_probability_partition(raw_ratios) -> None:
    normalized = normalize_runtime_config_payload({"random_ua_ratios": raw_ratios})
    ratios = normalized.random_ua_ratios

    assert set(ratios) == {"wechat", "mobile", "pc"}
    assert sum(ratios.values()) == 100
    assert all(0 <= ratio <= 100 for ratio in ratios.values())
