"""
Tool definitions + implementations for the FLEETI GPT-5 agentic orchestrator.

Each tool is a thin wrapper over an already-existing, well-tested backend module:
  - search_fleet_schema -> FleetDbSummarizer.RAGPipeline
  - run_fleet_query     -> FleetiQueryRunner.LlmMongoRunner.run_payload (object path)
  - run_report          -> FleetiCommon.process_report_request (mongo_handler + APIHandler)

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
    pipeline: Any  # shared RAGPipeline instance

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
_RUN_FLEET_QUERY_DESCRIPTION = """Execute a READ-ONLY MongoDB query against the fleet database and return matching rows.
Call `search_fleet_schema` first to learn exact collection/field paths. Pass the query as a
parsed object (it is executed as-is — do NOT wrap it in markdown or db.collection.aggregate(...)).

STARTING COLLECTION:
- Vehicle/plate questions -> start from "Asset".
- Driving-behavior events (Idling, Harsh Acceleration/Braking/Cornering, Sharp Turn, Sudden Stop,
  Over Speeding, Zigzag Driving, Frequent Start/Stop, Long Continuous Driving, Driving Without GPS
  Lock, low-battery driving) -> "Events".
- Other alerts and geofence alert logs -> "AlertHistory".
- "latest/current" telemetry (location/speed/ignition) -> "AvlRecordLatest"; historical telemetry
  (at a past time) -> "AvlRecord".
- Daily aggregates -> "DailyAnalytics"; trips -> "Trip".

IDENTIFIER RULES:
- Plate number -> details.plate_number, matched case-insensitively & exactly:
  {"details.plate_number": {"$regex": "^123 ABC$", "$options": "i"}}. Never match on _id/asset_id.
- Geofence -> Geofence.name; AlertRule -> AlertRule.name; driver name ->
  Driver.profile.first_name + last_name. Match all string identifiers with ^...$ case-insensitive regex.
- Driver-of-vehicle: query the Driver collection's asset_assignments (take the latest assignment).

DATES:
- Emit ALL dates as Extended JSON: {"$date": "2025-11-01T00:00:00Z"} (NOT ISODate(...), NOT a bare
  string). Use the current UTC datetime from the system prompt to resolve relative dates.
- "latest/last/recent/current" -> $sort by the time field descending + $limit 1. "oldest/first" ->
  ascending + $limit 1. Exact time -> match a +/-5 minute window and pick the closest record.
- Only add $sort/$limit when the user implies ordering or a single/top-N result; never for "all".

JOINS ($lookup) — only to reach fields in a DIFFERENT collection; never join a collection to itself:
- Asset->Trip: localField "_id", foreignField "driver_info.asset_id"
- Asset->AvlRecord/AvlRecordLatest: "_id" -> "device_context.asset_id"
- Asset->Events: "_id" -> "device_context.asset_id"
- Asset->AlertHistory: "_id" -> "device_context.asset_id"
- AlertHistory->AlertRule: "alert_info.alert_rule_id" -> "_id"
- AlertHistory->Geofence: "alert_info.geofence_id" -> "_id"
- Asset->Device: "imei" -> "imei"; AvlRecord->Device: "device_id" -> "device_id"
- DailyAnalytics->Asset: "asset_id" -> "_id"; DailyAnalytics->Driver: "driver_id" -> "_id"

TENANT ISOLATION (handled server-side — do NOT add sub_tenant_id yourself):
- The server injects sub_tenant_id into the starting $match automatically for tenant-scoped
  collections. For a starting collection WITHOUT its own sub_tenant_id (e.g. AlertHistory, Trip,
  DailyAnalytics), you MUST include a $lookup into a tenant-aware collection (Asset, AlertRule,
  Driver, Device, Geofence, Events, AvlRecord) so the server can scope via that join.

PROJECTION:
- Always exclude _id ("_id": 0) and never project any *_id field. Use full paths, e.g.
  {"$project": {"_id": 0, "plate_number": "$details.plate_number", "speed": "$latest.speed"}}.

Distances are stored in METERS; return them raw (the assistant converts units when answering)."""

TOOL_DEFINITIONS: List[Dict[str, Any]] = [
    {
        "type": "function",
        "name": "search_fleet_schema",
        "description": (
            "Retrieve the relevant MongoDB collection schemas for a fleet DATA question. "
            "Call this BEFORE run_fleet_query to learn the exact field names and paths to use."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": (
                        "Natural-language description of the data needed (entities + fields), e.g. "
                        "'latest GPS location and speed for a vehicle by plate number'."
                    ),
                }
            },
            "required": ["query"],
            "additionalProperties": False,
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
def _tool_search_fleet_schema(args: Dict[str, Any], ctx: ToolContext) -> Dict[str, Any]:
    query = (args.get("query") or "").strip()
    if not query:
        return {"error": "missing_query"}

    rag_result = ctx.pipeline.query(query, use_llm=True)
    collection_json = rag_result.get("collection_json", {}) or {}
    collection_data = collection_json.get("collection_data", {}) or {}

    schemas = "\n\n".join(
        info.get("schema", "")
        for info in collection_data.values()
        if isinstance(info, dict)
    ).strip()

    selected: List[str] = []
    for _parent, data in collection_data.items():
        if isinstance(data, dict):
            selected.extend(data.get("selected_sub_collections", []) or [])
    if selected:
        ctx.selected_collections = selected

    return {
        "schemas": schemas or "(no schema matched; use your knowledge of the collections)",
        "collections": selected,
    }


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
    if name == "search_fleet_schema":
        return _tool_search_fleet_schema(args, ctx)
    if name == "run_fleet_query":
        return _tool_run_fleet_query(args, ctx)
    if name == "run_report":
        return await _tool_run_report(args, ctx)
    return {"error": f"unknown_tool:{name}"}
