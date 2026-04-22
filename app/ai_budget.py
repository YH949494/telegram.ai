import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Deque, Dict, Literal, Tuple


BudgetDecisionState = Literal["allow", "deny", "downgrade"]


@dataclass(frozen=True)
class BudgetDecision:
    allowed: bool
    state: BudgetDecisionState
    reason: str = "ok"


class AIBudgetService:
    def __init__(self) -> None:
        self._decision_events: Deque[float] = deque()
        self._generation_events: Deque[float] = deque()
        self._per_chat_decision_events: Dict[int, Deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    @staticmethod
    def _evict_old(events: Deque[float], now: float, window_seconds: int) -> None:
        while events and (now - events[0]) > window_seconds:
            events.popleft()

    def allow_decision(
        self,
        *,
        chat_id: int,
        max_per_minute: int,
        max_per_chat_per_hour: int,
        priority: bool,
    ) -> BudgetDecision:
        now = time.time()
        with self._lock:
            self._evict_old(self._decision_events, now, 60)
            chat_events = self._per_chat_decision_events[chat_id]
            self._evict_old(chat_events, now, 3600)
            if len(self._decision_events) >= max_per_minute:
                return BudgetDecision(allowed=False, state="deny", reason="global_decision_limit")
            if len(chat_events) >= max_per_chat_per_hour and not priority:
                return BudgetDecision(allowed=False, state="deny", reason="chat_decision_limit")
            self._decision_events.append(now)
            chat_events.append(now)
        return BudgetDecision(allowed=True, state="allow")

    def allow_generation(
        self,
        *,
        max_per_minute: int,
        allow_downgrade: bool,
        priority: bool,
    ) -> BudgetDecision:
        now = time.time()
        with self._lock:
            self._evict_old(self._generation_events, now, 60)
            if len(self._generation_events) >= max_per_minute:
                if allow_downgrade and not priority:
                    return BudgetDecision(allowed=False, state="downgrade", reason="global_generation_limit")
                return BudgetDecision(allowed=False, state="deny", reason="global_generation_limit")
            self._generation_events.append(now)
        return BudgetDecision(allowed=True, state="allow")


ai_budget_service = AIBudgetService()
