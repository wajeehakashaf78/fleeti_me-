"""
Tool definitions + implementations for the FLEETI GPT-5 agentic orchestrator.

Each tool is a thin wrapper over an already-existing, well-tested backend module:
  - get_query_context -> FleetiAgent.schema_service (deterministic catalog, no ML/RAG)
  - run_fleet_query   -> FleetiQueryRunner.LlmMongoRunner.run_payload (object path)
  - run_report        -> FleetiCommon.process_report_request (mongo_handler + APIHandler)

Tenant isolation, timezone localization, and result capping happen here / inside the
runner, on parsed objects — never via string repair.
"""

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from FleetiQueryRunner.execute import LlmMongoRunner
from FleetiReports.api_handler import APIHandler
from FleetiReports.models import LLMResponse, PreRequisites
from FleetiResponse.respond import convert_query_response_times_for_user
from FleetiCommon import (
    build_reports_base_url,
    process_report_request,
    report_outcome_status,
)
from FleetiAgent.schema_service import build_menu, get_query_context, RULES

logger = logging.getLogger(__name__)

MAX_QUERY_LIMIT = 50
DEFAULT_QUERY_LIMIT = 10


# ================================
# Per-request tool context
# ================================
@dataclass
class ToolContext:
    """Carries per-request scope + captures side-effects for the endpoint."""
    mongo_db: str
    sub_tenant_id: Optional[str]
    base_url: str
    authorization: Optional[str]
    time_zone: Optional[str]
    remove_sub_tenant_match: bool

    # captured side-effects (read by the endpoint after the run)
    used_fleet_query: bool = False
    last_fleet_query: str = ""
    last_fleet_rows: List[Dict[str, Any]] = field(default_factory=list)
    selected_collections: List[str] = field(default_factory=list)
    report_payload: Optional[Dict[str, Any]] = None
    report_has_data: bool = False


# ================================
# Tool JSON-schema definitions (Responses API "function" tools)
# ================================
_RUN_FLEET_QUERY_DESCRIPTION = (
    "Execute a READ-ONLY MongoDB query and return matching rows. Call get_query_context FIRST "
    "to fetch the exact field paths, join hints, and examples for the collections you need. "
    "Pass the query as a parsed object — it is executed as-is, so do NOT wrap it in markdown or "
    "in db.collection.aggregate(...).\n\n" + RULES
)

TOOL_DEFINITIONS: List[Dict[str, Any]] = [
    {
        "type": "function",
        "name": "get_query_context",
        "description": (
            "Fetch the exact schema fields, join hints, and 2-3 relevant query examples for the "
            "fleet collections/sections you need — call this BEFORE run_fleet_query. Request "
            "sections by name, or a top-level collection name. Use this menu to choose:\n\n"
            + build_menu()
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "sections": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Collection or section names to fetch fields for, e.g. ['AvlRecordLatest'], "
                        "['Asset','Trip'], or ['asset_details_document_status_flags']."
                    ),
                },
                "intent": {
                    "type": "string",
                    "description": "Short description of what you're trying to query (used to pick relevant examples).",
                },
            },
            "required": ["sections"],
        },
    },
    {
        "type": "function",
        "name": "run_fleet_query",
        "description": _RUN_FLEET_QUERY_DESCRIPTION,
        "parameters": {
            "type": "object",
            "properties": {
                "collection": {
                    "type": "string",
                    "description": "Starting collection name (e.g. Asset, AvlRecordLatest, Trip, Driver, Events).",
                },
                "operation": {
                    "type": "string",
                    "enum": ["aggregate", "find"],
                    "description": "Mongo operation. Prefer aggregate.",
                },
                "pipeline": {
                    "type": "array",
                    "items": {"type": "object"},
                    "description": "Aggregation pipeline stages (when operation=aggregate).",
                },
                "filter": {
                    "type": "object",
                    "description": "Find filter document (when operation=find).",
                },
                "projection": {
                    "type": "object",
                    "description": "Optional find projection (when operation=find).",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max documents to return (default 10, max 50).",
                },
            },
            "required": ["collection", "operation"],
        },
    },
    {
        "type": "function",
        "name": "run_report",
        "description": (
            "Generate one of the supported fleet reports. Only call this once all required "
            "prerequisites for the chosen report type are known (ask the user otherwise). "
            "Provide resolved dates; do not invent a date range."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "report_type": {
                    "type": "string",
                    "description": "Supported report type string, e.g. Trip, FleetSummary, Odometer, Idling, DriverBehavior.",
                },
                "asset_plate_numbers": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Plate numbers, or ['ALL'] for every asset.",
                },
                "group_names": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Group names, or ['ALL'] for every group.",
                },
                "driver_names": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Driver names, or ['ALL'] for every driver (DriverBehavior only).",
                },
                "date_range": {
                    "type": "string",
                    "description": "Resolved range 'YYYY-MM-DD,YYYY-MM-DD' (single date allowed). Omit for FleetSummary.",
                },
                "geofence_names": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Geofence names when relevant.",
                },
            },
            "required": ["report_type"],
        },
    },
]


# ================================
# Tool implementations
# ================================
def _tool_get_query_context(args: Dict[str, Any], ctx: ToolContext) -> Dict[str, Any]:
    sections = args.get("sections") or []
    if isinstance(sections, str):
        sections = [sections]
    if not sections:
        return {"error": "missing_sections"}
    intent = args.get("intent")

    ctx.selected_collections = list(sections)
    return get_query_context(sections, intent)


def _tool_run_fleet_query(args: Dict[str, Any], ctx: ToolContext) -> Dict[str, Any]:
    collection = (args.get("collection") or "").strip()
    if not collection:
        return {"error": "missing_collection"}

    operation = (args.get("operation") or "aggregate").strip().lower()
    try:
        limit = int(args.get("limit") or DEFAULT_QUERY_LIMIT)
    except (TypeError, ValueError):
        limit = DEFAULT_QUERY_LIMIT
    limit = max(1, min(limit, MAX_QUERY_LIMIT))

    if operation == "find":
        flt = args.get("filter") or {}
        projection = args.get("projection")
        payload: Any = {"filter": flt, "projection": projection} if projection else flt
    else:
        operation = "aggregate"
        payload = args.get("pipeline") or []

    runner = LlmMongoRunner(mongo_db=ctx.mongo_db)
    try:
        rows = runner.run_payload(
            collection,
            operation,
            payload,
            limit=limit,
            user_time_zone=ctx.time_zone,
            sub_tenant_id=None if ctx.remove_sub_tenant_match else ctx.sub_tenant_id,
            remove_sub_tenant_match=ctx.remove_sub_tenant_match,
        )
    except Exception as exc:  # surface a compact error so the model can respond gracefully
        logger.debug("[run_fleet_query] failed: %s", exc)
        return {"error": "query_failed", "detail": str(exc)[:300]}

    ctx.used_fleet_query = True
    ctx.last_fleet_query = runner.last_executed_query or ""
    ctx.last_fleet_rows = rows

    localized = convert_query_response_times_for_user(rows, ctx.time_zone)
    return {"row_count": len(localized), "rows": localized}


async def _tool_run_report(args: Dict[str, Any], ctx: ToolContext) -> Dict[str, Any]:
    report_type = (args.get("report_type") or "").strip()
    if not report_type:
        return {"error": "missing_report_type"}

    pre_req = PreRequisites(
        asset_plate_numbers=args.get("asset_plate_numbers"),
        group_names=args.get("group_names"),
        driver_names=args.get("driver_names"),
        date_range=args.get("date_range"),
        geofence_names=args.get("geofence_names"),
    )
    # FleetSummary never takes a date range.
    if report_type == "FleetSummary":
        pre_req.date_range = None

    llm_response = LLMResponse(type=report_type, pre_req=pre_req, message="")

    api_handler = APIHandler(
        base_url=build_reports_base_url(ctx.base_url),
        access_token=ctx.authorization,
    )

    result = await process_report_request(
        llm_response,
        ctx.mongo_db,
        ctx.sub_tenant_id,
        api_handler,
        ctx.time_zone,
        remove_sub_tenant_match=ctx.remove_sub_tenant_match,
    )

    api_response = result.get("api_response")
    mongodb_query_result = result.get("mongodb_query_result")
    status = report_outcome_status(api_response, mongodb_query_result)

    if status == "data":
        payload: Dict[str, Any] = {"type": report_type, "api_response": api_response}
        if result.get("start_datetime") and result.get("end_datetime"):
            payload["start_datetime"] = result["start_datetime"]
            payload["end_datetime"] = result["end_datetime"]
        ctx.report_payload = payload
        ctx.report_has_data = True
        # Signal the agent loop to short-circuit and return the structured payload.
        return {"status": "data", "report_type": report_type}

    # Empty / failure / not-found: hand a localized summary to the model so it can
    # write a natural-language explanation.
    payload_for_model = api_response if api_response is not None else mongodb_query_result
    localized = convert_query_response_times_for_user(payload_for_model, ctx.time_zone)
    return {"status": status, "report_type": report_type, "result": localized}


async def execute_tool(name: str, args: Dict[str, Any], ctx: ToolContext) -> Dict[str, Any]:
    """Dispatch a single tool call. Returns the JSON-able result handed back to the model."""
    if name == "get_query_context":
        return _tool_get_query_context(args, ctx)
    if name == "run_fleet_query":
        return _tool_run_fleet_query(args, ctx)
    if name == "run_report":
        return await _tool_run_report(args, ctx)
    return {"error": f"unknown_tool:{name}"}
