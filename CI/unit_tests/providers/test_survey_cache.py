from __future__ import annotations

import os
import tempfile
import threading
import time
import unittest

from software.providers.contracts import build_survey_definition
import software.providers.survey_cache as survey_cache
from software.providers.survey_cache import parse_survey_with_cache


class SurveyCacheTests(unittest.TestCase):
    def _patch_runtime_directory(self, temp_dir: str):
        original_runtime_directory = survey_cache.get_runtime_directory
        survey_cache.get_runtime_directory = lambda: temp_dir
        return original_runtime_directory

    def tearDown(self) -> None:
        survey_cache.clear_survey_parse_cache()

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

    def test_credamo_short_url_is_canonicalized_for_parser(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            seen_urls: list[str] = []
            original_runtime_directory = self._patch_runtime_directory(temp_dir)

            def parser(url: str):
                seen_urls.append(url)
                return build_survey_definition("credamo", "见数标题", [{"num": 1, "title": "见数题目", "type_code": "3"}])

            try:
                parse_survey_with_cache("https://www.credamo.com/s/Bvyyaaano/", parser)
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

    def test_credamo_short_url_and_redirect_url_share_cache(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            calls: list[str] = []
            original_runtime_directory = self._patch_runtime_directory(temp_dir)

            def parser(url: str):
                calls.append(url)
                return build_survey_definition("credamo", "见数标题", [{"num": 1, "title": "见数题目", "type_code": "3"}])

            try:
                first = parse_survey_with_cache("https://www.credamo.com/s/demo", parser)
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

    def test_remote_fingerprint_unavailable_reuses_recent_cache_temporarily(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            calls: list[str] = []
            original_runtime_directory = self._patch_runtime_directory(temp_dir)
            original_fetch_fingerprint = survey_cache._fetch_remote_fingerprint
            original_now = survey_cache._now
            now_values = [1000, 1005]

            def parser(url: str):
                calls.append(url)
                return build_survey_definition("wjx", "旧标题", [{"num": 1, "title": "旧题目", "type_code": "3"}])

            try:
                survey_cache._fetch_remote_fingerprint = lambda url, provider: "same" if len(calls) == 0 else None
                survey_cache._now = lambda: now_values.pop(0)
                first = parse_survey_with_cache("https://www.wjx.cn/vm/demo.aspx", parser)
                second = parse_survey_with_cache("https://www.wjx.cn/vm/demo.aspx", parser)
            finally:
                survey_cache.get_runtime_directory = original_runtime_directory
                survey_cache._fetch_remote_fingerprint = original_fetch_fingerprint
                survey_cache._now = original_now

            self.assertEqual(len(calls), 1)
            self.assertEqual(first.title, "旧标题")
            self.assertEqual(second.title, "旧标题")

    def test_clear_survey_parse_cache_removes_cached_entries(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            original_runtime_directory = self._patch_runtime_directory(temp_dir)
            cache_dir = os.path.join(temp_dir, "configs", "survey_cache")
            os.makedirs(os.path.join(cache_dir, "nested"), exist_ok=True)
            with open(os.path.join(cache_dir, "cache.json"), "w", encoding="utf-8") as file:
                file.write("{}")
            with open(os.path.join(cache_dir, "nested", "orphan.txt"), "w", encoding="utf-8") as file:
                file.write("x")

            try:
                removed_count = survey_cache.clear_survey_parse_cache()
            finally:
                survey_cache.get_runtime_directory = original_runtime_directory

            self.assertEqual(removed_count, 2)
            self.assertEqual(os.listdir(cache_dir), [])

    def test_clear_survey_parse_cache_blocks_late_background_rewrite(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            original_runtime_directory = self._patch_runtime_directory(temp_dir)
            cache_dir = os.path.join(temp_dir, "configs", "survey_cache")
            os.makedirs(cache_dir, exist_ok=True)
            cache_path = os.path.join(cache_dir, "stale.json")
            wrote_attempt = threading.Event()

            try:
                epoch_before_clear = survey_cache._cache_clear_epoch_snapshot()
                survey_cache.clear_survey_parse_cache()
                survey_cache._write_cached_definition(
                    cache_path,
                    build_survey_definition("wjx", "标题", [{"num": 1, "title": "Q1", "type_code": "3"}]),
                    "fingerprint",
                    expected_epoch=epoch_before_clear,
                )
                wrote_attempt.set()
            finally:
                survey_cache.get_runtime_directory = original_runtime_directory

            self.assertTrue(wrote_attempt.is_set())
            self.assertFalse(os.path.exists(cache_path))

    def test_same_url_concurrent_requests_share_singleflight_parse(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            original_runtime_directory = self._patch_runtime_directory(temp_dir)
            original_fetch_fingerprint = survey_cache._fetch_remote_fingerprint
            call_count = 0
            call_lock = threading.Lock()
            results: list[str] = []
            start_event = threading.Event()
            errors: list[BaseException] = []

            def parser(url: str):
                nonlocal call_count
                with call_lock:
                    call_count += 1
                start_event.wait(timeout=1)
                time.sleep(0.05)
                return build_survey_definition("wjx", "并发标题", [{"num": 1, "title": url, "type_code": "3"}])

            def worker() -> None:
                try:
                    definition = parse_survey_with_cache("https://www.wjx.cn/vm/demo.aspx", parser)
                    results.append(definition.title)
                except BaseException as exc:
                    errors.append(exc)

            threads = [threading.Thread(target=worker) for _ in range(5)]
            try:
                survey_cache._fetch_remote_fingerprint = lambda url, provider: None
                for thread in threads:
                    thread.start()
                time.sleep(0.05)
                start_event.set()
                for thread in threads:
                    thread.join(timeout=5)
            finally:
                survey_cache.get_runtime_directory = original_runtime_directory
                survey_cache._fetch_remote_fingerprint = original_fetch_fingerprint

            self.assertEqual(errors, [])
            self.assertEqual(call_count, 1)
            self.assertEqual(results, ["并发标题"] * 5)

    def test_stale_cache_returns_immediately_and_triggers_single_background_refresh(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            original_runtime_directory = self._patch_runtime_directory(temp_dir)
            original_fetch_fingerprint = survey_cache._fetch_remote_fingerprint
            original_now = survey_cache._now
            now_values = [1000, 1000 + survey_cache._SURVEY_PARSE_CACHE_TTL_SECONDS + 10]
            titles = ["旧标题", "新标题"]
            parser_calls: list[str] = []
            refresh_event = threading.Event()

            def parser(url: str):
                parser_calls.append(url)
                title = titles.pop(0)
                if title == "新标题":
                    refresh_event.set()
                return build_survey_definition("wjx", title, [{"num": 1, "title": title, "type_code": "3"}])

            fingerprint_calls = iter(["old", "changed", "changed"])

            try:
                survey_cache._now = lambda: now_values.pop(0) if now_values else 1000 + survey_cache._SURVEY_PARSE_CACHE_TTL_SECONDS + 20
                survey_cache._fetch_remote_fingerprint = lambda url, provider: next(fingerprint_calls, "changed")
                first = parse_survey_with_cache("https://www.wjx.cn/vm/demo.aspx", parser)
                second = parse_survey_with_cache("https://www.wjx.cn/vm/demo.aspx", parser)
                refresh_event.wait(timeout=3)
                for _ in range(30):
                    third = parse_survey_with_cache("https://www.wjx.cn/vm/demo.aspx", parser)
                    if third.title == "新标题":
                        break
                    time.sleep(0.05)
            finally:
                survey_cache.get_runtime_directory = original_runtime_directory
                survey_cache._fetch_remote_fingerprint = original_fetch_fingerprint
                survey_cache._now = original_now

            self.assertEqual(first.title, "旧标题")
            self.assertEqual(second.title, "旧标题")
            self.assertEqual(third.title, "新标题")
            self.assertEqual(len(parser_calls), 2)


if __name__ == "__main__":
    unittest.main()
