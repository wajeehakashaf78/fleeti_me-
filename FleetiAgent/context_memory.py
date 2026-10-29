"""
Context management for the FLEETI agent.

1. ContextMemory - remembers, per OpenAI conversation, which schema lines (fields, enums,
   notes) and joins get_query_context has already given the model, so later calls in the
   same conversation send only what is NEW. The OpenAI Conversation keeps the earlier tool
   outputs, so the model still has them. Lines older than REUSE_TURNS turns are sent again
   (the conversation may have truncated them), and the model can ask for a full resend with
   get_query_context(refresh=true).
2. count_tokens - token size of a context payload (tiktoken o200k_base, the GPT-4o/GPT-5
   tokenizer; falls back to ~4 characters per token).

State is in-process only: after a restart, or on another worker, nothing is remembered and
everything is simply sent in full again - always safe.
"""

import json
import os
import threading
import time
from collections import OrderedDict
from typing import Any, Dict, Iterable, Optional

DEDUPE_ENABLED = (os.getenv("FLEETI_CONTEXT_DEDUPE") or "1").strip().lower() not in ("0", "false", "off", "no")
REUSE_TURNS = int(os.getenv("FLEETI_CONTEXT_REUSE_TURNS") or "4")
MAX_CONVERSATIONS = int(os.getenv("FLEETI_CONTEXT_MAX_CONVERSATIONS") or "2000")
TTL_SECONDS = int(os.getenv("FLEETI_CONTEXT_TTL_SECONDS") or str(6 * 3600))
MAX_CONTEXT_TOKENS = int(os.getenv("FLEETI_CONTEXT_MAX_TOKENS") or "4000")


class ConversationView:
    """What one conversation has already received, seen from the current turn."""

    def __init__(self, sent: Dict[str, int], turn: int, refresh: bool):
        self._sent = sent
        self._turn = turn
        self._refresh = refresh

    def seen(self, key: str) -> bool:
        if self._refresh:
            return False
        sent_turn = self._sent.get(key)
        return sent_turn is not None and self._turn - sent_turn < REUSE_TURNS

    def mark(self, keys: Iterable[str]) -> None:
        for key in keys:
            self._sent[key] = self._turn


class ContextMemory:
    def __init__(self) -> None:
        self._data: "OrderedDict[str, Dict[str, Any]]" = OrderedDict()
        self._lock = threading.Lock()

    def view(self, conversation_id: Optional[str], turn: int, refresh: bool = False) -> Optional[ConversationView]:
        if not DEDUPE_ENABLED or not conversation_id:
            return None
        now = time.time()
        with self._lock:
            for cid in [c for c, v in self._data.items() if now - v["touched"] > TTL_SECONDS]:
                del self._data[cid]
            entry = self._data.pop(conversation_id, None) or {"sent": {}}
            entry["touched"] = now
            self._data[conversation_id] = entry  # most recently used last
            while len(self._data) > MAX_CONVERSATIONS:
                self._data.popitem(last=False)
            return ConversationView(entry["sent"], turn, refresh)


MEMORY = ContextMemory()

_encoder = None


def count_tokens(payload: Any) -> int:
    global _encoder
    text = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False, default=str)
    try:
        if _encoder is None:
            import tiktoken

            _encoder = tiktoken.get_encoding("o200k_base")
        return len(_encoder.encode(text))
    except Exception:  # tiktoken missing or its encoding file could not be downloaded
        return len(text) // 4
