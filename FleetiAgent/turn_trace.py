"""
Per-turn debug trace for FLEETI (TEST/DIAGNOSTIC ONLY).

When FLEETI_TURN_TRACE is enabled, every /chat turn writes ONE human-readable file
capturing the full chain used to answer a user question:
  - the user question and exactly what was sent to the model (developer note + user msg)
  - each model call's output (tool calls with arguments, reasoning items, text) + token usage
  - the schema context returned by get_query_context
  - the EXACT Mongo query run by run_fleet_query and its result (with a row sample)
  - report / aggregate / export tool results
  - the final model response (text or report payload) and per-turn totals + $ estimate

Toggle (default OFF):
  FLEETI_TURN_TRACE=true|false
  FLEETI_TURN_TRACE_DIR=<dir>   (default: logs/turn_traces)

Fail-safe: tracing NEVER raises into the turn — all writes are guarded.
"""

import os
import re
import json
import uuid
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def trace_enabled() -> bool:
    return (os.getenv("FLEETI_TURN_TRACE") or "").strip().lower() in ("1", "true", "yes", "on")


def _j(value: Any) -> str:
    try:
        return json.dumps(value, indent=2, default=str, ensure_ascii=False)
    except Exception:
        return str(value)


def summarize_model_output(resp: Any) -> List[Dict[str, Any]]:
    """Flatten an OpenAI Responses result into an ordered list of what the model did
    (function calls, reasoning, text). Robust to shape changes."""
    out: List[Dict[str, Any]] = []
    try:
        for o in (getattr(resp, "output", None) or []):
            t = getattr(o, "type", None)
            if t == "function_call":
                args = getattr(o, "arguments", "")
                try:
                    args = json.loads(args) if isinstance(args, str) else args
                except (TypeError, ValueError):
                    pass
                out.append({"type": "function_call", "name": getattr(o, "name", None), "arguments": args})
            elif t == "message":
                parts = []
                for c in (getattr(o, "content", None) or []):
                    if getattr(c, "type", None) in ("output_text", "text"):
                        parts.append(getattr(c, "text", "") or "")
                out.append({"type": "message", "text": "".join(parts)})
            elif t == "reasoning":
                summ = getattr(o, "summary", None)
                out.append({"type": "reasoning", "summary": _stringify_summary(summ)})
            else:
                out.append({"type": t or "unknown"})
    except Exception:
        pass
    return out


def _stringify_summary(summ: Any) -> str:
    if not summ:
        return "(no summary emitted)"
    try:
        if isinstance(summ, list):
            texts = [getattr(s, "text", None) or (s.get("text") if isinstance(s, dict) else str(s)) for s in summ]
            return "\n".join(t for t in texts if t) or "(no summary emitted)"
    except Exception:
        pass
    return str(summ)


class TurnTrace:
    """Accumulates ordered, human-readable sections and writes them to one file per turn."""

    def __init__(self, enabled: bool):
        self.enabled = enabled
        self.meta: Dict[str, Any] = {}
        self.lines: List[str] = []
        self.started = datetime.now()
        self.turn_id = uuid.uuid4().hex[:12]

    # ---- recording (all no-ops when disabled) ----
    def set_meta(self, **kw: Any) -> None:
        if self.enabled:
            self.meta.update(kw)

    def section(self, title: str) -> None:
        if self.enabled:
            self.lines.append("\n" + "=" * 72 + f"\n{title}\n" + "=" * 72)

    def line(self, text: str) -> None:
        if self.enabled:
            self.lines.append(text)

    def block(self, label: str, value: Any) -> None:
        if self.enabled:
            rendered = value if isinstance(value, str) else _j(value)
            self.lines.append(f"\n--- {label} ---\n{rendered}")

    def model_call(self, index: int, usage: Dict[str, int], resp: Any) -> None:
        if not self.enabled:
            return
        self.section(f"MODEL CALL {index}")
        self.line(
            "usage: input=%s cached=%s output=%s reasoning=%s"
            % (usage.get("input"), usage.get("cached"), usage.get("output"), usage.get("reasoning"))
        )
        self.block("model did (in order)", summarize_model_output(resp))

    # ---- write ----
    def write(self) -> Optional[str]:
        if not self.enabled:
            return None
        try:
            out_dir = os.getenv("FLEETI_TURN_TRACE_DIR") or os.path.join("logs", "turn_traces")
            os.makedirs(out_dir, exist_ok=True)

            head = ["FLEETI TURN TRACE", "=" * 72]
            for k in ("timestamp", "session_id", "conversation_id", "model", "reasoning",
                      "mongo_db", "sub_tenant_id", "time_zone"):
                if k in self.meta:
                    head.append(f"{k}: {self.meta[k]}")
            body = "\n".join(head) + "\n" + "\n".join(self.lines) + "\n"

            q_snip = _slug(self.meta.get("question") or "")
            fname = f"{self.started.strftime('%Y%m%d-%H%M%S')}__{self.turn_id}__{q_snip}.txt"
            path = os.path.join(out_dir, fname)
            with open(path, "w", encoding="utf-8") as f:
                f.write(body)
            logger.info("📝 turn trace written | %s", path)
            return path
        except Exception as exc:  # noqa: BLE001 - tracing must never break the turn
            logger.debug("turn trace write failed: %s", exc)
            return None


def _slug(text: str, maxlen: int = 40) -> str:
    s = re.sub(r"[^A-Za-z0-9]+", "-", (text or "").strip()).strip("-")
    return (s[:maxlen] or "turn")
