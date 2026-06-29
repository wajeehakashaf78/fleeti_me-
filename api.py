"""
FastAPI application for FLEETI - Fleet Management Chatbot.

/chat is served by the GPT-5 agentic orchestrator (FleetiAgent): a single
Responses API tool-calling loop (get_query_context -> run_fleet_query / run_report)
with server-side tenant isolation. The legacy classifier -> RAG -> mongo-string ->
response pipeline has been removed.
"""

import os
import json
import copy
import time
import asyncio
import logging
from typing import Optional, Dict, Any, List, Tuple
from datetime import datetime, timezone

from fastapi import FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from dotenv import load_dotenv


class _MessagePrefixFilter(logging.Filter):
    def __init__(self, *prefixes: str):
        super().__init__()
        self.prefixes = prefixes

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        return any(message.startswith(prefix) for prefix in self.prefixes)


def _configure_api_logging() -> None:
    logging.basicConfig(level=logging.INFO)

    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("openai").setLevel(logging.WARNING)

    httpx_logger = logging.getLogger("httpx")
    httpx_logger.setLevel(logging.INFO)
    httpx_logger.addFilter(_MessagePrefixFilter("HTTP Request: POST https://api.openai.com"))

    query_logger = logging.getLogger("FleetiQueryRunner.execute")
    query_logger.setLevel(logging.INFO)
    query_logger.addFilter(_MessagePrefixFilter("📋 Executing MongoDB Query:"))

    history_logger = logging.getLogger("FleetiHistorySaver.history_saver")
    history_logger.setLevel(logging.INFO)
    history_logger.addFilter(_MessagePrefixFilter("Appended message to existing session:"))

    # FLEETI agent + tools (turn start, run_fleet_query, aggregate_results / export_results
    # step logs), report API calls, and per-turn token usage -> INFO (terminal).
    for name in (
        "FleetiAgent.agent", "FleetiAgent.tools", "FleetiAgent.usage",
        "FleetiReports.api_handler", "FleetiReports.mongo_handler",
    ):
        logging.getLogger(name).setLevel(logging.INFO)

    # Mirror the per-question trace (turn start, executed query, tool steps, token usage)
    # to a rotating log file, in addition to the terminal.
    try:
        from logging.handlers import RotatingFileHandler
        log_path = os.getenv("FLEETI_LOG_FILE") or os.path.join("logs", "fleeti.log")
        os.makedirs(os.path.dirname(log_path) or ".", exist_ok=True)
        file_handler = RotatingFileHandler(
            log_path, maxBytes=5_000_000, backupCount=3, encoding="utf-8"
        )
        file_handler.setLevel(logging.INFO)
        file_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        for name in (
            "FleetiAgent.agent",
            "FleetiAgent.tools",
            "FleetiAgent.usage",
            "FleetiQueryRunner.execute",
            "FleetiReports.api_handler",
            "FleetiReports.mongo_handler",
            "FleetiHistorySaver.history_saver",
        ):
            lg = logging.getLogger(name)
            if not any(isinstance(h, RotatingFileHandler) for h in lg.handlers):
                lg.addHandler(file_handler)
    except Exception:
        pass


_configure_api_logging()
logger = logging.getLogger(__name__)

# Components and helpers
from FleetiHistorySaver.history_saver import FleetiHistorySaver
from FleetiAgent import agent as fleeti_agent
from FleetiAgent.tools import EXPORTS_DIR, sweep_old_exports
from FleetiCommon import should_remove_sub_tenant_match
from jwt_utils import decode_jwt_no_verify, extract_db_and_sub_tenant, extract_db_from_url

load_dotenv()


# ================================
# Session history cache (per session, short TTL)
# ================================
SESSION_HISTORY_CACHE_TTL_SECONDS = int(os.getenv("SESSION_HISTORY_CACHE_TTL_SECONDS", "60"))
# After this many turns on one OpenAI conversation, reset to a fresh EMPTY conversation
# (clears context to keep per-turn cost bounded). No history is re-injected.
CONVERSATION_TURN_LIMIT = int(os.getenv("FLEETI_CONVERSATION_TURN_LIMIT", "10"))
# Reuse the agent logger so reset events land in both terminal and the log file.
agent_logger = logging.getLogger("FleetiAgent.agent")
_SessionCacheKey = Tuple[str, str, str]
_SESSION_HISTORY_CACHE: Dict[_SessionCacheKey, Dict[str, Any]] = {}


def _session_cache_key(mongo_db: str, sub_tenant_id: Optional[str], session_id: str) -> _SessionCacheKey:
    return (mongo_db, sub_tenant_id or "", session_id)


def _prune_expired_session_cache(now: Optional[float] = None) -> None:
    current = now if now is not None else time.monotonic()
    expired_keys = [
        key for key, entry in _SESSION_HISTORY_CACHE.items()
        if float(entry.get("expires_at", 0)) <= current
    ]
    for key in expired_keys:
        _SESSION_HISTORY_CACHE.pop(key, None)


def _get_cached_session_document(
    history_saver: Any,
    cache_key: _SessionCacheKey,
) -> Optional[Dict[str, Any]]:
    now = time.monotonic()
    _prune_expired_session_cache(now)

    cached = _SESSION_HISTORY_CACHE.get(cache_key)
    if cached is not None:
        cached["expires_at"] = now + SESSION_HISTORY_CACHE_TTL_SECONDS
        return copy.deepcopy(cached.get("session_doc"))

    session_doc = history_saver.get_session_document()
    _SESSION_HISTORY_CACHE[cache_key] = {
        "session_doc": copy.deepcopy(session_doc),
        "expires_at": now + SESSION_HISTORY_CACHE_TTL_SECONDS,
    }
    return session_doc


def _append_message_to_session_cache(
    cache_key: _SessionCacheKey,
    message: Dict[str, Any],
) -> None:
    now = time.monotonic()
    cached = _SESSION_HISTORY_CACHE.get(cache_key)
    if cached is None or cached.get("session_doc") is None:
        mongo_db, sub_tenant_id, session_id = cache_key
        cached = {
            "session_doc": {
                "sessionId": session_id,
                "sub_tenant_id": sub_tenant_id,
                "messages": [],
            },
            "expires_at": now + SESSION_HISTORY_CACHE_TTL_SECONDS,
        }
        _SESSION_HISTORY_CACHE[cache_key] = cached

    cached["expires_at"] = now + SESSION_HISTORY_CACHE_TTL_SECONDS
    cached["session_doc"].setdefault("messages", []).append(copy.deepcopy(message))


def _set_cached_conversation_id(cache_key: _SessionCacheKey, conversation_id: str) -> None:
    """Record the OpenAI conversation id in the session cache so the next turn reuses it."""
    now = time.monotonic()
    cached = _SESSION_HISTORY_CACHE.get(cache_key)
    if cached is None or cached.get("session_doc") is None:
        mongo_db, sub_tenant_id, session_id = cache_key
        cached = {
            "session_doc": {
                "sessionId": session_id,
                "sub_tenant_id": sub_tenant_id,
                "messages": [],
            },
            "expires_at": now + SESSION_HISTORY_CACHE_TTL_SECONDS,
        }
        _SESSION_HISTORY_CACHE[cache_key] = cached
    cached["expires_at"] = now + SESSION_HISTORY_CACHE_TTL_SECONDS
    cached["session_doc"]["openai_conversation_id"] = conversation_id
    cached["session_doc"]["conversation_turn_count"] = 0  # new conversation starts fresh


def _set_cached_conversation_turn_count(cache_key: _SessionCacheKey, count: int) -> None:
    """Update the cached turn counter so the next turn (within TTL) sees the right value."""
    cached = _SESSION_HISTORY_CACHE.get(cache_key)
    if cached is not None and cached.get("session_doc") is not None:
        cached["session_doc"]["conversation_turn_count"] = count
        cached["expires_at"] = time.monotonic() + SESSION_HISTORY_CACHE_TTL_SECONDS


# ================================
# Misc helpers
# ================================
def _load_cors_origins_from_env() -> List[str]:
    """Read allowed CORS origins from CORS_ALLOWED_ORIGINS ("*", CSV, or JSON list)."""
    raw = (os.getenv("CORS_ALLOWED_ORIGINS") or "*").strip()
    if raw == "*":
        return ["*"]
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            cleaned = [str(x).strip() for x in parsed if str(x).strip()]
            return cleaned or ["*"]
    except Exception:
        pass
    cleaned = [x.strip() for x in raw.split(",") if x.strip()]
    return cleaned or ["*"]


def _format_datetime_utc_z(dt: Optional[Any]) -> Optional[str]:
    """Format a datetime for API responses as UTC with a Z suffix (ISO 8601)."""
    if dt is None:
        return None
    if isinstance(dt, str):
        s = dt.strip()
        if not s:
            return None
        return s if s.endswith("Z") else s.rstrip("Z") + "Z"
    if not isinstance(dt, datetime):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z"


def _user_friendly_failure_message() -> str:
    return (
        "I couldn't process your request right now. "
        "Please rephrase your question and try again."
    )


def _create_conversation(
    history_saver: FleetiHistorySaver,
    session_cache_key: _SessionCacheKey,
) -> str:
    """
    Create a fresh, EMPTY OpenAI Conversation (no prior history injected) and persist its
    id on the session doc + cache (resetting the turn counter). Return the id.
    """
    conv = fleeti_agent.client.conversations.create()
    history_saver.set_conversation_id(conv.id)
    _set_cached_conversation_id(session_cache_key, conv.id)
    return conv.id


# ================================
# FastAPI app
# ================================
app = FastAPI(
    title="FLEETI API",
    description="Fleet Management Chatbot API",
    version="2.0.0",
)

_cors_origins = _load_cors_origins_from_env()
_allow_credentials = "*" not in _cors_origins  # Must be False when using "*"
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=_allow_credentials,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatRequest(BaseModel):
    base_url: str = Field(..., description="Base URL from FE (e.g., https://qa.dev-iot.tracking.me/)")
    assistant_static_input: Optional[str] = Field(None, description="Initial static assistant message")
    user_input: Optional[str] = Field(None, description="User's message/question")
    session_id: Optional[str] = Field(None, description="Session ID (MongoDB document ID)")
    time_zone: Optional[str] = Field(
        default=None,
        description="User timezone in format 'UTC +/- X:XX' (e.g., 'UTC +5:00')",
    )


class ChatResponse(BaseModel):
    human_response: Optional[Any] = Field(default=None, description="Natural language response or structured data")
    session_id: Optional[str] = Field(default=None, description="Session ID (MongoDB document ID)")
    error: bool = Field(default=False, description="Whether an error occurred")
    download_url: Optional[str] = Field(default=None, description="Download link for a generated file (e.g. exported .xlsx), if any")


@app.get("/")
async def root():
    """Health check endpoint."""
    return {"status": "ok", "message": "FLEETI API is running", "version": "2.0.0"}


@app.on_event("startup")
async def _on_startup() -> None:
    """Ensure the exports folder exists and periodically purge expired files."""
    try:
        EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass

    async def _cleaner() -> None:
        while True:
            sweep_old_exports()
            await asyncio.sleep(1800)  # every 30 minutes

    asyncio.create_task(_cleaner())


@app.get("/downloads/{filename}")
async def download_export(filename: str):
    """Serve a generated export file (e.g. .xlsx). Files expire after a few hours."""
    sweep_old_exports()
    safe = os.path.basename(filename)
    if safe != filename or not safe.endswith(".xlsx"):
        raise HTTPException(status_code=400, detail="Invalid filename")
    path = EXPORTS_DIR / safe
    if not path.exists():
        raise HTTPException(status_code=404, detail="File not found or expired")
    return FileResponse(
        str(path),
        filename=safe,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest, authorization: Optional[str] = Header(default=None)):
    """
    Main chat endpoint — handled by the GPT-5 agentic orchestrator.

    Scenario 1 (assistant_static_input present): create a session with a static
    assistant message and return its session_id.
    Scenario 2 (user_input + session_id): run the agent and return the answer
    (natural-language text, or a structured report payload).
    """
    try:
        if not authorization:
            return ChatResponse(human_response="Missing Authorization header.", error=True)

        token_payload = decode_jwt_no_verify(authorization)
        _, sub_tenant_id = extract_db_and_sub_tenant(token_payload)
        mongo_db = extract_db_from_url(request.base_url)

        if not mongo_db:
            return ChatResponse(
                human_response="Invalid token: missing database information.",
                error=True,
            )

        # Scenario 1: create session with a static assistant message.
        if request.assistant_static_input is not None:
            history_saver = FleetiHistorySaver(
                session_id="static_session",
                sub_tenant_id=sub_tenant_id or "",
                mongo_db=mongo_db,
            )
            session_id = history_saver.save_static_message(request.assistant_static_input)
            return ChatResponse(human_response=None, session_id=session_id, error=False)

        # Scenario 2: normal chat flow.
        if not request.user_input or not request.session_id:
            return ChatResponse(human_response="Missing user_input or session_id.", error=True)

        history_saver = FleetiHistorySaver(
            session_id=request.session_id,
            sub_tenant_id=sub_tenant_id or "",
            mongo_db=mongo_db,
        )
        session_cache_key = _session_cache_key(mongo_db, sub_tenant_id, request.session_id)
        session_doc = _get_cached_session_document(history_saver, session_cache_key)

        def save_general_message_to_history(**kwargs: Any) -> Dict[str, Any]:
            saved_message = history_saver.save_general_message(**kwargs)
            _append_message_to_session_cache(session_cache_key, saved_message)
            return saved_message

        def save_fleet_message_to_history(**kwargs: Any) -> Dict[str, Any]:
            saved_message = history_saver.save_fleet_message(**kwargs)
            _append_message_to_session_cache(session_cache_key, saved_message)
            return saved_message

        if fleeti_agent.client is None:
            return ChatResponse(human_response=_user_friendly_failure_message(), error=False)

        # Cross-turn memory lives in an OpenAI Conversation; we only send the new message.
        # Every CONVERSATION_TURN_LIMIT turns we reset to a fresh EMPTY conversation to keep
        # per-turn cost bounded (no history is carried over).
        conversation_id = history_saver.get_conversation_id(session_doc)
        turn_count = int((session_doc or {}).get("conversation_turn_count", 0) or 0)

        if conversation_id and turn_count >= CONVERSATION_TURN_LIMIT:
            agent_logger.info(
                "♻ context reset after %d turns | session=%s (starting a fresh conversation)",
                turn_count, request.session_id,
            )
            conversation_id = _create_conversation(history_saver, session_cache_key)
            turn_count = 0
        elif not conversation_id:
            conversation_id = _create_conversation(history_saver, session_cache_key)
            turn_count = 0

        remove_sub_tenant_match = should_remove_sub_tenant_match(
            sub_tenant_id=sub_tenant_id,
            base_url=request.base_url,
        )

        async def _run(conv_id: str):
            return await fleeti_agent.run(
                request.user_input,
                conversation_id=conv_id,
                mongo_db=mongo_db,
                sub_tenant_id=sub_tenant_id,
                base_url=request.base_url,
                authorization=authorization,
                time_zone=request.time_zone,
                remove_sub_tenant_match=remove_sub_tenant_match,
            )

        result = await _run(conversation_id)
        if result.conversation_invalid:
            # Conversation missing/expired on OpenAI -> start a fresh empty one, retry once.
            conversation_id = _create_conversation(history_saver, session_cache_key)
            turn_count = 0
            result = await _run(conversation_id)

        # Record this turn against the current conversation (drives the 10-turn reset).
        turn_count += 1
        history_saver.set_conversation_turn_count(turn_count)
        _set_cached_conversation_turn_count(session_cache_key, turn_count)

        if result.error or result.conversation_invalid:
            return ChatResponse(human_response=_user_friendly_failure_message(), error=False)

        # Report with displayable data -> structured payload.
        if result.report_payload is not None:
            save_fleet_message_to_history(
                user_input=request.user_input,
                query="",
                human_response=result.report_payload,
            )
            return ChatResponse(human_response=result.report_payload, error=False)

        # Fleet data question answered in natural language (optionally with an export link).
        if result.used_fleet_query:
            save_fleet_message_to_history(
                user_input=request.user_input,
                query=result.last_fleet_query,
                human_response=result.text,
            )
            return ChatResponse(human_response=result.text, download_url=result.export_url, error=False)

        # General conversation, read-only refusal, or a request for a missing report prerequisite.
        save_general_message_to_history(
            user_input=request.user_input,
            llm_response=result.text,
        )
        return ChatResponse(human_response=result.text, download_url=result.export_url, error=False)

    except Exception as e:
        logger.debug("[UnhandledChatError] %s", str(e))
        return ChatResponse(human_response=_user_friendly_failure_message(), error=False)


# ================================
# Pagination (conversations list + per-session messages)
# ================================
_MAX_PAGE_SIZE = 100


def _normalize_page_size(
    page: Optional[int], size: Optional[int], default_size: int
) -> Tuple[bool, int, int]:
    """
    Resolve optional page/size into (paginate, page, size).

    Pagination is OPT-IN: when the caller passes neither page nor size, `paginate`
    is False and the endpoint returns the full set (backward compatible). When either
    is provided, page>=1 and 1<=size<=_MAX_PAGE_SIZE.
    """
    paginate = page is not None or size is not None
    p = page if (page is not None and page >= 1) else 1
    try:
        s = int(size) if size is not None else int(default_size)
    except (TypeError, ValueError):
        s = default_size
    s = max(1, min(s, _MAX_PAGE_SIZE))
    return paginate, p, s


@app.get("/conversations")
async def get_conversations(
    authorization: Optional[str] = Header(default=None),
    page: Optional[int] = Query(default=None, ge=1, description="1-based page (omit for all)"),
    size: Optional[int] = Query(default=None, ge=1, le=_MAX_PAGE_SIZE, description="Page size (omit for all)"),
):
    """
    List conversation sessions for the sub-tenant in the JWT, newest activity first.
    Returns session _id, last message content, and last message timestamp.

    Pagination (for infinite scroll / "load more" as the user scrolls down) is opt-in:
    pass page & size to get one page plus {total, has_more}; omit them to get all sessions.
    """
    try:
        if not authorization:
            return {"error": "Missing Authorization header", "conversations": []}

        token_payload = decode_jwt_no_verify(authorization)
        mongo_db, sub_tenant_id = extract_db_and_sub_tenant(token_payload)
        if not mongo_db or not sub_tenant_id:
            return {"error": "Invalid token: missing database or sub-tenant information.", "conversations": []}

        from pymongo import MongoClient
        mongo_uri = os.getenv("MONGO_URI")
        if not mongo_uri:
            logger.error("[GetConversations] MONGO_URI not configured")
            return {"error": "Service is temporarily unavailable.", "conversations": []}

        client = MongoClient(mongo_uri)
        db = client[mongo_db]
        collection = db["FleetiMessages"]

        paginate, page_n, size_n = _normalize_page_size(page, size, default_size=20)
        skip = (page_n - 1) * size_n

        # $facet computes the (optional) page slice AND the total count in one round trip,
        # so the FE knows whether more pages remain.
        items_stage: List[Dict[str, Any]] = []
        if paginate:
            items_stage += [{"$skip": skip}, {"$limit": size_n}]
        items_stage.append({"$project": {"_id": 1, "last_message": 1, "last_timestamp": 1}})

        pipeline = [
            {"$match": {"sub_tenant_id": sub_tenant_id}},
            {"$addFields": {"last_message": {"$arrayElemAt": ["$messages", -1]}}},
            {"$addFields": {"last_timestamp": "$last_message.timestamp"}},
            {"$sort": {"last_timestamp": -1}},
            {"$facet": {"items": items_stage, "total": [{"$count": "count"}]}},
        ]

        facet = list(collection.aggregate(pipeline))
        doc = facet[0] if facet else {}
        sessions = doc.get("items", []) or []
        total_arr = doc.get("total") or []
        total = total_arr[0].get("count", 0) if total_arr else 0

        conversations = []
        for session in sessions:
            last_msg = session.get("last_message") or {}
            last_text = (
                last_msg.get("user_input")
                or last_msg.get("human_response")
                or last_msg.get("llm_response")
                or last_msg.get("assistant_static_input")
                or ""
            )
            if not isinstance(last_text, str):
                last_text = json.dumps(last_text, default=str)

            last_ts = session.get("last_timestamp")
            conversations.append({
                "session_id": str(session.get("_id")),
                "last_message": last_text,
                "last_timestamp": _format_datetime_utc_z(last_ts),
            })

        has_more = bool(paginate and (skip + len(conversations) < total))
        return {
            "conversations": conversations,
            "page": page_n if paginate else 1,
            "size": size_n if paginate else total,
            "total": total,
            "has_more": has_more,
            "error": None,
        }
    except Exception as e:
        logger.debug("[GetConversationsError] %s", str(e))
        return {"error": "Unable to load conversations right now.", "conversations": []}


class SessionRequest(BaseModel):
    session_id: str = Field(..., description="Session ID (MongoDB document ID)")
    page: Optional[int] = Field(default=None, ge=1, description="1-based page from the newest message (omit for all)")
    size: Optional[int] = Field(default=None, ge=1, le=_MAX_PAGE_SIZE, description="Messages per page (omit for all)")


@app.post("/session")
async def get_session(request: SessionRequest, authorization: Optional[str] = Header(default=None)):
    """
    Get conversation messages for a specific session.
    Returns user_input and human_response in the same order as stored.
    """
    try:
        if not authorization:
            return {"error": "Missing Authorization header", "messages": []}

        token_payload = decode_jwt_no_verify(authorization)
        mongo_db, sub_tenant_id = extract_db_and_sub_tenant(token_payload)
        if not mongo_db or not sub_tenant_id:
            return {"error": "Invalid token: missing database or sub-tenant information.", "messages": []}

        from pymongo import MongoClient
        mongo_uri = os.getenv("MONGO_URI")
        if not mongo_uri:
            logger.error("[GetSession] MONGO_URI not configured")
            return {"error": "Service is temporarily unavailable.", "messages": []}

        client = MongoClient(mongo_uri)
        db = client[mongo_db]
        collection = db["FleetiMessages"]

        session_doc = collection.find_one({
            "sessionId": request.session_id,
            "sub_tenant_id": sub_tenant_id,
        })

        if not session_doc:
            return {"messages": [], "page": 1, "size": 0, "total": 0, "has_more": False, "error": None}

        messages = []
        for msg in session_doc.get("messages", []):
            if "assistant_static_input" in msg:
                messages.append({
                    "user_input": "",
                    "human_response": msg.get("assistant_static_input", ""),
                })
                continue
            if "user_input" in msg:
                messages.append({
                    "user_input": msg.get("user_input", ""),
                    "human_response": msg.get("human_response", msg.get("llm_response", "")),
                })

        total = len(messages)
        paginate, page_n, size_n = _normalize_page_size(request.page, request.size, default_size=10)

        if not paginate:
            # Legacy: return the full conversation in chronological order.
            return {"messages": messages, "page": 1, "size": total, "total": total, "has_more": False, "error": None}

        # Paginate from the NEWEST end: page 1 = the most recent `size` messages; higher
        # pages walk backwards in time (for "scroll up to load older"). Each page stays in
        # chronological (oldest -> newest) order so the FE can render/prepend it directly.
        end = total - (page_n - 1) * size_n
        start = max(0, total - page_n * size_n)
        page_items = messages[start:end] if end > 0 else []
        has_more = start > 0  # older messages remain above this page

        return {
            "messages": page_items,
            "page": page_n,
            "size": size_n,
            "total": total,
            "has_more": has_more,
            "error": None,
        }
    except Exception as e:
        logger.debug("[GetSessionError] %s", str(e))
        return {"error": "Unable to load session messages right now.", "messages": []}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("api:app", host="0.0.0.0", port=8000, reload=True)
