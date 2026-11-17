"""技能追问的进程内暂存：10 分钟 TTL，最多追问 2 轮。

只保存追问所需的最小上下文；服务重启后丢失，用户重新发送命令即可。
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass

TTL_SECONDS = 600
MAX_ROUNDS = 2


@dataclass
class PendingSkill:
    conversation_id: int
    user_id: int
    skill_id: int
    version_no: int
    original_text: str
    missing: list[str]
    rounds: int = 0
    expires_at: float = 0.0


class PendingStore:
    def __init__(self) -> None:
        self._items: dict[int, PendingSkill] = {}
        self._lock = threading.Lock()

    def set(self, pending: PendingSkill) -> None:
        pending.expires_at = time.time() + TTL_SECONDS
        with self._lock:
            self._items[pending.conversation_id] = pending

    def get(self, conversation_id: int, user_id: int) -> PendingSkill | None:
        with self._lock:
            item = self._items.get(conversation_id)
            if item is None:
                return None
            if item.expires_at < time.time() or item.user_id != user_id:
                self._items.pop(conversation_id, None)
                return None
            return item

    def clear(self, conversation_id: int) -> None:
        with self._lock:
            self._items.pop(conversation_id, None)

    def bump(self, pending: PendingSkill) -> bool:
        """记录一次追问；超过上限返回 False 并清理。"""
        pending.rounds += 1
        if pending.rounds >= MAX_ROUNDS:
            self.clear(pending.conversation_id)
            return False
        pending.expires_at = time.time() + TTL_SECONDS
        return True


pending_store = PendingStore()
