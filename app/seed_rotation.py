import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Deque, Dict, List, Optional, Tuple


@dataclass(frozen=True)
class SeedItem:
    key: str
    text: str
    tone: str
    reply_goal: str
    allowed_contexts: Tuple[str, ...]


class SeedRotationService:
    def __init__(self) -> None:
        self._usage: Dict[Tuple[int, str], Deque[Tuple[float, str]]] = defaultdict(deque)
        self._lock = threading.Lock()

    def pick_seed(
        self,
        *,
        chat_id: int,
        category: str,
        seeds: List[SeedItem],
        repeat_window_seconds: int,
        max_seed_reuse_per_window: int,
    ) -> Optional[SeedItem]:
        if not seeds:
            return None
        if len(seeds) == 1:
            return seeds[0]
        now = time.time()
        key = (chat_id, category)
        with self._lock:
            usage = self._usage[key]
            while usage and (now - usage[0][0]) > repeat_window_seconds:
                usage.popleft()
            recent_keys = [seed_key for _, seed_key in usage]
            scores = []
            for seed in seeds:
                count = recent_keys.count(seed.key)
                if count >= max_seed_reuse_per_window:
                    continue
                last_used_ts = max((ts for ts, seed_key in usage if seed_key == seed.key), default=0.0)
                scores.append((count, last_used_ts, seed))
            if not scores:
                return seeds[0]
            scores.sort(key=lambda item: (item[0], item[1]))
            return scores[0][2]

    def mark_used(self, *, chat_id: int, category: str, seed_key: str) -> None:
        with self._lock:
            self._usage[(chat_id, category)].append((time.time(), seed_key))


seed_rotation_service = SeedRotationService()
