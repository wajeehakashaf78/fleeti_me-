"""
FastAPI Application for FLEETI - Fleet Management Chatbot System
Converts the CLI-based main.py to a REST API with dynamic parameters
"""

from fastapi import FastAPI, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import os
import json
import ast
import re
from typing import Optional, Dict, Any, List, Tuple
from datetime import datetime, timezone, timedelta
from urllib.parse import urlparse
from dotenv import load_dotenv
from dateutil import parser as dtparser

# Import all the components from main.py
from ConversationClassifier.conversation_classifier import ConversationClassifier
from FleetiHistorySaver.history_saver import FleetiHistorySaver
from FleetDbSummarizer.rag_pipeline import RAGPipeline
from FleetiMongoagent.prompt_blueprint import PROMPT as prompt_blueprint
from FleetiMongoagent.run_all_models import orchistrator_main as mongoagent_orchistrator_main
from FleetiQueryRunner.execute import LlmMongoRunner
from FleetiResponse.respond import generate_llm_response as generate_human_response
from jwt_utils import decode_jwt_no_verify, extract_db_and_sub_tenant

# FleetiReports modules (integrated)
from FleetiReports.llm_agent import llm_agent
from FleetiReports.mongo_handler import mongo_handler
from FleetiReports.api_handler import APIHandler
from FleetiReports.models import LLMResponse

# Load environment variables
load_dotenv()


def _load_cors_origins_from_env() -> List[str]:
    """
    Read allowed CORS origins from env var `CORS_ALLOWED_ORIGINS`.
    Supports:
    - "*" 
    - comma-separated string
    - JSON array string
    """
    raw = (os.getenv("CORS_ALLOWED_ORIGINS") or "*").strip()
    if raw == "*":
        return ["*"]

    # Try JSON list first.
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            cleaned = [str(x).strip() for x in parsed if str(x).strip()]
            return cleaned or ["*"]
    except Exception:
        pass

    # Fallback: comma-separated.
    cleaned = [x.strip() for x in raw.split(",") if x.strip()]
    return cleaned or ["*"]


def _format_datetime_utc_z(dt: Optional[Any]) -> Optional[str]:
    """
    Format a datetime for API response as UTC with Z suffix (ISO 8601).
    Handles naive datetimes from MongoDB (treated as UTC) and already-serialized strings.
    """
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

# Initialize FastAPI app
app = FastAPI(
    title="FLEETI API",
    description="Fleet Management Chatbot API",
    version="1.0.0"
)

# Enable CORS
_cors_origins = _load_cors_origins_from_env()
_allow_credentials = "*" not in _cors_origins  # Must be False when using "*"
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=_allow_credentials,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize global components that don't depend on dynamic parameters
classifier = ConversationClassifier()
pipeline = RAGPipeline()


# ================================
# FleetiReports Integration Helpers
# ================================
def _build_reports_base_url(base_url: str) -> str:
    return base_url.rstrip("/") + "/api/admin/reports"


def _extract_hostname(base_url: Optional[str]) -> Optional[str]:
    """
    Extract lowercase hostname from base_url.
    Accepts full URL (https://demo.tracking.me/) or raw host.
    """
    if not base_url:
        return None
    raw = base_url.strip()
    if not raw:
        return None
    parsed = urlparse(raw if "://" in raw else f"https://{raw}")
    if not parsed.hostname:
        return None
    return parsed.hostname.strip().lower().strip(".")


def _should_remove_sub_tenant_match(sub_tenant_id: str, base_url: Optional[str]) -> bool:
    """
    Remove sub_tenant_id query filters when FE base URL host equals JWT sub_tenant_id.
    Example:
      sub_tenant_id = "demo.tracking.me"
      base_url = "https://demo.tracking.me/"
    """
    host = _extract_hostname(base_url)
    if not host or not sub_tenant_id:
        return False
    return host == sub_tenant_id.strip().lower().strip(".")


# Collections that carry sub_tenant_id directly on documents.
# Any aggregation starting from one of these MUST filter by sub_tenant_id in
# its first $match; the guardrail below enforces this even when the LLM
# forgets. Collections NOT in this set (AlertHistory, Trip, DailyAnalytics,
# ...) must instead $lookup into one of these and filter via the join.
TENANT_AWARE_COLLECTIONS = frozenset({
    "AlertRule", "Asset", "AvlRecord", "AvlRecordLatest",
    "Device", "Driver", "Events", "Geofence",
})


def _extract_starting_collection(query_str: str) -> Optional[str]:
    """Return the collection name from 'db.<Collection>.(aggregate|find)(...)'."""
    m = re.search(r"db\.([A-Za-z0-9_]+)\.(aggregate|find)\s*\(", query_str)
    return m.group(1) if m else None


def _find_first_match_body_span(query_str: str) -> Optional[Tuple[int, int]]:
    """
    Locate the body braces of the first $match stage in an aggregate pipeline.
    Returns (open_brace_idx, close_brace_idx) or None if not found.
    Walks braces with string-awareness so constructors like ISODate("...")
    containing '{' or '}' would not break the depth count.
    """
    m = re.search(
        r"aggregate\s*\(\s*\[\s*\{\s*[\"']\$match[\"']\s*:\s*\{",
        query_str,
    )
    if not m:
        return None
    open_idx = m.end() - 1  # index of the match body's opening '{'
    depth = 0
    in_str = False
    str_ch: Optional[str] = None
    escape = False
    for i in range(open_idx, len(query_str)):
        ch = query_str[i]
        if escape:
            escape = False
            continue
        if ch == "\\":
            escape = True
            continue
        if in_str:
            if ch == str_ch:
                in_str = False
                str_ch = None
            continue
        if ch == '"' or ch == "'":
            in_str = True
            str_ch = ch
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return open_idx, i
    return None


def _enforce_sub_tenant_filter(
    query_str: str,
    tenant_value: str,
) -> Tuple[str, Optional[str]]:
    """
    Guarantee tenant isolation on a generated aggregation query.

    Returns (possibly modified query, error_message). When error_message is
    not None, the caller MUST reject the query instead of executing it.

    Rules:
      - Starting collection in TENANT_AWARE_COLLECTIONS:
          * First $match already filters by sub_tenant_id → no change.
          * First $match exists but missing sub_tenant_id → inject it.
          * No leading $match stage → prepend one with sub_tenant_id.
          * Not an aggregate pipeline (e.g. find()) → reject.
      - Starting collection not tenant-aware (AlertHistory, Trip, ...):
          * Require $lookup into a tenant-aware collection AND a
            sub_tenant_id filter somewhere, else reject.
    """
    coll = _extract_starting_collection(query_str)
    if not coll:
        # Unparseable shape — let the downstream parser produce the real error.
        return query_str, None

    if coll in TENANT_AWARE_COLLECTIONS:
        span = _find_first_match_body_span(query_str)
        if span is not None:
            open_idx, close_idx = span
            body = query_str[open_idx + 1 : close_idx]
            if re.search(r"[\"']sub_tenant_id[\"']\s*:", body):
                return query_str, None  # already filtered
            injection = f'"sub_tenant_id": "{tenant_value}"'
            if body.strip():
                injection += ", "
            insert_pos = open_idx + 1
            return (
                query_str[:insert_pos] + injection + query_str[insert_pos:],
                None,
            )

        # No leading $match. Prepend one right after 'aggregate(['.
        prep = re.search(r"aggregate\s*\(\s*\[", query_str)
        if not prep:
            return query_str, (
                f"Query on tenant-aware collection '{coll}' is not an "
                f"aggregate pipeline; refusing to run without sub_tenant_id."
            )
        insert_pos = prep.end()
        new_stage = f'{{"$match": {{"sub_tenant_id": "{tenant_value}"}}}}'
        tail = query_str[insert_pos:].lstrip()
        sep = "" if tail.startswith("]") else ", "
        return (
            query_str[:insert_pos] + new_stage + sep + query_str[insert_pos:],
            None,
        )

    # Collection has no sub_tenant_id field: require a tenant-aware $lookup
    # plus a sub_tenant_id filter somewhere in the pipeline.
    lookup_targets = re.findall(
        r"[\"']from[\"']\s*:\s*[\"']([A-Za-z0-9_]+)[\"']",
        query_str,
    )
    has_tenant_lookup = any(t in TENANT_AWARE_COLLECTIONS for t in lookup_targets)
    has_sub_tenant_key = re.search(
        r"[\"'](?:[^\"']*\.)?sub_tenant_id[\"']\s*:", query_str
    ) is not None
    if has_tenant_lookup and has_sub_tenant_key:
        return query_str, None
    return query_str, (
        f"Query on '{coll}' lacks tenant isolation: must $lookup into a "
        f"tenant-aware collection and filter by sub_tenant_id."
    )


def _compact_assistant_for_llm_history(assistant_value: Any) -> str:
    """
    Keep report responses compact when building LLM history.
    """
    if isinstance(assistant_value, dict) and "type" in assistant_value and "api_response" in assistant_value:
        return json.dumps(
            {
                "type": assistant_value.get("type"),
                "api_response": "valid_json_response"
            },
            separators=(",", ":")
        )
    if isinstance(assistant_value, str):
        return assistant_value
    try:
        return json.dumps(assistant_value, default=str)
    except Exception:
        return str(assistant_value)


def _build_reports_conversation_history(session_doc: Optional[Dict[str, Any]]) -> List[Dict[str, str]]:
    """
    Build conversation history for FleetiReports LLM from Mongo session doc.
    Excludes any messages that do not have a 'type' field (static initial message).
    """
    if not session_doc:
        return []
    history: List[Dict[str, str]] = []
    typed_messages = [m for m in session_doc.get("messages", []) if m.get("type") in ("general", "fleet")]
    # Only pass the most recent 5 typed messages to the reports LLM.
    for msg in typed_messages[-5:]:
        msg_type = msg.get("type")
        if msg_type == "general":
            user_content = msg.get("user_input", "")
            assistant_content = msg.get("llm_response", "")
            assistant_content = _compact_assistant_for_llm_history(assistant_content)
            history.append({"role": "user", "content": user_content})
            history.append({"role": "assistant", "content": assistant_content})
        elif msg_type == "fleet":
            user_content = msg.get("user_input", "")
            assistant_content = msg.get("human_response", "")
            assistant_content = _compact_assistant_for_llm_history(assistant_content)
            history.append({"role": "user", "content": user_content})
            history.append({"role": "assistant", "content": assistant_content})
    return history


def _parse_date_range(date_range_str: str) -> tuple[str, str]:
    if "," in date_range_str:
        parts = date_range_str.split(",", 1)
        return parts[0].strip(), parts[1].strip()
    return date_range_str.strip(), date_range_str.strip()


def _parse_user_utc_offset(user_time_zone: Optional[str]) -> timezone:
    """
    Parse timezone offsets in forms:
    +5, +5:00, -03:30, UTC+5, UTC +5:00, UTC-03:30
    Fallback to UTC when invalid.
    """
    if not user_time_zone:
        return timezone.utc
    m = re.match(
        r"^\s*(?:UTC\s*)?([+-])\s*(\d{1,2})(?::?\s*(\d{2}))?\s*$",
        user_time_zone,
        flags=re.IGNORECASE
    )
    if not m:
        return timezone.utc
    sign = 1 if m.group(1) == "+" else -1
    hours = int(m.group(2))
    minutes = int(m.group(3) or 0)
    if hours > 14 or minutes > 59:
        return timezone.utc
    return timezone(timedelta(hours=hours * sign, minutes=minutes * sign))


def _has_explicit_time_component(value: str) -> bool:
    return bool(re.search(r"\d{2}:\d{2}(?::\d{2})?", value))


def _to_utc_iso_z_for_report(
    value: str,
    user_tz: timezone,
    reinterpret_utc_as_user_local: bool = True
) -> str:
    dt = dtparser.parse(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=user_tz)
    elif reinterpret_utc_as_user_local:
        utc_like = dt.utcoffset() == timedelta(0)
        if utc_like and user_tz.utcoffset(None) != timedelta(0):
            dt = dt.replace(tzinfo=None).replace(tzinfo=user_tz)
    dt_utc = dt.astimezone(timezone.utc)
    return dt_utc.strftime("%Y-%m-%dT%H:%M:%SZ")


def _normalize_report_date_range_to_utc(
    date_range_str: str,
    user_time_zone: Optional[str]
) -> tuple[str, str]:
    """
    1) Parse start/end from date_range.
    2) If time is missing:
       - start gets 00:00:00
       - end gets 23:59:59
       - when same date, enforce those boundaries.
    3) Convert both to UTC Z format.
    """
    start_raw, end_raw = _parse_date_range(date_range_str)
    user_tz = _parse_user_utc_offset(user_time_zone)

    start_value = start_raw
    end_value = end_raw

    # Add day boundaries when time is absent
    if not _has_explicit_time_component(start_value):
        start_value = f"{start_value} 00:00:00"
    if not _has_explicit_time_component(end_value):
        end_value = f"{end_value} 23:59:59"

    # If both dates are same date, guarantee full-day bounds
    try:
        start_day = dtparser.parse(start_raw).date()
        end_day = dtparser.parse(end_raw).date()
        if start_day == end_day:
            start_value = f"{start_day.isoformat()} 00:00:00"
            end_value = f"{end_day.isoformat()} 23:59:59"
    except Exception:
        pass

    start_utc = _to_utc_iso_z_for_report(start_value, user_tz=user_tz)
    end_utc = _to_utc_iso_z_for_report(end_value, user_tz=user_tz)
    return start_utc, end_utc


def _dedupe_items_by_date_asset_id(items: List[Any]) -> List[Any]:
    """
    Keep first item for each:
    - (date, assetId) when date exists
    - assetId only when date does not exist
    Items without assetId are kept as-is.
    """
    seen: set[tuple[str, str]] = set()
    deduped: List[Any] = []

    date_keys = ("date", "Date", "reportDate", "ReportDate", "startDate", "StartDate")
    asset_keys = ("assetId", "AssetId", "asset_id")

    for item in items:
        if not isinstance(item, dict):
            deduped.append(item)
            continue

        asset_value = next((item.get(k) for k in asset_keys if item.get(k) is not None), None)
        date_value = next((item.get(k) for k in date_keys if item.get(k) is not None), None)

        if asset_value is None:
            deduped.append(item)
            continue

        asset_key = str(asset_value)
        if date_value is None:
            key = ("__asset_only__", asset_key)
        else:
            key = (str(date_value), asset_key)

        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)

    return deduped


def _dedupe_report_api_response(api_response: Any) -> Any:
    """
    Dedupe report API list payloads in common shapes:
    1) api_response.data.items
    2) api_response.data.data.items
    3) api_response.data.data (list of objects by assetId)
    """
    if not isinstance(api_response, dict):
        return api_response

    data_wrapper = api_response.get("data")
    if not isinstance(data_wrapper, dict):
        return api_response

    if isinstance(data_wrapper.get("items"), list):
        data_wrapper["items"] = _dedupe_items_by_date_asset_id(data_wrapper["items"])

    nested_data = data_wrapper.get("data")
    if isinstance(nested_data, dict) and isinstance(nested_data.get("items"), list):
        nested_data["items"] = _dedupe_items_by_date_asset_id(nested_data["items"])
    elif isinstance(nested_data, list):
        # Trip-like shape: data.data is a list of asset objects.
        # Keep only the first object for each assetId.
        seen_asset_ids: set[str] = set()
        deduped_assets: List[Any] = []
        for row in nested_data:
            if not isinstance(row, dict):
                deduped_assets.append(row)
                continue
            asset_id = row.get("assetId") or row.get("AssetId") or row.get("asset_id")
            if asset_id is None:
                deduped_assets.append(row)
                continue
            key = str(asset_id)
            if key in seen_asset_ids:
                continue
            seen_asset_ids.add(key)
            deduped_assets.append(row)
        data_wrapper["data"] = deduped_assets

    return api_response


async def _process_report_request(
    llm_response: LLMResponse,
    db_name: str,
    sub_tenant_id: Optional[str],
    api_handler: APIHandler,
    user_time_zone: Optional[str] = None,
    remove_sub_tenant_match: bool = False
) -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "mongodb_query_result": None,
        "api_response": None,
        "start_datetime": None,
        "end_datetime": None
    }
    report_type = llm_response.type
    pre_req = llm_response.pre_req
    if not pre_req:
        return result

    resolved_sub_tenant_id = None if remove_sub_tenant_match else sub_tenant_id

    asset_ids = None
    if pre_req.asset_plate_numbers:
        query_result = mongo_handler.get_asset_ids_by_plate_numbers(
            db_name,
            pre_req.asset_plate_numbers,
            sub_tenant_id=resolved_sub_tenant_id
        )
        result["mongodb_query_result"] = query_result
        if query_result["success"] and query_result["asset_ids"]:
            asset_ids = ",".join(query_result["asset_ids"])
    elif pre_req.group_names:
        query_result = mongo_handler.get_asset_ids_by_group_names(
            db_name,
            pre_req.group_names,
            sub_tenant_id=resolved_sub_tenant_id
        )
        result["mongodb_query_result"] = query_result
        if query_result["success"] and query_result["asset_ids"]:
            asset_ids = ",".join(query_result["asset_ids"])

    driver_ids = None
    if pre_req.driver_names:
        query_result = mongo_handler.get_driver_ids_by_names(
            db_name,
            pre_req.driver_names,
            sub_tenant_id=resolved_sub_tenant_id
        )
        result["mongodb_query_result"] = query_result
        if query_result["success"] and query_result["driver_ids"]:
            driver_ids = ",".join(query_result["driver_ids"])

    start_date = None
    end_date = None
    if pre_req.date_range:
        start_date, end_date = _normalize_report_date_range_to_utc(
            pre_req.date_range,
            user_time_zone
        )

    if report_type == "Trip":
        if asset_ids and start_date and end_date:
            result["api_response"] = await api_handler.fetch_trip_report(asset_ids, start_date, end_date)
    elif report_type == "FleetSummary":
        if asset_ids:
            result["api_response"] = await api_handler.fetch_fleet_summary(asset_ids)
    elif report_type == "FleetPerformanceSummary":
        if asset_ids and start_date and end_date:
            result["api_response"] = await api_handler.fetch_fleet_performance_summary(
                asset_ids, start_date, end_date
            )
    elif report_type == "SIM":
        if asset_ids and start_date and end_date:
            result["api_response"] = await api_handler.fetch_sim_report(asset_ids, start_date, end_date)
    elif report_type == "Utilization":
        if start_date and end_date:
            result["api_response"] = await api_handler.fetch_utilization_report(start_date, end_date)
    elif report_type in ("DriverBehaviour", "DrivingBehaviour", "DriverBehavior"):
        if driver_ids and start_date and end_date:
            result["api_response"] = await api_handler.fetch_generic_report(
                report_type, driver_ids=driver_ids, start_date=start_date, end_date=end_date
            )
    else:
        if asset_ids and start_date and end_date:
            result["api_response"] = await api_handler.fetch_generic_report(
                report_type, asset_ids=asset_ids, start_date=start_date, end_date=end_date
            )

    result["api_response"] = _dedupe_report_api_response(result.get("api_response"))
    # Expose normalized UTC date-time range only when date range existed and report call was made.
    if start_date and end_date and result.get("api_response") is not None:
        result["start_datetime"] = start_date
        result["end_datetime"] = end_date
    return result


def _user_friendly_failure_message() -> str:
    """Safe fallback message for user-facing failures."""
    return (
        "I couldn't process your request right now. "
        "Please rephrase your question and try again."
    )

# Pydantic models for request/response
class ChatRequest(BaseModel):
    base_url: str = Field(..., description="Base URL from FE (e.g., https://qa.dev-iot.tracking.me/)")
    assistant_static_input: Optional[str] = Field(None, description="Initial static assistant message")
    user_input: Optional[str] = Field(None, description="User's message/question")
    session_id: Optional[str] = Field(None, description="Session ID (MongoDB document ID)")
    time_zone: Optional[str] = Field(
        default=None,
        description="User timezone in format 'UTC +/- X:XX' (e.g., 'UTC +5:00')"
    )

class ChatResponse(BaseModel):
    human_response: Optional[Any] = Field(default=None, description="Natural language response or structured data")
    session_id: Optional[str] = Field(default=None, description="Session ID (MongoDB document ID)")
    error: bool = Field(default=False, description="Whether an error occurred")


@app.get("/")
async def root():
    """Health check endpoint"""
    return {
        "status": "ok",
        "message": "FLEETI API is running",
        "version": "1.0.0"
    }


@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest, authorization: Optional[str] = Header(default=None)):
    """
    Main chat endpoint - processes user input and returns AI response
    
    Args:
        request: ChatRequest containing sub_tenant_id, session_id, mongo_db, user_input
        
    Returns:
        ChatResponse with human_response and error flag
    """
    try:
        if not authorization:
            return ChatResponse(
                human_response="Missing Authorization header.",
                error=True
            )

        token_payload = decode_jwt_no_verify(authorization)
        mongo_db, sub_tenant_id = extract_db_and_sub_tenant(token_payload)

        if not mongo_db or not sub_tenant_id:
            return ChatResponse(
                human_response="Invalid token: missing database or sub-tenant information.",
                error=True
            )

        # Scenario 1: Create session with static assistant message
        if request.assistant_static_input is not None:
            history_saver = FleetiHistorySaver(
                session_id="static_session",
                sub_tenant_id=sub_tenant_id,
                mongo_db=mongo_db,
            )
            session_id = history_saver.save_static_message(request.assistant_static_input)
            return ChatResponse(
                human_response=None,
                session_id=session_id,
                error=False
            )

        # Scenario 2: Normal chat flow
        if not request.user_input or not request.session_id:
            return ChatResponse(
                human_response="Missing user_input or session_id.",
                error=True
            )

        # Initialize history saver with dynamic session_id and sub_tenant_id
        history_saver = FleetiHistorySaver(
            session_id=request.session_id,
            sub_tenant_id=sub_tenant_id,
            mongo_db=mongo_db,
        )

        # Load existing conversation history (excludes static message).
        # Always set classifier history to this session's history; for a new session
        # this must be [] so we don't leak history from other sessions (e.g. wrong
        # plate numbers from a previous chat).
        existing_history = history_saver.load_session_history()
        classifier.conversation_history = existing_history[-8:] if existing_history else []

        # Process message through classifier
        refined_message, classification, llm_response = classifier.process_message(request.user_input)
        
        # Handle classification result
        # Note: classification can be "general conversation" or "fleet"
        if classification == "general conversation":
            # General conversation - return LLM response directly
            # The classifier should always provide a response for general conversation
            # (it defaults to a greeting if none is provided)
            if llm_response:
                # Save general message to history
                history_saver.save_general_message(
                    user_input=request.user_input,
                    refined_message=refined_message,
                    llm_response=llm_response
                )
                
                return ChatResponse(
                    human_response=llm_response,
                    error=False
                )
            else:
                # Fallback: if somehow no response was generated, use default
                default_response = "Helloooo, I am your fleet assistant. How can I help you today?"
                history_saver.save_general_message(
                    user_input=request.user_input,
                    refined_message=refined_message,
                    llm_response=default_response
                )
                
                return ChatResponse(
                    human_response=default_response,
                    error=False
                )
        
        elif classification == "fleet":
            # Fleet query - First check with FleetiReports (integrated)
            base_api_url = _build_reports_base_url(request.base_url)
            reports_api_handler = APIHandler(base_url=base_api_url, access_token=authorization)

            session_doc = history_saver.get_session_document()
            reports_history = _build_reports_conversation_history(session_doc)
            report_llm_response = llm_agent.process_user_input(refined_message, reports_history)

            def _is_empty_pre_req(pre_req_obj: Any) -> bool:
                if pre_req_obj is None:
                    return True
                return (
                    not getattr(pre_req_obj, "asset_plate_numbers", None)
                    and not getattr(pre_req_obj, "group_names", None)
                    and not getattr(pre_req_obj, "driver_names", None)
                    and not getattr(pre_req_obj, "date_range", None)
                    and not getattr(pre_req_obj, "geofence_names", None)
                )

            # Fallback retry: if report type is recognized but prerequisites are missing,
            # retry without history to reduce context pollution.
            if (
                report_llm_response
                and report_llm_response.type
                and report_llm_response.type.lower() != "invalid"
                and _is_empty_pre_req(report_llm_response.pre_req)
            ):
                retry_response = llm_agent.process_user_input(refined_message, None)
                if retry_response and not _is_empty_pre_req(retry_response.pre_req):
                    report_llm_response = retry_response

            # Deterministic guardrail: FleetSummary must not require date range.
            if report_llm_response and report_llm_response.type == "FleetSummary":
                if report_llm_response.pre_req is not None:
                    report_llm_response.pre_req.date_range = None
                    has_asset_or_group = bool(
                        report_llm_response.pre_req.asset_plate_numbers
                        or report_llm_response.pre_req.group_names
                    )
                    if has_asset_or_group:
                        report_llm_response.message = ""
                    elif not report_llm_response.message or not report_llm_response.message.strip():
                        report_llm_response.message = (
                            "Please provide the asset plate number(s) or group name(s) for the Fleet Summary Report."
                        )

            print("\n--- Report LLM Response ---")
            if report_llm_response:
                try:
                    print(json.dumps(report_llm_response.model_dump(), indent=2, default=str))
                except Exception:
                    print(f"type: {getattr(report_llm_response, 'type', None)}")
                    print(f"pre_req: {getattr(report_llm_response, 'pre_req', None)}")
                    print(f"message: {getattr(report_llm_response, 'message', None)}")
            else:
                print("None")

            response_type = report_llm_response.type if report_llm_response else "invalid"
            response_message = report_llm_response.message if report_llm_response else ""
            api_response_data = None
            
            # Check if type is "invalid" - route to FleetDbSummarizer (RAG pipeline)
            if response_type.lower() == "invalid":

                # Check if message field is not empty - then, this IS the final response
                if response_message and response_message.strip():
                    final_response = response_message
                    
                    # Save FleetiReports response as fleet message
                    history_saver.save_fleet_message(
                        user_input=request.user_input,
                        refined_message=refined_message,
                        selected_collections=[],
                        query="",
                        query_response=[],
                        human_response=final_response
                    )
                    
                    # Update classifier history
                    if classifier.conversation_history:
                        classifier.conversation_history[-1]["assistant"] = final_response
                    
                    return ChatResponse(
                        human_response=final_response,
                        error=False
                    )
                else:
                    # Message is empty - use existing RAG pipeline
                
                    # Step 1: RAG Pipeline - get relevant schemas
                    rag_result = pipeline.query(refined_message, use_llm=True)
                    
                    # Extract schemas
                    schemas = "\n\n".join(
                        collection_info.get("schema", "")
                        for collection_info in rag_result.get('collection_json', {}).get("collection_data", {}).values()
                    )
                    
                    # Get selected collections
                    collection_json = rag_result.get('collection_json', {})
                    collection_data = collection_json.get('collection_data', {})
                    
                    selected_collections = []
                    if collection_data:
                        for parent_collection, data in collection_data.items():
                            sub_collections = data.get('selected_sub_collections', [])
                            selected_collections.extend(sub_collections)
                    else:
                        # Fallback: parse from collections string
                        collections_output = rag_result.get('collections', '[]')
                        try:
                            selected_collections = ast.literal_eval(str(collections_output))
                            if not isinstance(selected_collections, list):
                                selected_collections = []
                        except Exception as e:
                            # Try regex fallback
                            list_match = re.search(r'\[(.*?)\]', str(collections_output))
                            if list_match:
                                list_content = list_match.group(1)
                                selected_collections = [c.strip().strip("'\"") for c in list_content.split(',') if c.strip()]
                            else:
                                selected_collections = []
                    
                    # Step 2: Generate MongoDB query via FleetiMongoagent
                    now_utc = datetime.now(timezone.utc)
                    full_prompt = (
                        prompt_blueprint
                        .replace("{current_date}", now_utc.strftime("%Y-%m-%d"))
                        .replace("{current_datetime_utc}", now_utc.strftime("%Y-%m-%dT%H:%M:%SZ"))
                        .replace("{schemas}", schemas)
                        .replace("{refined_message}", refined_message)
                    )
                    mongoagent_response = mongoagent_orchistrator_main(full_prompt)
                    
                    if not mongoagent_response:
                        return ChatResponse(
                            human_response="I couldn't generate a database query for your question. Please try rephrasing.",
                            error=True
                        )

                    # Always apply tenant isolation using the sub_tenant_id from
                    # the JWT. Substitute the LLM's placeholder, then enforce the
                    # guardrail so queries on tenant-aware collections always
                    # carry a sub_tenant_id filter.
                    patterns = [
                        (r'("(?:[^"]*\.)?sub_tenant_id"\s*:\s*)"sub_tenant_id"', r'\1"' + sub_tenant_id + '"'),
                        (r'("(?:[^"]*\.)?sub_tenant_id"\s*:\s*)\'sub_tenant_id\'', r'\1"' + sub_tenant_id + '"'),
                        (r'(\'(?:[^\']*\.)?sub_tenant_id\'\s*:\s*)"sub_tenant_id"', r'\1"' + sub_tenant_id + '"'),
                        (r'(\'(?:[^\']*\.)?sub_tenant_id\'\s*:\s*)\'sub_tenant_id\'', r'\1"' + sub_tenant_id + '"'),
                    ]
                    for pattern, replacement in patterns:
                        mongoagent_response = re.sub(pattern, replacement, mongoagent_response)

                    pre_guard = mongoagent_response
                    mongoagent_response, guard_error = _enforce_sub_tenant_filter(
                        mongoagent_response,
                        sub_tenant_id,
                    )
                    if guard_error:
                        print(f"[SubTenantGuard] Rejected — {guard_error}")
                        print(f"[SubTenantGuard] Query: {mongoagent_response[:500]}")
                        return ChatResponse(
                            human_response=_user_friendly_failure_message(),
                            error=False
                        )
                    if mongoagent_response != pre_guard:
                        print("[SubTenantGuard] Patched query to inject sub_tenant_id filter")
                    else:
                        print("[SubTenantGuard] Query already contained sub_tenant_id filter")

                    # Step 3: Execute query with dynamic mongo_db from JWT
                    query_runner = LlmMongoRunner(mongo_db=mongo_db)

                    try:
                        results = query_runner.run(
                            mongoagent_response,
                            limit=10,
                            user_time_zone=request.time_zone,
                            remove_sub_tenant_match=False,
                        )
                        
                        # Convert results to string
                        results_str = json.dumps(results, indent=2, default=str) if results else "[]"
                        
                        # Step 4: Generate human-friendly response
                        human_response = generate_human_response(request.user_input, refined_message, results_str)
                        
                        # Save fleet message to history
                        history_saver.save_fleet_message(
                            user_input=request.user_input,
                            refined_message=refined_message,
                            selected_collections=selected_collections,
                            query=mongoagent_response,
                            query_response=results,
                            human_response=human_response
                        )
                        
                        # Update classifier history with actual response
                        if classifier.conversation_history:
                            classifier.conversation_history[-1]["assistant"] = human_response
                        
                        return ChatResponse(
                            human_response=human_response,
                            error=False
                        )
                    
                    except Exception as query_error:
                        # Log technical error server-side only.
                        print(f"[QueryRunnerError] {str(query_error)}")
                        return ChatResponse(
                            human_response=_user_friendly_failure_message(),
                            error=False
                        )
            else:
                # Type is NOT "invalid" - use FleetiReports response

                # Check if message field is not empty - this IS the final response
                if response_message and response_message.strip():
                    final_response = response_message

                    # Save FleetiReports response as fleet message
                    history_saver.save_fleet_message(
                        user_input=request.user_input,
                        refined_message=refined_message,
                        selected_collections=[],
                        query="",
                        query_response=[],
                        human_response=final_response
                    )

                    # Update classifier history
                    if classifier.conversation_history:
                        classifier.conversation_history[-1]["assistant"] = final_response

                    return ChatResponse(
                        human_response=final_response,
                        error=False
                    )
                else:
                    # Message is empty - process report request
                    remove_sub_tenant_match_for_reports = _should_remove_sub_tenant_match(
                        sub_tenant_id=sub_tenant_id,
                        base_url=request.base_url
                    )
                    processing_result = await _process_report_request(
                        report_llm_response,
                        mongo_db,
                        sub_tenant_id,
                        reports_api_handler,
                        request.time_zone,
                        remove_sub_tenant_match=remove_sub_tenant_match_for_reports
                    )
                    api_response_data = processing_result.get("api_response")
                    mongodb_query_result = processing_result.get("mongodb_query_result")
                    report_start_datetime = processing_result.get("start_datetime")
                    report_end_datetime = processing_result.get("end_datetime")

                    # If report API failed or returned empty result set, return text response instead of JSON
                    is_report_api_failure = (
                        isinstance(api_response_data, dict)
                        and api_response_data.get("success") is False
                    )
                    is_asset_or_driver_not_found = (
                        api_response_data is None
                        and isinstance(mongodb_query_result, dict)
                        and mongodb_query_result.get("success") is True
                        and (
                            ("asset_ids" in mongodb_query_result and len(mongodb_query_result.get("asset_ids") or []) == 0)
                            or ("driver_ids" in mongodb_query_result and len(mongodb_query_result.get("driver_ids") or []) == 0)
                        )
                    )
                    api_data_wrapper = api_response_data.get("data") if isinstance(api_response_data, dict) else None
                    nested_data = api_data_wrapper.get("data") if isinstance(api_data_wrapper, dict) else None
                    # Support these empty-data shapes:
                    # 1) api_response.data.items == []
                    # 2) api_response.data.data.items == []
                    # 3) api_response.data.data == []
                    is_empty_report_data = False
                    if isinstance(api_data_wrapper, dict) and isinstance(api_data_wrapper.get("items"), list):
                        is_empty_report_data = len(api_data_wrapper.get("items")) == 0
                    elif isinstance(nested_data, dict) and isinstance(nested_data.get("items"), list):
                        is_empty_report_data = len(nested_data.get("items")) == 0
                    elif isinstance(nested_data, list):
                        is_empty_report_data = len(nested_data) == 0

                    if is_report_api_failure or is_empty_report_data or is_asset_or_driver_not_found:
                        report_results_payload = api_response_data if api_response_data is not None else mongodb_query_result
                        report_results_str = json.dumps(report_results_payload, indent=2, default=str) if report_results_payload else "{}"
                        final_response = generate_human_response(
                            request.user_input,
                            refined_message,
                            report_results_str
                        )
                    else:
                        # Default report behavior: return structured response
                        final_response = {
                            "type": response_type,
                            "api_response": api_response_data
                        }
                        if report_start_datetime and report_end_datetime:
                            final_response["start_datetime"] = report_start_datetime
                            final_response["end_datetime"] = report_end_datetime

                    # Save FleetiReports response as fleet message
                    history_saver.save_fleet_message(
                        user_input=request.user_input,
                        refined_message=refined_message,
                        selected_collections=[],
                        query="",
                        query_response=[],
                        human_response=final_response
                    )

                    return ChatResponse(
                        human_response=final_response,
                        error=False
                    )
        
        else:
            # Unknown classification
            return ChatResponse(
                human_response="I couldn't understand your message. Please try again.",
                error=True
            )
    
    except Exception as e:
        # Log technical error server-side only.
        print(f"[UnhandledChatError] {str(e)}")
        # Catch-all error handler
        return ChatResponse(
            human_response=_user_friendly_failure_message(),
            error=False
        )


@app.get("/conversations")
async def get_conversations(authorization: Optional[str] = Header(default=None)):
    """
    Get list of all conversation sessions for the sub-tenant in the JWT.
    Returns session _id, last message content, and last message timestamp.
    """
    try:
        if not authorization:
            return {"error": "Missing Authorization header", "conversations": []}

        token_payload = decode_jwt_no_verify(authorization)
        mongo_db, sub_tenant_id = extract_db_and_sub_tenant(token_payload)
        if not mongo_db or not sub_tenant_id:
            return {"error": "Invalid token: missing database or sub-tenant information.", "conversations": []}

        from pymongo import MongoClient
        load_dotenv()
        mongo_uri = os.getenv("MONGO_URI")
        if not mongo_uri:
            return {"error": "MONGO_URI not configured", "conversations": []}

        client = MongoClient(mongo_uri)
        db = client[mongo_db]
        collection = db["FleetiMessages"]

        pipeline = [
            {"$match": {"sub_tenant_id": sub_tenant_id}},
            {"$addFields": {"last_message": {"$arrayElemAt": ["$messages", -1]}}},
            {"$addFields": {"last_timestamp": "$last_message.timestamp"}},
            {"$sort": {"last_timestamp": -1}},
            {"$project": {"_id": 1, "last_message": 1, "last_timestamp": 1}}
        ]

        sessions = list(collection.aggregate(pipeline))

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
                "last_timestamp": _format_datetime_utc_z(last_ts)
            })

        return {"conversations": conversations, "error": None}
    except Exception as e:
        return {"error": str(e), "conversations": []}


class SessionRequest(BaseModel):
    session_id: str = Field(..., description="Session ID (MongoDB document ID)")


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
        load_dotenv()
        mongo_uri = os.getenv("MONGO_URI")
        if not mongo_uri:
            return {"error": "MONGO_URI not configured", "messages": []}

        client = MongoClient(mongo_uri)
        db = client[mongo_db]
        collection = db["FleetiMessages"]

        session_doc = collection.find_one({
            "sessionId": request.session_id,
            "sub_tenant_id": sub_tenant_id
        })

        if not session_doc:
            return {"messages": [], "error": None}

        messages = []
        for msg in session_doc.get("messages", []):
            if "assistant_static_input" in msg:
                messages.append({
                    "user_input": "",
                    "human_response": msg.get("assistant_static_input", "")
                })
                continue
            if "user_input" in msg:
                messages.append({
                    "user_input": msg.get("user_input", ""),
                    "human_response": msg.get("human_response", msg.get("llm_response", ""))
                })

        return {"messages": messages, "error": None}
    except Exception as e:
        return {"error": str(e), "messages": []}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "api:app",
        host="0.0.0.0",
        port=8000,
        reload=True
    )
