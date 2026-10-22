from __future__ import annotations

from hypothesis import given, strategies as st

from software.providers.common import (
    SUPPORTED_SURVEY_PROVIDERS,
    normalize_survey_parse_url,
    normalize_survey_provider,
)


@given(st.one_of(st.none(), st.booleans(), st.integers(), st.text()))
def test_provider_normalization_always_returns_supported_provider(value) -> None:
    normalized = normalize_survey_provider(value)

    assert normalized in SUPPORTED_SURVEY_PROVIDERS
    assert normalize_survey_provider(normalized) == normalized


@given(st.text(min_size=0, max_size=240))
def test_provider_parse_url_normalization_is_idempotent(value: str) -> None:
    normalized = normalize_survey_parse_url(value)

    assert normalize_survey_parse_url(normalized) == normalized
