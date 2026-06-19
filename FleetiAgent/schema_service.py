"""
Deterministic schema + query-context service for the FLEETI GPT-5 agent.

Replaces the embedding/BM25/cross-encoder + routing-LLM RAG stack for the /chat/v2
path. The DB is only ~12 logical collections, so instead of semantic retrieval we:
  - expose a compact always-on MENU (collections, sections, disambiguations) in the
    get_query_context tool description, and
  - return only the pruned fields the model asks for (+ relevant joins + 2-3 relevant
    examples) on demand.

Field text comes from the schema .txt files (source of truth) via load_collection_schemas;
join rules reuse generate_relationship_rules. No ML, no extra LLM call.
"""

import re
import logging
from typing import Any, Dict, List, Optional, Tuple

from FleetDbSummarizer.config import COLLECTION_SCHEMAS_DIR
from FleetDbSummarizer.utils import load_collection_schemas, generate_relationship_rules

logger = logging.getLogger(__name__)


# ================================
# Section fields, loaded once from the .txt files
# ================================
def _load_sections() -> Tuple[Dict[str, str], Dict[str, str]]:
    """
    Returns:
      section_fields: {section_name: "- field: type" lines joined}
      section_parent: {section_name: top_level_collection}
    """
    raw = load_collection_schemas(COLLECTION_SCHEMAS_DIR)  # {parent: {section: schema_text}}
    section_fields: Dict[str, str] = {}
    section_parent: Dict[str, str] = {}
    for parent, sections in raw.items():
        for section, schema_text in sections.items():
            field_lines = [
                ln.strip()
                for ln in schema_text.splitlines()
                if ln.strip().startswith("- ")
            ]
            section_fields[section] = "\n".join(field_lines)
            section_parent[section] = parent
    return section_fields, section_parent


_SECTION_FIELDS, _SECTION_PARENT = _load_sections()


def _norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


# Lookup of normalized section name -> canonical section name.
_NORM_SECTION = {_norm(s): s for s in _SECTION_FIELDS}
# Normalized top-level collection -> canonical collection.
_NORM_COLLECTION = {_norm(p): p for p in set(_SECTION_PARENT.values())}
_COLLECTION_SECTIONS: Dict[str, List[str]] = {}
for _sec, _par in _SECTION_PARENT.items():
    _COLLECTION_SECTIONS.setdefault(_par, []).append(_sec)
for _par in _COLLECTION_SECTIONS:
    _COLLECTION_SECTIONS[_par].sort(key=lambda x: (not x.endswith("_base"), x))

# When a top-level collection is requested by name, return these default section(s).
_DEFAULT_SECTIONS: Dict[str, List[str]] = {
    "Asset": ["asset_base", "asset_details_base"],
    "Driver": ["Driver_base", "Driver_Profile"],
    "AvlRecord": ["AvlRecord_base"],
    "Trip": ["Trip_base"],
    "AlertRule": ["AlertRule_base"],
    "AlertHistory": ["AlertHistory_base"],
    "Events": ["Events_base"],
    "Geofence": ["Geofence_base"],
    "Device": ["Device_base"],
    "DailyAnalytics": ["DailyAnalytics_base"],
    "SystemAlertRule": ["SystemAlertRule_base"],
}


# ================================
# Curated catalog -> always-on MENU
# ================================
# One compact line of purpose per section for the most-used sections; the rest are
# listed by name (the names are self-descriptive). Disambiguations are the high-value part.
CATALOG: List[Dict[str, Any]] = [
    {
        "collection": "Asset",
        "purpose": "Vehicles/assets: identity, specs, documents/expiry, device link.",
        "ids": "_id (asset id); details.plate_number; device_details.imei",
        "section_notes": {
            "asset_base": "status, availability, created_at, expiry_date",
            "asset_details_base": "plate_number, plate_type, vehicle_type, fleet_type, make, model, VIN, fuel_type, odometer",
            "asset_details_document_status_flags": "insurance/istimara/mvpi/operation-card/barrier-cert expiry & status",
            "asset_device_details": "device_details.imei, group_id, group_name (link to Device)",
        },
    },
    {
        "collection": "AvlRecord",
        "purpose": "Telemetry/GPS: location, speed, ignition, movement, sensors, odometer, voltage.",
        "ids": "imei; device_context.asset_id (->Asset._id); device_context.driver_info.id (->Driver._id)",
        "section_notes": {
            "AvlRecord_base": "timestamp, location, speed, ignition_status, movement, gps_status, odometer",
            "AvlRecord_sensor": "fuel/temperature/humidity/weight & other sensor readings",
        },
    },
    {
        "collection": "Trip",
        "purpose": "Per-trip records: start/end, distance, duration, speeds, idling, harsh events, fuel, scores.",
        "ids": "driver_info.asset_id (->Asset._id); driver_info.driver_info.id (->Driver._id); imei",
        "section_notes": {
            "Trip_base": "start_at, end_at, distance_covered (meters), duration, avg/max speed, idle_time",
            "Trip_Analytics": "per-trip behavior/safety analytics",
        },
    },
    {
        "collection": "Driver",
        "purpose": "Drivers: profile, vehicle assignments, license/visa/medical, compliance, analytics.",
        "ids": "_id (driver id); profile.first_name + profile.last_name; asset_assignments[]._id (->Asset._id)",
        "section_notes": {
            "Driver_base": "core identity",
            "Driver_Profile": "full personal/professional profile",
            "Driver_analytics": "OVERALL/all-time driver KPIs (safety_score, behavior_score, avg_speed, total_trips/distance/hours, harsh-event counts) — use for 'overall'/all-time, do not recompute from Trip/DailyAnalytics",
            "Driver_behavior": "overall behavior scores (risk, compliance, fatigue)",
            "Driver_performance": "overall performance ratings (overall_rating, safety_score, efficiency)",
            "Driver_asset_assignments": "driver<->vehicle assignments (use latest for driver-of-vehicle)",
            "Driver_license": "license issue/expiry/status",
            "Driver_visa": "visa/work-permit",
            "Driver_medical": "medical certificate expiry/status",
            "Driver_wasl_logs": "WASL (Saudi) compliance logs",
        },
    },
    {
        "collection": "Events",
        "purpose": "Driving-behavior event logs AND SystemAlertRule trigger logs.",
        "ids": "device_context.asset_id (->Asset._id); device_context.driver_info.id (->Driver._id); event_type",
        "section_notes": {
            "Events_base": "event_type, timestamp, location, speed, duration, severity",
        },
    },
    {
        "collection": "AlertHistory",
        "purpose": "Logs for AlertRule triggers AND geofence events (no sub_tenant_id of its own).",
        "ids": "alert_info.alert_rule_id (->AlertRule._id); alert_info.geofence_id (->Geofence._id); device_context.asset_id",
        "section_notes": {
            "AlertHistory_base": "alert_info.alert_type ('geofence' vs 'alertRule'), name, severity, status, created_at, location",
        },
    },
    {
        "collection": "AlertRule",
        "purpose": "Alert rule definitions/config only (trigger logs live in AlertHistory).",
        "ids": "_id; name",
        "section_notes": {
            "AlertRule_base": "name, description, severity, enabled status",
            "AlertRule_condition": "thresholds & trigger criteria",
            "AlertRule_assigned_assets": "vehicles monitored by the rule",
        },
    },
    {
        "collection": "Geofence",
        "purpose": "Geofence definitions/config only (geofence events live in AlertHistory).",
        "ids": "_id; name; asset_assignments[].asset_id (->Asset._id)",
        "section_notes": {
            "Geofence_base": "name, boundary/config",
            "Geofence_asset_assignment": "assets assigned to the geofence",
        },
    },
    {
        "collection": "Device",
        "purpose": "Tracking device/hardware metadata.",
        "ids": "imei (->Asset.details.device_details.imei); device_id (->AvlRecord.device_id)",
        "section_notes": {"Device_base": "imei, serial, model, manufacturer, SIM, install/warranty"},
    },
    {
        "collection": "DailyAnalytics",
        "purpose": "Per-day aggregates per asset/driver: distance, duration, idle, over-speeding, fuel, scores.",
        "ids": "asset_id (->Asset._id); driver_id (->Driver._id); timestamp (the day)",
        "section_notes": {"DailyAnalytics_base": "daily distance (meters), duration, idle, over_speeding, scores"},
    },
    {
        "collection": "SystemAlertRule",
        "purpose": "System-level alert rule definitions only (trigger logs live in Events).",
        "ids": "event_type (->Events.event_type)",
        "section_notes": {"SystemAlertRule_base": "predefined system alert rules"},
    },
]

_DISAMBIGUATIONS = """DISAMBIGUATIONS:
- Latest/current telemetry (location/speed/ignition/movement) -> AvlRecordLatest (one latest doc per asset). Historical/at-a-past-time telemetry -> AvlRecord. (Both share the AvlRecord schema.)
- Driving-behavior events (Idling, Harsh Acceleration/Braking/Cornering, Sharp Turn, Sudden Stop, Over Speeding, Zigzag, Frequent Start/Stop, Long Continuous Driving, Driving Without GPS Lock, low-battery driving) -> Events. Events is also where SystemAlertRule trigger logs live.
- AlertRule trigger logs AND geofence event logs -> AlertHistory (alert_info.alert_type = 'geofence' vs 'alertRule'). AlertRule/Geofence/SystemAlertRule hold definitions only.
- Driver of a vehicle -> Driver.asset_assignments (use the latest assignment).
- Per-day aggregates -> DailyAnalytics; per-trip -> Trip."""


def build_menu() -> str:
    """Render the compact always-on collection menu (embedded in the tool description)."""
    lines: List[str] = ["COLLECTIONS (request sections via get_query_context):"]
    for entry in CATALOG:
        coll = entry["collection"]
        lines.append(f"\n{coll} — {entry['purpose']}")
        lines.append(f"  ids: {entry['ids']}")
        notes = entry.get("section_notes", {})
        sec_parts = []
        for sec in _COLLECTION_SECTIONS.get(coll, []):
            note = notes.get(sec)
            sec_parts.append(f"{sec} ({note})" if note else sec)
        if sec_parts:
            lines.append("  sections: " + " | ".join(sec_parts))
    lines.append("\n" + _DISAMBIGUATIONS)
    return "\n".join(lines)


# ================================
# Invariant query RULES (deduped from prompt_blueprint.py)
# ================================
RULES = """QUERY RULES:
- Plate numbers: match details.plate_number with case-insensitive exact regex {"$regex":"^<plate>$","$options":"i"}; never match _id/asset_id. Match other string identifiers (geofence/alert/rule names) the same ^...$ /i way. For Events.event_type use a flexible regex, e.g. {"$regex":"harsh[-_\\\\s]*braking|harshbraking","$options":"i"}.
- Dates: emit ALL dates as Extended JSON {"$date":"YYYY-MM-DDTHH:MM:SSZ"} — never ISODate(...) or a bare string. Resolve relative dates against the current UTC datetime from the system prompt.
- Time intent: latest/last/current -> $sort the time field desc + $limit 1; oldest/first -> asc + $limit 1; an exact time -> match a +/-5 minute window and pick the closest record. Add $sort/$limit only when ordering or a single/top-N result is implied; never for "all".
- Joins: $lookup only to reach fields in a DIFFERENT collection; never join a collection to itself. Use the localField/foreignField from the get_query_context "joins" output.
- Projection: always exclude _id ("_id":0) and never project any *_id field; use full paths, e.g. {"plate_number":"$details.plate_number"}.
- Tenant: do NOT add sub_tenant_id yourself — the server injects it. If the starting collection has no sub_tenant_id of its own (AlertHistory, Trip, DailyAnalytics), include a $lookup into a tenant-aware collection (Asset, AvlRecord, Driver, Device, Events, Geofence, AlertRule) so the server can scope via the join.
- Active vehicles only: every Asset access (any vehicle/plate question) is automatically restricted server-side to ACTIVE vehicles (device_availability "AssignedToDevice", status "Active", expiry_date in the future/missing/null). Treat "vehicles" as active vehicles; do NOT add these conditions yourself.
- Data-source preference (choose silently; never ask the user which source to use):
  1. OVERALL / all-time entity KPIs come from the entity's OWN collection. For a driver's overall scores/metrics (safety score, behavior score, performance rating, all-time average speed, total trips/distance/hours, harsh-event counts) read directly from Driver.driver_analytics / Driver.analytics / Driver.behavior / Driver.performance — do NOT recompute them from Trip or DailyAnalytics.
  2. For a SPECIFIC TIME RANGE (today, yesterday, last 7 days, a date range) aggregate from Trip (per-trip rows: avg_speed, max_speed, distance_covered, duration, idle_time, safety/behaviour scores) or DailyAnalytics (per-day rows), whichever fits the metric.
  3. For INSTANTANEOUS / raw values (current speed, a reading at a moment) use AvlRecord / AvlRecordLatest.
- Distances are stored in METERS; return them raw (the assistant converts units when answering)."""


# ================================
# Tagged example bank (ported from prompt_blueprint.py; dates as Extended JSON)
# ================================
EXAMPLES: List[Dict[str, Any]] = [
    {
        "tags": ["location", "telemetry", "historical", "asset", "time-exact"],
        "collections": ["Asset", "AvlRecord"],
        "question": "What was the location of plate 304 XYA at 4:35 PM on Oct 10, 2025?",
        "query": 'db.Asset.aggregate([{"$match":{"details.plate_number":{"$regex":"^304 XYA$","$options":"i"}}},{"$lookup":{"from":"AvlRecord","let":{"assetImei":"$device_details.imei","targetTime":{"$date":"2025-10-10T16:35:00Z"}},"pipeline":[{"$match":{"$expr":{"$eq":["$imei","$$assetImei"]}}},{"$addFields":{"time_diff":{"$abs":{"$subtract":["$timestamp","$$targetTime"]}}}},{"$sort":{"time_diff":1}},{"$limit":1},{"$project":{"_id":0,"location":1,"timestamp":1,"speed":1,"ignition_status":1}}],"as":"closest"}},{"$unwind":"$closest"},{"$project":{"_id":0,"plate_number":"$details.plate_number","location":"$closest.location","timestamp":"$closest.timestamp","speed":"$closest.speed"}}])',
    },
    {
        "tags": ["location", "telemetry", "latest", "current", "moving", "count"],
        "collections": ["Asset", "AvlRecord"],
        "question": "What is the latest location of plate 123 ABC?",
        "query": 'db.Asset.aggregate([{"$match":{"details.plate_number":{"$regex":"^123 ABC$","$options":"i"}}},{"$lookup":{"from":"AvlRecordLatest","localField":"_id","foreignField":"device_context.asset_id","as":"latest"}},{"$unwind":"$latest"},{"$project":{"_id":0,"plate_number":"$details.plate_number","location":"$latest.location","speed":"$latest.speed","ignition_status":"$latest.ignition_status","timestamp":"$latest.timestamp"}}])',
    },
    {
        "tags": ["trips", "asset", "distance"],
        "collections": ["Asset", "Trip"],
        "question": "Show all trips for plate 243.",
        "query": 'db.Asset.aggregate([{"$match":{"details.plate_number":{"$regex":"^243$","$options":"i"}}},{"$lookup":{"from":"Trip","localField":"_id","foreignField":"driver_info.asset_id","as":"trips"}},{"$unwind":"$trips"},{"$project":{"_id":0,"plate_number":"$details.plate_number","start_at":"$trips.start_at","end_at":"$trips.end_at","duration":"$trips.duration","distance_covered":"$trips.distance_covered","avg_speed":"$trips.avg_speed"}}])',
    },
    {
        "tags": ["asset", "details", "plate", "type"],
        "collections": ["Asset"],
        "question": "What is the plate type of plate 123 ABC?",
        "query": 'db.Asset.aggregate([{"$match":{"details.plate_number":{"$regex":"^123 ABC$","$options":"i"}}},{"$project":{"_id":0,"plate_number":"$details.plate_number","plate_type":"$details.plate_type"}}])',
    },
    {
        "tags": ["events", "idling", "asset", "time-range", "behavior"],
        "collections": ["Asset", "Events"],
        "question": "List Idling events for plate 123 ABC yesterday.",
        "query": 'db.Asset.aggregate([{"$match":{"details.plate_number":{"$regex":"^123 ABC$","$options":"i"}}},{"$lookup":{"from":"Events","localField":"_id","foreignField":"device_context.asset_id","as":"events"}},{"$unwind":"$events"},{"$match":{"events.event_type":{"$regex":"^idling$","$options":"i"},"events.timestamp":{"$gte":{"$date":"2026-01-01T00:00:00Z"},"$lte":{"$date":"2026-01-02T00:00:00Z"}}}},{"$project":{"_id":0,"plate_number":"$details.plate_number","event_type":"$events.event_type","timestamp":"$events.timestamp","location":"$events.location"}}])',
    },
    {
        "tags": ["events", "harshbraking", "behavior"],
        "collections": ["Events"],
        "question": "Show all harsh braking events.",
        "query": 'db.Events.aggregate([{"$match":{"event_type":{"$regex":"harsh[-_\\\\s]*braking|harshbraking","$options":"i"}}},{"$project":{"_id":0,"event_type":1,"timestamp":1,"location":1,"speed":1,"duration":1}}])',
    },
    {
        "tags": ["geofence", "asset", "assignment"],
        "collections": ["Geofence", "Asset"],
        "question": "Which vehicles are assigned to Geofence A?",
        "query": 'db.Geofence.aggregate([{"$match":{"name":{"$regex":"^Geofence A$","$options":"i"}}},{"$lookup":{"from":"Asset","localField":"asset_assignments.asset_id","foreignField":"_id","as":"asset"}},{"$unwind":"$asset"},{"$project":{"_id":0,"geofence":"$name","plate_number":"$asset.details.plate_number"}}])',
    },
    {
        "tags": ["geofence", "alerts", "alerthistory", "asset", "events"],
        "collections": ["Asset", "AlertHistory"],
        "question": "Show geofence alerts for plate 123 ABC.",
        "query": 'db.Asset.aggregate([{"$match":{"details.plate_number":{"$regex":"^123 ABC$","$options":"i"}}},{"$lookup":{"from":"AlertHistory","localField":"_id","foreignField":"device_context.asset_id","as":"alerts"}},{"$unwind":"$alerts"},{"$match":{"alerts.alert_info.alert_type":"geofence"}},{"$project":{"_id":0,"plate_number":"$details.plate_number","geofence_name":"$alerts.alert_info.name","timestamp":"$alerts.created_at","location":"$alerts.alert_info.location","status":"$alerts.alert_info.status"}}])',
    },
    {
        "tags": ["alerts", "alerthistory", "alertrule", "time-range"],
        "collections": ["AlertHistory", "AlertRule"],
        "question": "Get all alerts from 2025-10-01 to 2025-10-31.",
        "query": 'db.AlertHistory.aggregate([{"$lookup":{"from":"AlertRule","localField":"alert_info.alert_rule_id","foreignField":"_id","as":"alert_rule"}},{"$unwind":"$alert_rule"},{"$match":{"created_at":{"$gte":{"$date":"2025-10-01T00:00:00Z"},"$lte":{"$date":"2025-10-31T23:59:59Z"}}}},{"$project":{"_id":0,"alert_type":"$alert_info.alert_type","name":"$alert_info.name","severity":"$alert_info.severity","timestamp":"$created_at","status":"$alert_info.status"}}])',
    },
    {
        "tags": ["device", "asset", "imei"],
        "collections": ["Asset"],
        "question": "What device is installed on plate 123 ABC?",
        "query": 'db.Asset.aggregate([{"$match":{"details.plate_number":{"$regex":"^123 ABC$","$options":"i"}}},{"$project":{"_id":0,"plate_number":"$details.plate_number","imei":"$details.device_details.imei","device_name":"$details.device_details.device_name"}}])',
    },
    {
        "tags": ["dailyanalytics", "distance", "asset", "analytics"],
        "collections": ["Asset", "DailyAnalytics"],
        "question": "Distance covered for plate 123 ABC on 2025-02-01.",
        "query": 'db.Asset.aggregate([{"$match":{"details.plate_number":{"$regex":"^123 ABC$","$options":"i"}}},{"$lookup":{"from":"DailyAnalytics","localField":"_id","foreignField":"asset_id","as":"daily"}},{"$unwind":"$daily"},{"$match":{"daily.timestamp":{"$gte":{"$date":"2025-02-01T00:00:00Z"},"$lte":{"$date":"2025-02-01T23:59:59Z"}}}},{"$project":{"_id":0,"plate_number":"$details.plate_number","date":"$daily.timestamp","distance_m":"$daily.distance_m"}}])',
    },
    {
        "tags": ["driver", "assignment", "asset"],
        "collections": ["Driver", "Asset"],
        "question": "Who is the driver of plate LEB 8172? (latest assignment)",
        "query": 'db.Driver.aggregate([{"$unwind":"$asset_assignments"},{"$match":{"asset_assignments.created_at":{"$type":"date"}}},{"$sort":{"_id":1,"asset_assignments.created_at":-1}},{"$group":{"_id":"$_id","doc":{"$first":"$$ROOT"},"latest_assignment":{"$first":"$asset_assignments"}}},{"$lookup":{"from":"Asset","pipeline":[{"$match":{"details.plate_number":{"$regex":"^LEB 8172$","$options":"i"}}},{"$project":{"_id":1}},{"$limit":1}],"as":"matched_asset"}},{"$unwind":"$matched_asset"},{"$match":{"$expr":{"$eq":["$latest_assignment._id","$matched_asset._id"]}}},{"$project":{"_id":0,"driver_name":{"$trim":{"input":{"$concat":[{"$ifNull":["$doc.profile.first_name",""]}," ",{"$ifNull":["$doc.profile.last_name",""]}]}}}}}])',
    },
    {
        "tags": ["distance", "trips", "aggregate", "asset"],
        "collections": ["Trip", "Asset"],
        "question": "Which vehicles covered more than 10 km in the last week?",
        "query": 'db.Trip.aggregate([{"$match":{"driver_info.asset_id":{"$exists":true,"$nin":[null,""]},"distance_covered":{"$type":"number"}}},{"$match":{"$expr":{"$gte":["$start_at",{"$dateSubtract":{"startDate":"$$NOW","unit":"day","amount":7}}]}}},{"$group":{"_id":"$driver_info.asset_id","totalMeters":{"$sum":"$distance_covered"}}},{"$match":{"totalMeters":{"$gt":10000}}},{"$lookup":{"from":"Asset","localField":"_id","foreignField":"_id","as":"asset"}},{"$unwind":"$asset"},{"$project":{"_id":0,"plate_number":"$asset.details.plate_number","totalKm":{"$divide":["$totalMeters",1000]}}}])',
    },
]


def select_examples(sections: List[str], intent: Optional[str], k: int = 3) -> List[str]:
    """Pick the k most relevant examples by tag/collection/keyword overlap (no ML)."""
    tokens = set()
    for s in sections or []:
        tokens.update(t for t in _norm(s).replace("details", " ").split() if t)
        for part in re.split(r"[_\s]+", (s or "").lower()):
            if part:
                tokens.add(part)
    parents = {_SECTION_PARENT.get(_NORM_SECTION.get(_norm(s), ""), "") for s in (sections or [])}
    parents = {p for p in parents if p}
    for w in re.split(r"[^a-z0-9]+", (intent or "").lower()):
        if len(w) > 2:
            tokens.add(w)

    scored: List[Tuple[float, Dict[str, Any]]] = []
    for ex in EXAMPLES:
        score = 0.0
        score += 2.0 * len(parents.intersection(ex.get("collections", [])))
        for tag in ex.get("tags", []):
            tnorm = _norm(tag)
            if tag in tokens or tnorm in tokens or any(tnorm in tk or tk in tnorm for tk in tokens):
                score += 1.0
        if score > 0:
            scored.append((score, ex))

    scored.sort(key=lambda x: x[0], reverse=True)
    chosen = [ex for _s, ex in scored[:k]]
    return [f"Q: {ex['question']}\n{ex['query']}" for ex in chosen]


def _resolve_sections(requested: List[str]) -> Tuple[List[str], Dict[str, List[str]]]:
    """
    Map requested names to canonical sections (tolerant). Returns:
      resolved sections (deduped, order-preserved),
      extra_available: {collection: [other available sections]} for collection-level requests.
    """
    resolved: List[str] = []
    extra_available: Dict[str, List[str]] = {}
    for name in requested or []:
        n = _norm(name)
        if not n:
            continue
        # AvlRecordLatest is handled as its own logical collection in get_query_context.
        if n in ("avlrecordlatest", "avlrecordslatest"):
            continue
        if n in _NORM_SECTION:  # exact section
            sec = _NORM_SECTION[n]
            if sec not in resolved:
                resolved.append(sec)
            continue
        if n in _NORM_COLLECTION:  # top-level collection -> defaults + list the rest
            coll = _NORM_COLLECTION[n]
            for sec in _DEFAULT_SECTIONS.get(coll, _COLLECTION_SECTIONS.get(coll, [])[:1]):
                if sec not in resolved:
                    resolved.append(sec)
            others = [s for s in _COLLECTION_SECTIONS.get(coll, []) if s not in resolved]
            if others:
                extra_available[coll] = others
            continue
        # fuzzy contains match against sections
        match = next((s for k, s in _NORM_SECTION.items() if n and (n in k or k in n)), None)
        if match and match not in resolved:
            resolved.append(match)
    return resolved, extra_available


def get_query_context(sections: List[str], intent: Optional[str] = None) -> Dict[str, Any]:
    """Return pruned fields + relevant joins + 2-3 relevant examples for the requested sections."""
    requested = sections or []
    wants_latest = any(_norm(s) in ("avlrecordlatest", "avlrecordslatest") for s in requested)
    resolved, extra_available = _resolve_sections(requested)

    # Group fields by parent collection, dedupe field lines.
    by_collection: Dict[str, List[str]] = {}
    for sec in resolved:
        parent = _SECTION_PARENT.get(sec, sec)
        bucket = by_collection.setdefault(parent, [])
        for line in _SECTION_FIELDS.get(sec, "").splitlines():
            if line and line not in bucket:
                bucket.append(line)

    schema_blocks: List[str] = []
    if wants_latest:
        # AvlRecordLatest shares AvlRecord's fields but is its own collection (one latest doc/asset).
        schema_blocks.append(
            "Collection: AvlRecordLatest (latest telemetry — exactly one most-recent record per "
            "asset; query it directly and do NOT add $sort/$limit)\nFields:\n"
            + _SECTION_FIELDS.get("AvlRecord_base", "")
        )
    for coll, lines in by_collection.items():
        schema_blocks.append(f"Collection: {coll}\nFields:\n" + "\n".join(lines))
    schemas = "\n\n".join(schema_blocks) if schema_blocks else "(no matching sections; check the menu names)"

    joins = generate_relationship_rules(sorted(by_collection.keys()))
    if wants_latest:
        joins = [
            'Asset -> AvlRecordLatest: localField "_id", foreignField "device_context.asset_id". '
            "AvlRecordLatest holds only the single latest record per asset, so do NOT add $sort or $limit."
        ] + joins

    example_basis = resolved + list(requested)
    if wants_latest:
        example_basis += ["AvlRecord", "latest", "location"]
    examples = select_examples(example_basis, intent)

    result: Dict[str, Any] = {"schemas": schemas, "joins": joins, "examples": examples}
    if extra_available:
        result["other_sections_available"] = extra_available
    return result
