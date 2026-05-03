"""ExecutionState 的分布抽样与信效度配额状态。"""

from __future__ import annotations

import threading
from typing import Any, List, Optional, Tuple


class DistributionRuntimeMixin:
    @staticmethod
    def _normalize_distribution_counts(raw_counts: Any, option_count: int) -> List[int]:
        count = max(0, int(option_count or 0))
        normalized = [0] * count
        if not isinstance(raw_counts, list):
            return normalized
        for idx in range(min(len(raw_counts), count)):
            try:
                normalized[idx] = max(0, int(raw_counts[idx] or 0))
            except Exception:
                normalized[idx] = 0
        return normalized

    def snapshot_distribution_stats(self, stat_key: str, option_count: int) -> Tuple[int, List[int]]:
        with self.lock:
            bucket = self.distribution_runtime_stats.get(str(stat_key or "")) or {}
            total = max(0, int(bucket.get("total") or 0)) if isinstance(bucket, dict) else 0
            counts = self._normalize_distribution_counts(
                bucket.get("counts") if isinstance(bucket, dict) else None,
                option_count,
            )
        return total, counts

    def reset_pending_distribution(self, thread_name: Optional[str] = None) -> None:
        key = str(thread_name or threading.current_thread().name or "Worker-?").strip() or "Worker-?"
        with self.lock:
            self.distribution_pending_by_thread[key] = []

    def append_pending_distribution_choice(
        self,
        stat_key: str,
        option_index: int,
        option_count: int,
        thread_name: Optional[str] = None,
    ) -> None:
        key = str(thread_name or threading.current_thread().name or "Worker-?").strip() or "Worker-?"
        normalized_option_count = max(0, int(option_count or 0))
        normalized_option_index = int(option_index or 0)
        if normalized_option_count <= 0:
            return
        if normalized_option_index < 0 or normalized_option_index >= normalized_option_count:
            return
        item = (str(stat_key or ""), normalized_option_index, normalized_option_count)
        with self.lock:
            pending = self.distribution_pending_by_thread.setdefault(key, [])
            pending.append(item)

    def commit_pending_distribution(self, thread_name: Optional[str] = None) -> int:
        key = str(thread_name or threading.current_thread().name or "Worker-?").strip() or "Worker-?"
        committed = 0
        with self.lock:
            pending = list(self.distribution_pending_by_thread.get(key) or [])
            self.distribution_pending_by_thread[key] = []
            for stat_key, option_index, option_count in pending:
                if option_count <= 0 or option_index < 0 or option_index >= option_count:
                    continue
                bucket = self.distribution_runtime_stats.get(stat_key) or {}
                total = max(0, int(bucket.get("total") or 0)) if isinstance(bucket, dict) else 0
                counts = self._normalize_distribution_counts(
                    bucket.get("counts") if isinstance(bucket, dict) else None,
                    option_count,
                )
                counts[option_index] += 1
                self.distribution_runtime_stats[stat_key] = {
                    "total": total + 1,
                    "counts": counts,
                }
                committed += 1
        return committed

    def peek_reserved_joint_sample(self, thread_name: Optional[str] = None) -> Optional[int]:
        key = str(thread_name or threading.current_thread().name or "Worker-?").strip() or "Worker-?"
        with self.lock:
            reserved = self.joint_reserved_sample_by_thread.get(key)
            return int(reserved) if reserved is not None else None

    def reserve_joint_sample(self, sample_count: int, thread_name: Optional[str] = None) -> Optional[int]:
        key = str(thread_name or threading.current_thread().name or "Worker-?").strip() or "Worker-?"
        total = max(0, int(sample_count or 0))
        if total <= 0:
            return None
        with self.lock:
            existing = self.joint_reserved_sample_by_thread.get(key)
            if existing is not None:
                return int(existing)
            reserved_values = set(self.joint_reserved_sample_by_thread.values())
            for sample_index in range(total):
                if sample_index in reserved_values or sample_index in self.joint_committed_sample_indexes:
                    continue
                self.joint_reserved_sample_by_thread[key] = sample_index
                return sample_index
        return None

    def release_joint_sample(self, thread_name: Optional[str] = None) -> Optional[int]:
        key = str(thread_name or threading.current_thread().name or "Worker-?").strip() or "Worker-?"
        with self.lock:
            reserved = self.joint_reserved_sample_by_thread.pop(key, None)
        if reserved is not None:
            self.notify_runtime_change()
            return int(reserved)
        return None

    def commit_joint_sample(self, thread_name: Optional[str] = None) -> Optional[int]:
        key = str(thread_name or threading.current_thread().name or "Worker-?").strip() or "Worker-?"
        with self.lock:
            reserved = self.joint_reserved_sample_by_thread.pop(key, None)
            if reserved is None:
                return None
            self.joint_committed_sample_indexes.add(int(reserved))
        self.notify_runtime_change()
        return int(reserved)

    def wait_for_joint_sample(
        self,
        sample_count: int,
        *,
        thread_name: Optional[str] = None,
        stop_signal: Optional[threading.Event] = None,
        timeout_seconds: float = 0.5,
    ) -> Optional[int]:
        while True:
            reserved = self.reserve_joint_sample(sample_count, thread_name=thread_name)
            if reserved is not None:
                return reserved
            if stop_signal is not None and stop_signal.is_set():
                return None
            if self.wait_for_runtime_change(stop_signal=stop_signal, timeout=timeout_seconds):
                return None
