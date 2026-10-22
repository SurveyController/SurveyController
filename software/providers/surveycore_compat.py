"""Centralized imports for private helpers from the pinned surveycore package."""

from surveycore.core.questions.schema import _infer_option_count as _infer_option_count
from surveycore.wjx.provider.html_parser import _normalize_html_text as _normalize_html_text
from surveycore.wjx.provider.questions import multiple_rules as _wjx_multiple_rules

_apply_rule_constraints = _wjx_multiple_rules._apply_rule_constraints
_normalize_selected_indices = _wjx_multiple_rules._normalize_selected_indices
_resolve_rule_sets = _wjx_multiple_rules._resolve_rule_sets

__all__ = [
    "_apply_rule_constraints",
    "_infer_option_count",
    "_normalize_html_text",
    "_normalize_selected_indices",
    "_resolve_rule_sets",
    "_wjx_multiple_rules",
]
