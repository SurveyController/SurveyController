#!/usr/bin/env python
"""回归检查：只要存在正权重，0 权重选项绝不应被命中。"""

from __future__ import annotations

import math
import random
from contextlib import contextmanager
from typing import Iterator

from wjx.core.questions.tendency import get_tendency_index, reset_tendency
from wjx.core.questions.utils import weighted_index


@contextmanager
def patched_random(*, random_value: float | None = None, randrange_value: int | None = None) -> Iterator[None]:
    original_random = random.random
    original_randrange = random.randrange
    try:
        if random_value is not None:
            random.random = lambda: random_value
        if randrange_value is not None:
            random.randrange = lambda upper: randrange_value
        yield
    finally:
        random.random = original_random
        random.randrange = original_randrange


def assert_equal(name: str, actual: int, expected: int) -> None:
    if actual != expected:
        raise AssertionError(f"{name} 失败：期望 {expected}，实际 {actual}")
    print(f"[PASS] {name}: {actual}")


def run_weighted_index_checks() -> None:
    with patched_random(random_value=0.0):
        assert_equal("weighted_index 前导 0 权重不误选", weighted_index([0.0, 100.0, 0.0]), 1)
        assert_equal("weighted_index 只有末尾正权重时不误选前导 0", weighted_index([0.0, 0.0, 1.0]), 2)

    with patched_random(random_value=math.nextafter(1.0, 0.0)):
        assert_equal("weighted_index 上边界兜底命中最后一个正权重", weighted_index([0.0, 1.0, 3.0]), 2)

    with patched_random(randrange_value=2):
        assert_equal("weighted_index 全 0 时保留原随机兜底", weighted_index([0.0, 0.0, 0.0]), 2)


def run_tendency_checks() -> None:
    with patched_random(random_value=0.0):
        reset_tendency()
        assert_equal(
            "量表未分组时仍落在非 0 权重项",
            get_tendency_index(3, [0.0, 100.0, 0.0], dimension=None),
            1,
        )
        assert_equal(
            "评分未分组且唯一正权重在右侧时仍能命中",
            get_tendency_index(3, [0.0, 0.0, 100.0], dimension=None),
            2,
        )

        reset_tendency()
        assert_equal(
            "同维度首题生成基准后命中非 0 权重项",
            get_tendency_index(5, [0.0, 0.0, 100.0, 0.0, 0.0], dimension="same-dim"),
            2,
        )
        assert_equal(
            "同维度后续题沿用基准时仍命中非 0 权重项",
            get_tendency_index(5, [0.0, 0.0, 100.0, 0.0, 0.0], dimension="same-dim"),
            2,
        )


def main() -> None:
    run_weighted_index_checks()
    run_tendency_checks()
    print("所有 0 权重禁选回归检查已通过。")


if __name__ == "__main__":
    main()
