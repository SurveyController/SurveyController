from __future__ import annotations

import os
import tempfile
import unittest

from software.providers.contracts import build_survey_definition
import software.providers.survey_cache as survey_cache
from software.providers.survey_cache import parse_survey_with_cache


class SurveyCacheTests(unittest.TestCase):
    def _patch_runtime_directory(self, temp_dir: str):
        original_runtime_directory = survey_cache.get_runtime_directory
        survey_cache.get_runtime_directory = lambda: temp_dir
        return original_runtime_directory

    def test_same_fingerprint_reuses_cached_definition(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            calls: list[str] = []
            original_runtime_directory = self._patch_runtime_directory(temp_dir)
            original_fetch_fingerprint = survey_cache._fetch_remote_fingerprint

            def parser(url: str):
                calls.append(url)
                return build_survey_definition("wjx", "旧标题", [{"num": 1, "title": "旧题目", "type_code": "3"}])

            try:
                survey_cache._fetch_remote_fingerprint = lambda url, provider: "same"
                first = parse_survey_with_cache("https://www.wjx.cn/vm/demo.aspx", parser)
                second = parse_survey_with_cache("https://www.wjx.cn/vm/demo.aspx", parser)
            finally:
                survey_cache.get_runtime_directory = original_runtime_directory
                survey_cache._fetch_remote_fingerprint = original_fetch_fingerprint

            self.assertEqual(len(calls), 1)
            self.assertEqual(first.title, "旧标题")
            self.assertEqual(second.title, "旧标题")
            self.assertEqual(second.questions[0]["title"], "旧题目")
            self.assertTrue(os.path.isdir(os.path.join(temp_dir, "configs", "survey_cache")))

    def test_credamo_url_fragment_is_preserved_for_parser(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            seen_urls: list[str] = []
            original_runtime_directory = self._patch_runtime_directory(temp_dir)

            def parser(url: str):
                seen_urls.append(url)
                return build_survey_definition("credamo", "见数标题", [{"num": 1, "title": "见数题目", "type_code": "3"}])

            try:
                parse_survey_with_cache("https://www.credamo.com/answer.html#/s/Bvyyaaano/", parser)
            finally:
                survey_cache.get_runtime_directory = original_runtime_directory

            self.assertEqual(seen_urls, ["https://www.credamo.com/answer.html#/s/Bvyyaaano/"])

    def test_changed_fingerprint_refreshes_cache(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            fingerprints = ["old", "new", "new"]
            titles = ["旧标题", "新标题"]
            original_runtime_directory = self._patch_runtime_directory(temp_dir)
            original_fetch_fingerprint = survey_cache._fetch_remote_fingerprint

            def parser(url: str):
                title = titles.pop(0)
                return build_survey_definition("wjx", title, [{"num": 1, "title": title, "type_code": "3"}])

            def next_fingerprint(url: str, provider: str) -> str:
                return fingerprints.pop(0)

            try:
                survey_cache._fetch_remote_fingerprint = next_fingerprint
                first = parse_survey_with_cache("https://www.wjx.cn/vm/demo.aspx", parser)
                second = parse_survey_with_cache("https://www.wjx.cn/vm/demo.aspx", parser)
            finally:
                survey_cache.get_runtime_directory = original_runtime_directory
                survey_cache._fetch_remote_fingerprint = original_fetch_fingerprint

            self.assertEqual(first.title, "旧标题")
            self.assertEqual(second.title, "新标题")
            self.assertEqual(titles, [])

    def test_credamo_reuses_cache_within_short_ttl(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            calls: list[str] = []
            original_runtime_directory = self._patch_runtime_directory(temp_dir)

            def parser(url: str):
                calls.append(url)
                return build_survey_definition("credamo", "见数标题", [{"num": 1, "title": "见数题目", "type_code": "3"}])

            try:
                first = parse_survey_with_cache("https://www.credamo.com/answer.html#/s/demo", parser)
                second = parse_survey_with_cache("https://www.credamo.com/answer.html#/s/demo", parser)
            finally:
                survey_cache.get_runtime_directory = original_runtime_directory

            self.assertEqual(len(calls), 1)
            self.assertEqual(first.title, "见数标题")
            self.assertEqual(second.title, "见数标题")

    def test_credamo_refreshes_after_short_ttl_expires(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            original_runtime_directory = self._patch_runtime_directory(temp_dir)
            original_now = survey_cache._now
            now_values = [1000, 1000 + survey_cache._CREDAMO_TTL_SECONDS + 1, 2000]
            titles = ["旧见数", "新见数"]

            def parser(url: str):
                title = titles.pop(0)
                return build_survey_definition("credamo", title, [{"num": 1, "title": title, "type_code": "3"}])

            try:
                survey_cache._now = lambda: now_values.pop(0)
                first = parse_survey_with_cache("https://www.credamo.com/answer.html#/s/demo", parser)
                second = parse_survey_with_cache("https://www.credamo.com/answer.html#/s/demo", parser)
            finally:
                survey_cache.get_runtime_directory = original_runtime_directory
                survey_cache._now = original_now

            self.assertEqual(first.title, "旧见数")
            self.assertEqual(second.title, "新见数")
            self.assertEqual(titles, [])


if __name__ == "__main__":
    unittest.main()
