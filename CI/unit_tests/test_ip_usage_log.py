from __future__ import annotations
from unittest.mock import patch
from software.io.reports.ip_usage_log import _extract_records, _extract_remaining_ip, _to_int, get_usage_summary

class IpUsageLogTests:

    def test_to_int_accepts_numeric_strings_and_rejects_invalid_values(self) -> None:
        assert _to_int('7') == 7
        assert _to_int('7.9') == 7
        assert _to_int('bad') is None

    def test_extract_records_finds_nested_record_list(self) -> None:
        payload = {'data': {'history': [{'label': '今天', 'total': 3}, {'label': '昨天', 'total': 5}, 'bad']}}
        assert _extract_records(payload) == [{'label': '今天', 'total': 3}, {'label': '昨天', 'total': 5}]

    def test_extract_records_ignores_non_record_lists(self) -> None:
        payload = [{'foo': 1}, {'bar': 2}]
        assert _extract_records(payload) == []

    def test_extract_remaining_ip_reads_nested_value_and_clamps_negative_number(self) -> None:
        assert _extract_remaining_ip({'meta': {'remainingIp': '12'}}) == 12
        assert _extract_remaining_ip({'remaining': -5}) == 0
        assert _extract_remaining_ip({'meta': {'other': 1}}) is None

    @patch('software.io.reports.ip_usage_log.http_client.get')
    def test_get_usage_summary_returns_records_and_remaining_ip(self, mock_get, make_http_response) -> None:
        response = make_http_response(
            json_payload={'payload': {'list': [{'label': '今天', 'total': 1}, {'label': '昨天', 'total': 2}], 'remaining_ip': '9'}},
        )
        mock_get.return_value = response
        result = get_usage_summary()
        assert result == {'records': [{'label': '今天', 'total': 1}, {'label': '昨天', 'total': 2}], 'remaining_ip': 9}
        response.raise_for_status.assert_called_once_with()
