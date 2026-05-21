from __future__ import annotations

from collections import deque
from typing import Callable, Deque, Dict, List, Optional, Tuple

JobTuple = Tuple[str, str, str, str, List[str]]
# (key, stage, kind, hand_hash, codes13)


class JobScheduler:
    """
    Job list builder extracted from StrategyTab.

    Lưu ý:
    - Module này CHỈ build deque jobs theo đúng tuple format StrategyTab đang dùng.
    - Không spawn thread, không đụng queue kết quả, không đổi flow.
    """

    def __init__(self, hand_hash_fn: Callable[[List[str]], str]) -> None:
        self._hand_hash_fn = hand_hash_fn

    def build_jobs(
        self,
        snapshot: Dict[str, List[str]],
        ordered_keys: List[str],
        scheduled_hash: Dict[str, Optional[str]],
    ) -> Deque[JobTuple]:
        q: Deque[JobTuple] = deque()

        # BASE jobs (MAX + MONEY) with scheduled_hash dedup
        for k in ordered_keys:
            codes = snapshot[k]
            h = self._hand_hash_fn(codes)
            if scheduled_hash.get(k) == h:
                continue
            scheduled_hash[k] = h
            q.append((k, "BASE", "MAX", h, list(codes)))
            q.append((k, "BASE", "MONEY", h, list(codes)))

        # EXTRA jobs (ALL) always appended (same as StrategyTab hiện tại)
        for k in ordered_keys:
            codes = snapshot[k]
            h = self._hand_hash_fn(codes)
            q.append((k, "EXTRA", "ALL", h, list(codes)))

        return q
