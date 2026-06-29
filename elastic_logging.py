"""
Elasticsearch log shipping for FLEETI.

Ships every existing FLEETI log line (no log-call changes needed) to an
Elasticsearch index as one JSON document per log record, tagged with per-turn
context (turn_id, session_id, sub_tenant_id, mongo_db, user_input) so the
complete logs of a single /chat turn can be retrieved by filtering on turn_id.

Design goals (all enforced here):
  - OPT-IN: if ELASTIC_URL is unset, configure_elastic_logging() is a no-op.
  - NON-BLOCKING: records are queued and shipped by a background daemon thread,
    so request latency is never affected by Elasticsearch.
  - FAIL-SAFE: any Elasticsearch error (down, auth, mapping, network) is swallowed
    — logging must never crash or slow the app. Records are dropped on overflow.
  - NO NEW DEPENDENCY: talks to the Elasticsearch REST _bulk API via httpx
    (already a project dependency), so it works with ES 7.x/8.x over basic auth
    without the client/server version coupling of the official client.

Env:
  ELASTIC_URL              e.g. https://elastic.example.com:9200  (empty -> disabled)
  ELASTIC_USERNAME         basic-auth user (optional)
  ELASTIC_PASSWORD         basic-auth password (optional)
  ELASTIC_INDEX            index name (default "fleeti")
  ELASTIC_LOGGING_ENABLED  "false" to force-disable even when URL is set (default true)
  ELASTIC_VERIFY_SSL       "false" to skip TLS verification (default true)
  ELASTIC_LOG_LEVEL        minimum level shipped (default INFO)
"""

import os
import json
import time
import queue
import atexit
import socket
import logging
import threading
import contextvars
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, Optional

import httpx

# Internal logger for THIS module. It is deliberately NOT shipped to Elasticsearch
# (the handler is only attached to the FLEETI app loggers), so it can't feed back
# into itself and create a logging loop.
_log = logging.getLogger("FleetiElastic")

_HOSTNAME = socket.gethostname()


# ================================
# Per-turn context (correlates every log line of one /chat turn)
# ================================
_turn_ctx: "contextvars.ContextVar[Optional[Dict[str, Any]]]" = contextvars.ContextVar(
    "fleeti_turn_ctx", default=None
)


def set_turn_context(**fields: Any) -> "contextvars.Token":
    """
    Merge the given fields into the current turn context and return a reset token.
    Call once at the start of a /chat turn; pass the token to reset_turn_context()
    in a finally. None values are dropped.
    """
    current = dict(_turn_ctx.get() or {})
    current.update({k: v for k, v in fields.items() if v is not None})
    return _turn_ctx.set(current)


def reset_turn_context(token: Optional["contextvars.Token"]) -> None:
    if token is None:
        return
    try:
        _turn_ctx.reset(token)
    except Exception:
        # Resetting out of order / across contexts is non-fatal for cleanup.
        pass


class _TurnContextFilter(logging.Filter):
    """Stamps each record with the current turn context (read in the emitting thread,
    so contextvars resolve correctly even across asyncio.to_thread)."""

    def filter(self, record: logging.LogRecord) -> bool:
        ctx = _turn_ctx.get()
        if ctx:
            record.fleeti_ctx = ctx  # type: ignore[attr-defined]
        return True


# ================================
# Index mapping (created if the index is absent)
# ================================
def _index_mapping() -> Dict[str, Any]:
    return {
        "mappings": {
            "dynamic": True,
            "properties": {
                "@timestamp": {"type": "date"},
                "level": {"type": "keyword"},
                "logger": {"type": "keyword"},
                "message": {"type": "text"},
                "service": {"type": "keyword"},
                "host": {"type": "keyword"},
                "module": {"type": "keyword"},
                "func": {"type": "keyword"},
                "line": {"type": "integer"},
                "turn_id": {"type": "keyword"},
                "session_id": {"type": "keyword"},
                "sub_tenant_id": {"type": "keyword"},
                "mongo_db": {"type": "keyword"},
                "conversation_id": {"type": "keyword"},
                "user_input": {"type": "text"},
                "error": {"type": "text"},
            },
        }
    }


# ================================
# The shipping handler
# ================================
class ElasticLogHandler(logging.Handler):
    def __init__(
        self,
        url: str,
        index: str,
        username: Optional[str] = None,
        password: Optional[str] = None,
        verify_ssl: bool = True,
        level: int = logging.INFO,
        flush_interval: float = 2.0,
        batch_size: int = 200,
        queue_max: int = 20000,
    ) -> None:
        super().__init__(level=level)
        self._url = url.rstrip("/")
        self._index = index
        self._verify = verify_ssl
        self._flush_interval = flush_interval
        self._batch_size = batch_size
        self._queue: "queue.Queue[Dict[str, Any]]" = queue.Queue(maxsize=queue_max)
        self._index_ready = False
        self._stop = threading.Event()
        auth = (username, password) if username else None
        self._client = httpx.Client(timeout=10.0, verify=verify_ssl, auth=auth)
        self.addFilter(_TurnContextFilter())
        self._worker = threading.Thread(target=self._run, name="fleeti-elastic", daemon=True)
        self._worker.start()
        atexit.register(self.close)

    # ---- producer side (runs in the request/emitting thread) ----
    def emit(self, record: logging.LogRecord) -> None:
        try:
            doc = self._format_doc(record)
            self._queue.put_nowait(doc)
        except queue.Full:
            pass  # drop under backpressure; never block the app
        except Exception:
            pass  # logging must never raise

    def _format_doc(self, record: logging.LogRecord) -> Dict[str, Any]:
        doc: Dict[str, Any] = {
            "@timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "func": record.funcName,
            "line": record.lineno,
            "process": record.process,
            "service": "fleeti",
            "host": _HOSTNAME,
        }
        if record.exc_info:
            try:
                doc["error"] = logging.Formatter().formatException(record.exc_info)
            except Exception:
                pass
        ctx = getattr(record, "fleeti_ctx", None)
        if isinstance(ctx, dict):
            for k, v in ctx.items():
                if v is not None and k not in doc:
                    doc[k] = v
        return doc

    # ---- consumer side (background thread) ----
    def _run(self) -> None:
        buf: list[Dict[str, Any]] = []
        last_flush = time.monotonic()
        while not self._stop.is_set():
            try:
                doc = self._queue.get(timeout=self._flush_interval)
                buf.append(doc)
            except queue.Empty:
                pass
            now = time.monotonic()
            if buf and (len(buf) >= self._batch_size or (now - last_flush) >= self._flush_interval):
                self._flush(buf)
                buf = []
                last_flush = now
        # Drain whatever is left on shutdown.
        try:
            while True:
                buf.append(self._queue.get_nowait())
        except queue.Empty:
            pass
        if buf:
            self._flush(buf)

    def _ensure_index(self) -> bool:
        if self._index_ready:
            return True
        try:
            head = self._client.head(f"{self._url}/{self._index}")
            if head.status_code == 200:
                self._index_ready = True
                return True
            resp = self._client.put(f"{self._url}/{self._index}", json=_index_mapping())
            if resp.status_code in (200, 201) or (
                resp.status_code == 400 and "resource_already_exists" in resp.text
            ):
                self._index_ready = True
                _log.info("Elasticsearch index '%s' ready.", self._index)
                return True
            _log.warning("Could not create Elasticsearch index '%s': HTTP %s %s",
                         self._index, resp.status_code, resp.text[:200])
        except Exception as exc:  # noqa: BLE001
            _log.debug("Elasticsearch index check/create failed: %s", exc)
        return False

    def _flush(self, docs: list[Dict[str, Any]]) -> None:
        if not docs or not self._ensure_index():
            return
        try:
            action = json.dumps({"index": {"_index": self._index}})
            lines = []
            for d in docs:
                lines.append(action)
                lines.append(json.dumps(d, default=str))
            body = "\n".join(lines) + "\n"
            self._client.post(
                f"{self._url}/_bulk",
                content=body.encode("utf-8"),
                headers={"Content-Type": "application/x-ndjson"},
            )
        except Exception as exc:  # noqa: BLE001 - never raise from logging
            _log.debug("Elasticsearch bulk ship failed (%d docs): %s", len(docs), exc)

    def close(self) -> None:
        try:
            self._stop.set()
            if self._worker.is_alive():
                self._worker.join(timeout=5.0)
            self._client.close()
        except Exception:
            pass
        super().close()


# ================================
# Setup entrypoint
# ================================
_HANDLER: Optional[ElasticLogHandler] = None


def configure_elastic_logging(logger_names: Iterable[str]) -> Optional[ElasticLogHandler]:
    """
    Attach an ElasticLogHandler to the given loggers, reading config from the
    environment. Returns the handler, or None when disabled / not configured.
    Safe to call once at startup; subsequent calls are ignored.
    """
    global _HANDLER
    if _HANDLER is not None:
        return _HANDLER

    url = (os.getenv("ELASTIC_URL") or "").strip()
    enabled = (os.getenv("ELASTIC_LOGGING_ENABLED") or "true").strip().lower() not in ("false", "0", "no")
    if not url or not enabled:
        return None

    index = (os.getenv("ELASTIC_INDEX") or "fleeti").strip() or "fleeti"
    username = (os.getenv("ELASTIC_USERNAME") or "").strip() or None
    password = os.getenv("ELASTIC_PASSWORD") or None
    verify_ssl = (os.getenv("ELASTIC_VERIFY_SSL") or "true").strip().lower() not in ("false", "0", "no")
    level_name = (os.getenv("ELASTIC_LOG_LEVEL") or "INFO").strip().upper()
    level = getattr(logging, level_name, logging.INFO)

    try:
        handler = ElasticLogHandler(
            url=url,
            index=index,
            username=username,
            password=password,
            verify_ssl=verify_ssl,
            level=level,
        )
    except Exception as exc:  # noqa: BLE001
        _log.warning("Elasticsearch logging disabled (handler init failed): %s", exc)
        return None

    for name in logger_names:
        lg = logging.getLogger(name)
        if not any(isinstance(h, ElasticLogHandler) for h in lg.handlers):
            lg.addHandler(handler)

    _HANDLER = handler
    _log.info("Elasticsearch log shipping enabled | url=%s index=%s level=%s", url, index, level_name)
    return handler
