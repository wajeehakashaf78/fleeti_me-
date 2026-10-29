"""
Tool definitions + implementations for the FLEETI GPT-5 agentic orchestrator.

Each tool is a thin wrapper over an already-existing, well-tested backend module:
  - get_query_context -> FleetiAgent.schema_service (deterministic catalog, no ML/RAG)
  - run_fleet_query   -> FleetiQueryRunner.LlmMongoRunner.run_payload (object path)
  - run_report        -> FleetiCommon.process_report_request (mongo_handler + APIHandler)

Tenant isolation, timezone localization, and result capping happen here / inside the
runner, on parsed objects — never via string repair.
"""

import os
import re
import math
import time
import uuid
import json
import logging
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from openpyxl import Workbook

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
from FleetiAgent.context_memory import MEMORY
from FleetiAgent.prompts import SUPPORTED_REPORT_TYPES, canonicalize_report_type

logger = logging.getLogger(__name__)

# When a fleet query matches more than this many rows, the orchestrator gets only
# headers + count (not the rows). It then aggregates or exports the full set.
ROW_PREVIEW_THRESHOLD = 25

EXPORTS_DIR = Path(os.getenv("FLEETI_EXPORTS_DIR") or (Path(__file__).resolve().parent.parent / "exports"))
EXPORT_TTL_HOURS = float(os.getenv("EXPORT_FILE_TTL_HOURS", "4"))
# Mirror of the runner's defensive ceiling (FleetiQueryRunner.execute._MAX_QUERY_ROWS) so we can
# tell the model when a result was truncated at the cap.
MAX_QUERY_ROWS = int(os.getenv("FLEETI_MAX_QUERY_ROWS", "100000"))


# ================================
# Result helpers (columns, field access, exports)
# ================================
def _columns_of(rows: List[Dict[str, Any]]) -> List[str]:
    """Ordered union of top-level keys across result rows."""
    cols: List[str] = []
    seen = set()
    for r in rows:
        if isinstance(r, dict):
            for k in r.keys():
                if k not in seen:
                    seen.add(k)
                    cols.append(k)
    return cols


def _get_field(row: Any, path: str) -> Any:
    """Read a (possibly dotted) field path from a row dict."""
    cur = row
    for part in str(path).split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return None
    return cur


def _to_number(v: Any) -> Optional[float]:
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        try:
            return float(v.strip())
        except ValueError:
            return None
    return None


def _hashable(v: Any) -> Any:
    return v if isinstance(v, (str, int, float, bool, type(None))) else json.dumps(v, default=str, sort_keys=True)


def _is_id_column(name: str) -> bool:
    n = str(name).lower().strip()
    return n in ("_id", "id") or n.endswith("_id") or n.endswith(".id") or "._id" in n


def _display_columns(rows: List[Dict[str, Any]], requested: Optional[List[str]]) -> List[str]:
    if requested:
        cols = [c for c in requested if not _is_id_column(c)]
    else:
        cols = [c for c in _columns_of(rows) if not _is_id_column(c)]
    return cols or _columns_of(rows)


def _sanitize_filename(s: str) -> str:
    s = re.sub(r"[^A-Za-z0-9 _-]", "", s or "").strip().replace(" ", "_")
    return s or "export"


def _safe_sheet_title(t: str) -> str:
    t = re.sub(r"[\[\]:*?/\\]", "", t or "")[:31].strip()
    return t or "Results"


def _pretty_header(c: str) -> str:
    return re.sub(r"[._]+", " ", str(c)).strip().title() or str(c)


def _xlsx_cell(v: Any) -> Any:
    if v is None or isinstance(v, (str, int, float, bool)):
        return v
    if isinstance(v, datetime):
        return v.isoformat()
    try:
        return json.dumps(v, default=str)
    except Exception:
        return str(v)


def _download_url(filename: str) -> str:
    base = (os.getenv("PUBLIC_DOWNLOAD_BASE_URL") or "").rstrip("/")
    return f"{base}/downloads/{filename}" if base else f"/downloads/{filename}"


def sweep_old_exports() -> int:
    """Delete export files older than EXPORT_TTL_HOURS. Returns the count removed."""
    removed = 0
    try:
        cutoff = time.time() - EXPORT_TTL_HOURS * 3600
        for p in EXPORTS_DIR.glob("*.xlsx"):
            try:
                if p.stat().st_mtime < cutoff:
                    p.unlink()
                    removed += 1
            except OSError:
                pass
        if removed:
            logger.info("🧹 export cleanup | removed %d expired file(s) (> %.1fh old)", removed, EXPORT_TTL_HOURS)
    except Exception:
        pass
    return removed


def _write_xlsx(rows: List[Dict[str, Any]], cols: List[str], path: Path, sheet_title: str) -> None:
    wb = Workbook(write_only=True)  # streaming writer — memory-safe for large exports
    ws = wb.create_sheet(title=_safe_sheet_title(sheet_title))
    ws.append([_pretty_header(c) for c in cols])
    for r in rows:
        ws.append([_xlsx_cell(_get_field(r, c)) for c in cols])
    wb.save(str(path))


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
    user_question: str = ""
    conversation_id: str = ""  # OpenAI conversation; keys the "already given" context memory
    turn_index: int = 0        # turn number within that conversation

    # captured side-effects (read by the endpoint after the run)
    used_fleet_query: bool = False
    last_fleet_query: str = ""
    last_fleet_rows: List[Dict[str, Any]] = field(default_factory=list)
    selected_collections: List[str] = field(default_factory=list)
    report_payload: Optional[Dict[str, Any]] = None
    report_has_data: bool = False
    export_url: Optional[str] = None


# ================================
# Tool JSON-schema definitions (Responses API "function" tools)
# ================================
_RUN_FLEET_QUERY_DESCRIPTION = (
    "Execute a READ-ONLY MongoDB query and return matching rows. Call get_query_context FIRST "
    "to fetch the exact field paths, join hints, and examples for the collections you need. "
    "Pass the query as a parsed object — it is executed as-is, so do NOT wrap it in markdown or "
    "in db.collection.aggregate(...).\n\n"
    "LARGE RESULTS: the result is NOT row-capped (the full set is fetched). If it has MORE THAN 25 "
    "rows you receive ONLY the column headers + total count (not the rows). Then either (a) call "
    "aggregate_results to compute a value over ALL rows (average/total/count/max/min/top-N/group-by), "
    "or (b) call export_results to give the user a downloadable Excel of the full list. Never ask for "
    "or expect the raw rows once the count exceeds 25. Prefer doing aggregation in Mongo ($group/$count) "
    "so the result is already small when you only need a computed value.\n\n" + RULES
)

TOOL_DEFINITIONS: List[Dict[str, Any]] = [
    {
        "type": "function",
        "name": "get_query_context",
        "description": (
            "Fetch the exact schema fields, join hints, and 2-3 relevant query examples for the "
            "fleet collections/sections you need — call this BEFORE run_fleet_query. Request "
            "sections by name, or a top-level collection name. Within one conversation, fields, "
            "joins and examples you already received are not repeated (marked 'given earlier') — "
            "reuse them from the earlier result; pass refresh: true only if you no longer have "
            "them. Use this menu to choose:\n\n"
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
                "refresh": {
                    "type": "boolean",
                    "description": "true = resend everything, including items already given earlier in this conversation.",
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
                    "description": "Starting collection name (e.g. Asset, AvlRecordLatest, Trip, Driver, AlertHistory).",
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
            },
            "required": ["collection", "operation"],
        },
    },
    {
        "type": "function",
        "name": "aggregate_results",
        "description": (
            "Compute aggregate values over the FULL result set of the most recent run_fleet_query. "
            "Use this when that query returned >25 rows and the user wants a DERIVED value (average, "
            "total, count, min/max, median, top-N, or a group-by breakdown) rather than the list "
            "itself. Returns small computed results — never the raw rows. If the result can't answer "
            "the user's question, call export_results instead."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "operations": {
                    "type": "array",
                    "description": "One or more aggregations to compute.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "op": {
                                "type": "string",
                                "enum": ["count", "count_distinct", "distinct_values", "sum", "avg",
                                         "min", "max", "median", "stddev", "range", "first", "last",
                                         "top_n", "bottom_n"],
                                "description": "Aggregation to apply.",
                            },
                            "field": {
                                "type": "string",
                                "description": "Field/column to apply the op on (dotted path ok). Omit for count.",
                            },
                            "group_by": {
                                "type": "string",
                                "description": "Optional field to group by; the op is computed per group.",
                            },
                            "n": {
                                "type": "integer",
                                "description": "For top_n/bottom_n: how many rows (max 25).",
                            },
                            "columns": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "For top_n/bottom_n: user-facing columns to include.",
                            },
                        },
                        "required": ["op"],
                    },
                },
            },
            "required": ["operations"],
        },
    },
    {
        "type": "function",
        "name": "export_results",
        "description": (
            "Export the FULL result set of the most recent run_fleet_query to a downloadable Excel "
            "(.xlsx) file. Use this when the user wants a large LIST (e.g. 'all active vehicles'), or "
            "when aggregate_results can't answer the question. It exports the MOST RECENT "
            "run_fleet_query result EXACTLY as returned — so for a DETAILED list make sure that query "
            "returned RAW records (one row per item, NOT a $group summary) with the columns the user "
            "wants, joining for human-readable names (e.g. the vehicle plate). Choose only user-facing "
            "display columns (e.g. plate_number, status, last_reported) — internal id columns are "
            "dropped automatically. The download link is returned to the user automatically; in your "
            "reply just tell them the file is ready."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "columns": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "User-facing columns to include in the file (never internal ids).",
                },
                "title": {
                    "type": "string",
                    "description": "Short title for the file/sheet, e.g. 'Active vehicles'.",
                },
            },
            "required": ["columns"],
        },
    },
    {
        "type": "function",
        "name": "run_report",
        "description": (
            "Generate one of the supported fleet reports. Only call this once all required "
            "prerequisites for the chosen report type are known (ask the user otherwise). "
            "Provide resolved dates; do not invent a date range. Pass dates/times in the USER'S "
            "LOCAL timezone — the server converts them to UTC (never convert times yourself).\n\n"
            "DutyHour only: optionally set duty_type ('on' default, or 'off') and a duty time "
            "window via duty_start_time/duty_end_time (24h HH:MM, default 10:00 and 19:00). Only "
            "set these when the user states them; the server applies the defaults, the off-duty "
            "swap, and the UTC conversion."
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
                "duty_type": {
                    "type": "string",
                    "enum": ["on", "off"],
                    "description": "DutyHour only: 'on' (default) or 'off' duty. Set 'off' only if the user asks for off-duty.",
                },
                "duty_start_time": {
                    "type": "string",
                    "description": "DutyHour only: duty window start time in 24h HH:MM (default 10:00). Set only if the user states it.",
                },
                "duty_end_time": {
                    "type": "string",
                    "description": "DutyHour only: duty window end time in 24h HH:MM (default 19:00). Set only if the user states it.",
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
    memory = MEMORY.view(ctx.conversation_id, ctx.turn_index, refresh=bool(args.get("refresh")))
    return get_query_context(sections, intent, question=ctx.user_question, memory=memory)


def _tool_run_fleet_query(args: Dict[str, Any], ctx: ToolContext) -> Dict[str, Any]:
    collection = (args.get("collection") or "").strip()
    if not collection:
        return {"error": "missing_collection"}

    operation = (args.get("operation") or "aggregate").strip().lower()
    if operation == "find":
        flt = args.get("filter") or {}
        projection = args.get("projection")
        payload: Any = {"filter": flt, "projection": projection} if projection else flt
    else:
        operation = "aggregate"
        payload = args.get("pipeline") or []

    runner = LlmMongoRunner(mongo_db=ctx.mongo_db)
    try:
        rows = runner.run_payload(  # full result set (no row cap)
            collection,
            operation,
            payload,
            user_time_zone=ctx.time_zone,
            sub_tenant_id=None if ctx.remove_sub_tenant_match else ctx.sub_tenant_id,
            remove_sub_tenant_match=ctx.remove_sub_tenant_match,
        )
    except Exception as exc:  # surface a compact error so the model can respond gracefully
        logger.debug("[run_fleet_query] failed: %s", exc)
        return {"error": "query_failed", "detail": str(exc)[:300]}

    localized = convert_query_response_times_for_user(rows, ctx.time_zone)
    ctx.used_fleet_query = True
    ctx.last_fleet_query = runner.last_executed_query or ""
    ctx.last_fleet_rows = localized  # full set kept server-side for aggregate/export

    n = len(localized)
    truncated = n >= MAX_QUERY_ROWS
    if n > ROW_PREVIEW_THRESHOLD:
        cols = _columns_of(localized)
        logger.info(
            "📦 run_fleet_query | %s.%s | %d rows (> %d)%s → returning headers+count only | columns=%s",
            collection, operation, n, ROW_PREVIEW_THRESHOLD,
            " [TRUNCATED at cap]" if truncated else "", cols,
        )
        note = (
            f"{n} rows matched (more than {ROW_PREVIEW_THRESHOLD}), so the rows are NOT included "
            "to protect context/cost. Call aggregate_results to compute a value over ALL rows, "
            "or export_results to give the user a downloadable Excel of the full list. "
            "Do not request the raw rows."
        )
        result: Dict[str, Any] = {"row_count": n, "columns": cols, "rows_omitted": True, "note": note}
        if truncated:
            result["truncated"] = True
            result["note"] += (
                f" IMPORTANT: the result was CAPPED at {MAX_QUERY_ROWS} rows — there are likely more "
                "matching records. Tell the user the answer/export covers only the first "
                f"{MAX_QUERY_ROWS}, and suggest narrowing the date range or filters for the full set."
            )
        return result
    logger.info("📦 run_fleet_query | %s.%s | %d rows returned", collection, operation, n)
    return {"row_count": n, "rows": localized}


def _summarize_agg(res: Dict[str, Any]) -> str:
    if "error" in res:
        return f"error: {res['error']}"
    if "value" in res:
        return str(res["value"])[:160]
    if "groups" in res:
        return f"{len(res['groups'])} group(s)"
    if "rows" in res:
        return f"{len(res['rows'])} row(s)"
    return "(no value)"


def _scalar_op(op: str, rows: List[Dict[str, Any]], field_name: Optional[str]) -> Any:
    """Reduce a list of rows to a single value for the given op/field."""
    if op == "count":
        return len(rows)
    if op == "count_distinct":
        return len({_hashable(_get_field(r, field_name)) for r in rows if _get_field(r, field_name) is not None})
    if op == "distinct_values":
        out, seen = [], set()
        for r in rows:
            v = _get_field(r, field_name)
            if v is None:
                continue
            h = _hashable(v)
            if h not in seen:
                seen.add(h)
                out.append(v)
            if len(out) >= 100:
                break
        return out
    if op in ("first", "last"):
        seq = rows if op == "first" else list(reversed(rows))
        for r in seq:
            v = _get_field(r, field_name)
            if v is not None:
                return v
        return None

    nums = [v for v in (_to_number(_get_field(r, field_name)) for r in rows) if v is not None]
    if not nums:
        return None
    if op == "sum":
        return round(sum(nums), 4)
    if op == "avg":
        return round(sum(nums) / len(nums), 4)
    if op == "min":
        return min(nums)
    if op == "max":
        return max(nums)
    if op == "range":
        return round(max(nums) - min(nums), 4)
    if op == "median":
        s = sorted(nums)
        m = len(s)
        return s[m // 2] if m % 2 else round((s[m // 2 - 1] + s[m // 2]) / 2, 4)
    if op == "stddev":
        mean = sum(nums) / len(nums)
        return round(math.sqrt(sum((x - mean) ** 2 for x in nums) / len(nums)), 4)
    raise ValueError(f"unknown op: {op}")


def _compute_operation(spec: Dict[str, Any], rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    op = (spec.get("op") or "").strip().lower()
    field_name = spec.get("field")
    group_by = spec.get("group_by")
    res: Dict[str, Any] = {"op": op}
    if field_name:
        res["field"] = field_name

    try:
        if op in ("top_n", "bottom_n"):
            nn = max(1, min(int(spec.get("n") or 10), 25))
            valued = [(r, _to_number(_get_field(r, field_name))) for r in rows]
            valued = [(r, v) for r, v in valued if v is not None]
            valued.sort(key=lambda rv: rv[1], reverse=(op == "top_n"))
            cols = _display_columns(rows, spec.get("columns"))
            res["rows"] = [
                {**{c: _get_field(r, c) for c in cols}, field_name: v} for r, v in valued[:nn]
            ]
            return res

        if group_by:
            res["group_by"] = group_by
            groups: Dict[Any, List[Dict[str, Any]]] = {}
            for r in rows:
                groups.setdefault(_hashable(_get_field(r, group_by)), []).append(r)
            computed = {str(k): _scalar_op(op, grp, field_name) for k, grp in groups.items()}
            if len(computed) > 50:
                items = sorted(
                    computed.items(),
                    key=lambda kv: kv[1] if isinstance(kv[1], (int, float)) else float("-inf"),
                    reverse=True,
                )[:50]
                res.update({"groups": dict(items), "total_groups": len(computed), "groups_truncated_to": 50})
            else:
                res["groups"] = computed
            return res

        res["value"] = _scalar_op(op, rows, field_name)
        return res
    except Exception as exc:  # noqa: BLE001
        res["error"] = str(exc)[:200]
        return res


def _tool_aggregate_results(args: Dict[str, Any], ctx: ToolContext) -> Dict[str, Any]:
    rows = ctx.last_fleet_rows or []
    if not rows:
        logger.info("🧮 aggregate_results | no result set (run_fleet_query first)")
        return {"error": "no_result_set", "note": "Run run_fleet_query first; aggregate_results runs over its full result."}
    operations = args.get("operations") or []
    if isinstance(operations, dict):
        operations = [operations]
    if not operations:
        logger.info("🧮 aggregate_results | no operations provided")
        return {"error": "no_operations"}

    logger.info("🧮 aggregate_results | rows=%d | %d operation(s)", len(rows), len(operations))
    results: List[Dict[str, Any]] = []
    for spec in operations:
        res = _compute_operation(spec, rows)
        logger.info(
            "🧮   op=%s field=%s group_by=%s n=%s → %s",
            res.get("op"), res.get("field"), spec.get("group_by"), spec.get("n"), _summarize_agg(res),
        )
        results.append(res)
    logger.info("🧮 aggregate_results done | %d result(s)", len(results))
    return {"row_count": len(rows), "results": results}


def _tool_export_results(args: Dict[str, Any], ctx: ToolContext) -> Dict[str, Any]:
    rows = ctx.last_fleet_rows or []
    if not rows:
        logger.info("📄 export_results | no result set (run_fleet_query first)")
        return {"error": "no_result_set", "note": "Run run_fleet_query first; export_results exports its full result."}

    cols = _display_columns(rows, args.get("columns"))
    if not cols:
        logger.info("📄 export_results | no displayable columns")
        return {"error": "no_displayable_columns"}

    title = (args.get("title") or ctx.user_question or "fleet_export").strip()
    logger.info("📄 export_results | rows=%d | requested_columns=%s | title=%r", len(rows), args.get("columns"), title)
    logger.info("📄   display columns (ids stripped): %s", cols)
    try:
        EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
        sweep_old_exports()
        fname = f"{_sanitize_filename(title)[:60]}__{datetime.now().strftime('%Y%m%d-%H%M%S')}__{uuid.uuid4().hex[:8]}.xlsx"
        path = EXPORTS_DIR / fname
        _write_xlsx(rows, cols, path, sheet_title=title)
        size = path.stat().st_size
    except Exception as exc:  # noqa: BLE001
        logger.warning("📄 export_results FAILED: %s", exc)
        return {"error": "export_failed", "detail": str(exc)[:200]}

    ctx.export_url = _download_url(fname)
    logger.info("📄 export_results done | file=%s (%d bytes, %d rows) | url=%s", fname, size, len(rows), ctx.export_url)
    return {
        "status": "exported",
        "row_count": len(rows),
        "columns": cols,
        "note": "Excel file generated. The download link is delivered to the user automatically — just tell them the file is ready.",
    }


async def _tool_run_report(args: Dict[str, Any], ctx: ToolContext) -> Dict[str, Any]:
    raw_report_type = (args.get("report_type") or "").strip()
    if not raw_report_type:
        return {"error": "missing_report_type"}

    # Enforce that the report type is one of the SUPPORTED REPORTS (prompts.py). Normalize
    # casing/spacing/synonyms to the canonical token so the final response's report_type
    # field always exactly matches the supported list. Unknown types are rejected (this also
    # hard-blocks any report removed from the list).
    report_type = canonicalize_report_type(raw_report_type)
    if not report_type:
        logger.info("🧾 run_report | rejected unsupported report_type=%r", raw_report_type)
        return {
            "error": "unsupported_report_type",
            "detail": f"'{raw_report_type}' is not a supported report.",
            "supported_report_types": list(SUPPORTED_REPORT_TYPES),
        }

    pre_req = PreRequisites(
        asset_plate_numbers=args.get("asset_plate_numbers"),
        group_names=args.get("group_names"),
        driver_names=args.get("driver_names"),
        date_range=args.get("date_range"),
        geofence_names=args.get("geofence_names"),
        duty_type=args.get("duty_type"),
        duty_start_time=args.get("duty_start_time"),
        duty_end_time=args.get("duty_end_time"),
    )
    # FleetSummary never takes a date range.
    if report_type == "FleetSummary":
        pre_req.date_range = None

    logger.info(
        "🧾 run_report | type=%s | plates=%s groups=%s drivers=%s geofences=%s date_range=%s%s",
        report_type, pre_req.asset_plate_numbers, pre_req.group_names,
        pre_req.driver_names, pre_req.geofence_names, pre_req.date_range,
        (f" duty_type={pre_req.duty_type or 'on'} window={pre_req.duty_start_time or '10:00'}-{pre_req.duty_end_time or '19:00'}"
         if report_type == "DutyHour" else ""),
    )

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

    # Log id-resolution + the resolved UTC window + the final outcome.
    mq = mongodb_query_result or {}
    resolved = {}
    if "asset_ids" in mq:
        resolved["asset_ids"] = len(mq.get("asset_ids") or [])
    if "driver_ids" in mq:
        resolved["driver_ids"] = len(mq.get("driver_ids") or [])
    logger.info(
        "🧾 run_report | type=%s | resolved=%s | window=%s..%s | outcome=%s",
        report_type, resolved or "n/a",
        result.get("start_datetime"), result.get("end_datetime"), status,
    )

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
    if name == "aggregate_results":
        return _tool_aggregate_results(args, ctx)
    if name == "export_results":
        return _tool_export_results(args, ctx)
    if name == "run_report":
        return await _tool_run_report(args, ctx)
    return {"error": f"unknown_tool:{name}"}
