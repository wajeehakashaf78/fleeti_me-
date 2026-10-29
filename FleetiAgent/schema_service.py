"""
Schema + query-context service for the FLEETI GPT-5 agent.

DB knowledge (collections, fields, enums, notes, joins, example queries) is read from the
text files in FleetDbSummarizer/db_knowledge/ via FleetDbSummarizer.knowledge. Only the
query RULES live here in Python.

  - build_menu(): a compact always-on MENU (every collection, its sections and the
    disambiguations) embedded in the get_query_context tool description.
  - get_query_context(): the fields of the requested sections, the collections' enums and
    notes, the exact joins between them and 2-3 example queries.

RAG (FleetDbSummarizer.rag - Nomic embeddings in Postgres/pgvector, HNSW) chooses the
examples and adds the most relevant extra fields for the user's question. The menu, joins
and rules never go through RAG. Without Postgres it falls back to keyword matching.
"""

import re
import logging
from typing import Any, Dict, List, Optional, Tuple

from FleetDbSummarizer.knowledge import Example, load_knowledge
from FleetDbSummarizer import rag
from FleetiAgent.context_memory import MAX_CONTEXT_TOKENS, ConversationView, count_tokens

logger = logging.getLogger(__name__)

_K = load_knowledge()


def _norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


# Normalized section name -> canonical section; normalized collection -> canonical collection.
_NORM_SECTION = {_norm(s): s for s in _K.section_fields}
_NORM_COLLECTION = {_norm(c): c for c in _K.collections}
_EXAMPLES_BY_KEY = {ex.key: ex for ex in _K.examples}

# Kept for callers that used the old in-Python example bank.
EXAMPLES: List[Dict[str, Any]] = [
    {"tags": ex.tags, "collections": ex.collections, "question": ex.question, "query": ex.query}
    for ex in _K.examples
]


# ================================
# On-demand rule packs
# ================================
# Exact operational definitions that are too long (and too rarely needed) to sit in the
# always-on prompt. The MENU advertises them by name; get_query_context returns the full
# text only when the model asks for the pack — so the cached prefix stays small.
_RULE_PACKS_MENU = """ON-DEMAND RULE PACKS (request by name via get_query_context, exactly like a section):
- asset_status_rules — the EXACT definitions and thresholds for a vehicle's CONNECTIVITY
  (online / reporting / responding, offline, not reporting, not connected) and its MOVEMENT
  (moving, idle, stopped/parked, illegal movement). Request this pack BEFORE answering ANY
  question about those states — including counts, breakdowns, and "which vehicles are ..."
  lists. These thresholds are NOT guessable, so never answer such a question from memory.
  The pack also returns the Asset + AvlRecordLatest fields, joins and examples, so a single
  get_query_context call is all you need."""


ASSET_STATUS_RULES = """ASSET STATUS RULES — connectivity & movement (authoritative; follow exactly).

SCOPE: these states apply to ACTIVE vehicles ONLY. The server already restricts every Asset
access to active vehicles, so never add active/inactive conditions yourself. An INACTIVE
vehicle is NOT "offline" and NOT "not connected" — it is a separate category that has already
been excluded from your results.

SOURCE: every state is read from the vehicle's newest AvlRecordLatest packet, and that packet
MUST be matched with is_processed: true (ignore unprocessed packets entirely). The packet's
time field is `timestamp`. Join: Asset._id -> AvlRecordLatest.device_context.asset_id.
AvlRecordLatest keeps one row per DEVICE and a few vehicles have two devices, so inside the
$lookup sub-pipeline ALWAYS add {"$sort":{"timestamp":-1}},{"$limit":1} right after the
is_processed match — that keeps each vehicle's newest packet so every vehicle counts ONCE.

CONNECTIVITY — mutually exclusive; every active vehicle is in exactly ONE of these:
  * ONLINE (same thing as REPORTING / RESPONDING): has an is_processed packet whose
    timestamp is within the last 30 MINUTES.
  * OFFLINE: has an is_processed packet whose timestamp is older than 30 MINUTES but
    within the last 12 HOURS.
  * NOT REPORTING: has an is_processed packet whose timestamp is older than 12 HOURS.
  * NOT CONNECTED: has NO is_processed packet in AvlRecordLatest at all.
  OFFLINE, NOT REPORTING and NOT CONNECTED are three DIFFERENT states — never treat them as
  synonyms, never merge them, and answer only the one the user asked about.

Cutoffs — always compute from $$NOW, never from a hardcoded clock time:
  30 minutes: {"$dateSubtract":{"startDate":"$$NOW","unit":"minute","amount":30}}
  12 hours:   {"$dateSubtract":{"startDate":"$$NOW","unit":"hour","amount":12}}

MOVEMENT — applies ONLY to ONLINE vehicles, read from that SAME latest packet's `speed` and
`ignition_status`. ignition_status is the string "On"/"Off"; match it case-insensitively with
{"$regex":"^on$","$options":"i"} (or "^off$"):
  * MOVING           = speed > 0  AND ignition_status "On"
  * IDLE             = speed == 0 AND ignition_status "On"
  * STOPPED (parked) = speed == 0 AND ignition_status "Off"
  * ILLEGAL MOVEMENT = speed > 0  AND ignition_status "Off"
A vehicle that is not ONLINE has no movement state — never report it as stopped/parked.

QUERY SHAPE:
- ONLINE / OFFLINE / NOT REPORTING, and every movement state: start from Asset, $lookup
  AvlRecordLatest (sub-pipeline: is_processed match, then $sort timestamp desc + $limit 1),
  $unwind, then filter on the joined packet's timestamp / speed / ignition_status.
- ALWAYS $unwind the joined packet for those states. Do NOT read it with
  $addFields + $first: a vehicle with no packet then yields a MISSING value, and missing
  sorts BELOW every date, so it silently passes an "older than X" test and drags NOT
  CONNECTED vehicles into your OFFLINE / NOT REPORTING answer. $unwind drops them cleanly.
- NOT CONNECTED: start from Asset, $lookup AvlRecordLatest, and keep the assets whose joined
  array is EMPTY. Do NOT start from AvlRecordLatest for this state — a vehicle with no packet
  has no row there and could never be found."""

# Names the model may use to request the status pack (normalized, so casing/underscores
# do not matter). Matched BEFORE section resolution so they never fuzzy-match a real section.
_STATUS_RULES_ALIASES = frozenset({
    "assetstatusrules", "assetstatus", "statusrules", "vehiclestatusrules",
    "connectivityrules", "assetconnectivityrules", "movementrules",
})

# Seeded into example selection whenever the pack is requested, so the status examples
# always outrank the generic latest-telemetry ones regardless of the `intent` text.
_STATUS_EXAMPLE_HINTS = [
    "online", "offline", "reporting", "not-reporting", "not-connected",
    "connectivity", "status", "moving", "idle", "stopped", "illegal-movement",
]
_STATUS_SECTIONS = ["asset_base", "asset_details_base", "AvlRecordLatest_base"]


def build_menu() -> str:
    """Render the compact always-on collection menu (embedded in the tool description)."""
    lines: List[str] = ["COLLECTIONS (request sections via get_query_context):"]
    for coll, info in _K.collections.items():
        lines.append(f"\n{coll} — {info.purpose}")
        lines.append(f"  ids: {info.ids}")
        if not info.tenant.startswith("yes"):
            lines.append(f"  tenant: {info.tenant}")
        sec_parts = [f"{sec} ({note})" if note else sec for sec, note in info.section_notes.items()]
        if sec_parts:
            lines.append("  sections: " + " | ".join(sec_parts))
    if "DISAMBIGUATIONS" in _K.overview:
        lines.append("\n" + _K.overview["DISAMBIGUATIONS"])
    lines.append("\n" + _RULE_PACKS_MENU)
    return "\n".join(lines)


# ================================
# Invariant query RULES (deduped from prompt_blueprint.py)
# ================================
RULES = """QUERY RULES:
- Plate numbers: match details.plate_number with case-insensitive exact regex {"$regex":"^<plate>$","$options":"i"}; never match _id/asset_id. Match other string identifiers (geofence/alert/rule names) the same ^...$ /i way. For event/alert names match alert_info.alert_message in AlertHistory with a flexible regex, e.g. {"$regex":"harsh[-_\\\\s]*braking|harshbraking","$options":"i"}, and set alert_info.type ('systemAlert'|'alertRule'|'geofencealert') when the kind is known.
- Dates: emit ALL dates as Extended JSON {"$date":"YYYY-MM-DDTHH:MM:SSZ"} — never ISODate(...) or a bare string. Resolve relative dates/times against the per-turn "Current date & time" (user's timezone).
- TIMEZONE — emit the LOCAL wall-clock time the user means (in THEIR timezone) and do NOT convert to UTC yourself; the server converts user-local times to UTC before querying. Example: user in UTC+5 asks "from 2pm to 4pm" -> emit {"$date":"...T14:00:00Z"} and {"$date":"...T16:00:00Z"} (the server turns these into 09:00–11:00 UTC). A whole day "on 2026-06-20" -> 00:00:00 to 23:59:59 of that local date. (Relative ranges built with $$NOW are already UTC — do not adjust those.)
- Time intent: latest/last/current -> $sort the time field desc + $limit 1; oldest/first -> asc + $limit 1; an exact time -> match a +/-5 minute window and pick the closest record. Add $sort/$limit only when ordering or a single/top-N result is implied; never for "all".
- AvlRecord / AvlRecordLatest: ALWAYS include is_processed: true in the match — ignore unprocessed packets. AvlRecord and WaslPacket hold billions of rows: always filter them by vehicle (imei / device_context.asset_id) AND a time range.
- Vehicle STATUS questions — online / reporting / responding, offline, not reporting, not connected, or moving / idle / stopped / parked / illegal movement — have EXACT definitions and time thresholds that you must NOT guess or infer. Call get_query_context with sections ["asset_status_rules"] FIRST; it returns those rules plus the fields, joins and examples you need. This applies to counts and breakdowns too (e.g. "how many vehicles are online"). These states are evaluated over ACTIVE vehicles only.
- Joins: $lookup only to reach fields in a DIFFERENT collection; never join a collection to itself. Use the localField/foreignField from the get_query_context "joins" output.
- Projection: always exclude _id ("_id":0) and never project any *_id field; use full paths, e.g. {"plate_number":"$details.plate_number"}.
- Tenant: do NOT add sub_tenant_id yourself — the server injects it. If the starting collection has no tenant field of its own (Trip, DailyAnalytics, DeviceType, FuelRefill, FuelDrain, ColdChainRecord, ColdChainRecordLatest, WaslPacket, WaslPacketLatest), start from Asset or include a $lookup into a tenant-aware collection (Asset, Device, Driver, ...) joined on a field (localField/foreignField or let) so the server can scope via the join; rows that do not join are dropped. Queries are read-only: $out, $merge, $unionWith, $graphLookup and server-side JavaScript are refused. Private fields (credentials, national ids, personal contacts) are refused too.
- Active vehicles only: every Asset access (any vehicle/plate question) is automatically restricted server-side to ACTIVE vehicles. A vehicle is ACTIVE only when ALL of these are true TOGETHER: device_availability is "AssignedToDevice" AND status is "Active" or "Maintenance" (a vehicle under maintenance still counts as active) AND it has a real device IMEI AND it has an expiry_date that is still in the future. Anything else is INACTIVE / EXPIRED SUBSCRIPTION and is excluded — not assigned to a device, any other status (Inactive, Blocked, ...), no device IMEI, an expiry_date already passed, or no expiry_date at all. Expired vehicles must never appear in any answer. If the user's question is specifically about EXPIRED / inactive / deactivated / blocked vehicles (e.g. "how many are expired", "list inactive vehicles"), do NOT build or run a query — it can only ever come back empty; instead refuse briefly (you cover active vehicles only). Treat "vehicles" as active vehicles; do NOT add these conditions yourself. Records that link to a NON-active vehicle (e.g. alerts/events/trips whose vehicle isn't active) are EXCLUDED — the server inner-joins Asset, so such rows are dropped entirely (you won't see blank-plate orphan rows).
- Data-source preference (choose silently; never ask the user which source to use):
  1. OVERALL / all-time entity KPIs come from the entity's OWN collection. For a driver's overall scores/metrics (safety score, behavior score, performance rating, all-time average speed, total trips/distance/hours, harsh-event counts) read directly from Driver.driver_analytics / Driver.analytics / Driver.behavior / Driver.performance — do NOT recompute them from Trip or DailyAnalytics.
  2. For a SPECIFIC TIME RANGE (today, yesterday, last 7 days, a date range) aggregate from Trip (per-trip rows: avg_speed, max_speed, distance_covered, duration, idle_time, safety/behaviour scores) or DailyAnalytics (per-day rows, the day field is `date`), whichever fits the metric.
  3. For INSTANTANEOUS / raw values (current speed, a reading at a moment) use AvlRecord / AvlRecordLatest.
- Distances are stored in METERS; return them raw (the assistant converts units when answering)."""


def _format_example(ex: Example) -> str:
    return f"Q: {ex.question}\n{ex.query}"


def select_examples(sections: List[str], intent: Optional[str], k: int = 3) -> List[str]:
    """Keyword fallback: the k most relevant examples by tag/collection/word overlap, formatted."""
    return [_format_example(ex) for ex in _select_example_items(sections, intent, k)]


def _select_example_items(sections: List[str], intent: Optional[str], k: int = 3) -> List[Example]:
    tokens = set()
    for s in sections or []:
        tokens.update(t for t in _norm(s).replace("details", " ").split() if t)
        for part in re.split(r"[_\s]+", (s or "").lower()):
            if part:
                tokens.add(part)
    parents = {_K.section_parent.get(_NORM_SECTION.get(_norm(s), ""), "") for s in (sections or [])}
    parents |= {_NORM_COLLECTION[_norm(s)] for s in (sections or []) if _norm(s) in _NORM_COLLECTION}
    parents.discard("")
    for w in re.split(r"[^a-z0-9]+", (intent or "").lower()):
        if len(w) > 2:
            tokens.add(w)

    scored: List[Tuple[float, Example]] = []
    for ex in _K.examples:
        score = 2.0 * len(parents.intersection(ex.collections))
        for tag in ex.tags:
            tnorm = _norm(tag)
            if tag in tokens or tnorm in tokens or any(tnorm in tk or tk in tnorm for tk in tokens):
                score += 1.0
        if score > 0:
            scored.append((score, ex))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [ex for _s, ex in scored[:k]]


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
        if not n or n in _STATUS_RULES_ALIASES:  # rule packs are attached separately
            continue
        if n == "avlrecordslatest":
            n = "avlrecordlatest"
        if n in _NORM_SECTION:  # exact section
            sec = _NORM_SECTION[n]
            if sec not in resolved:
                resolved.append(sec)
            continue
        if n in _NORM_COLLECTION:  # top-level collection -> defaults + list the rest
            coll = _NORM_COLLECTION[n]
            info = _K.collections[coll]
            for sec in info.default_sections:
                if sec in _K.section_fields and sec not in resolved:
                    resolved.append(sec)
            others = [s for s in info.section_notes if s not in resolved]
            if others:
                extra_available[coll] = others
            continue
        # fuzzy contains match against sections
        match = next((s for key, s in _NORM_SECTION.items() if n in key or key in n), None)
        if match and match not in resolved:
            resolved.append(match)
    return resolved, extra_available


def _joins_between(collections: List[str]) -> List[str]:
    wanted = set(collections)
    return [r.text() for r in _K.relationships
            if r.left in wanted and r.right in wanted and r.left != r.right]


_ALREADY_GIVEN_NOTE = (
    "Items marked 'given earlier' were already sent in this conversation - reuse those exact "
    "field paths, joins and examples. If you no longer have them, call get_query_context again "
    "with refresh: true."
)


def _render(by_collection: Dict[str, List[str]], extra: Dict[str, List[str]], memory: Optional[ConversationView],
            sent: List[str]) -> str:
    """Schema text; with a memory, lines already given in this conversation are left out."""
    blocks: List[str] = []
    for coll in by_collection:
        info = _K.collections[coll]
        lines = by_collection[coll] + [ln for ln in extra.get(coll, []) if ln not in by_collection[coll]]
        values = [f"- {e}" for e in info.enums]
        notes = [f"- {n}" for n in info.notes]

        def new(items: List[str]) -> List[str]:
            fresh = [i for i in items if not (memory and memory.seen(f"{coll}|{i}"))]
            sent.extend(f"{coll}|{i}" for i in fresh)
            return fresh

        head_key = f"{coll}|_head"
        head_seen = bool(memory and memory.seen(head_key))
        new_lines, new_values, new_notes = new(lines), new(values), new(notes)
        given = len(lines) - len(new_lines)
        if head_seen and not (new_lines or new_values or new_notes):
            blocks.append(f"Collection: {coll} — all {len(lines)} fields, values and notes given earlier")
            continue
        sent.append(head_key)
        block = f"Collection: {coll} — {info.purpose}\nTenant: {info.tenant}\nFields:\n" + "\n".join(new_lines)
        if given:
            block += f"\n(+{given} more fields given earlier)"
        if new_values:
            block += "\nValues:\n" + "\n".join(new_values)
        if new_notes:
            block += "\nNotes:\n" + "\n".join(new_notes)
        blocks.append(block)
    return "\n\n".join(blocks) if blocks else "(no matching sections; check the menu names)"


def get_query_context(sections: List[str], intent: Optional[str] = None, question: Optional[str] = None,
                      memory: Optional[ConversationView] = None) -> Dict[str, Any]:
    """
    Fields + enums/notes + exact joins + 2-3 examples for the requested sections.

    memory: what this conversation already received (FleetiAgent.context_memory). Lines,
    joins and examples given in recent turns are replaced by a short "given earlier" marker.
    The result is kept under MAX_CONTEXT_TOKENS by dropping optional extras first; the
    requested fields, values, notes, joins and rules are never dropped.
    """
    requested = list(sections or [])
    wants_status_rules = any(_norm(s) in _STATUS_RULES_ALIASES for s in requested)
    if wants_status_rules:
        # Every connectivity/movement question reads the latest packet and identifies the
        # vehicle by plate, so pull those in automatically: one call returns the rules plus
        # the fields, joins and examples needed to write the query.
        requested += _STATUS_SECTIONS

    resolved, extra_available = _resolve_sections(requested)

    # Group fields by owning collection, dedupe field lines.
    by_collection: Dict[str, List[str]] = {}
    for sec in resolved:
        bucket = by_collection.setdefault(_K.section_parent[sec], [])
        for line in _K.section_fields.get(sec, []):
            if line not in bucket:
                bucket.append(line)
    involved = list(by_collection)

    # RAG: relevant extra fields of these collections + best examples + related collections.
    query_text = " ".join(t for t in (question, intent) if t).strip()
    hits = rag.retrieve(query_text, involved) if query_text else None
    rag_fields: Dict[str, List[str]] = dict(hits["fields"]) if hits else {}

    if hits and not wants_status_rules:
        example_items = [_EXAMPLES_BY_KEY[key] for key in hits["examples"] if key in _EXAMPLES_BY_KEY]
    else:
        basis = resolved + requested + (_STATUS_EXAMPLE_HINTS if wants_status_rules else [])
        example_items = _select_example_items(basis, intent)
    examples_seen = [ex for ex in example_items if memory and memory.seen(f"example|{ex.key}")]
    example_items = [ex for ex in example_items if ex not in examples_seen]

    joins_all = _joins_between(involved)
    joins = [j for j in joins_all if not (memory and memory.seen(f"join|{j}"))]
    related = [f"{c} — {_K.collections[c].purpose}" for c, _s in (hits["related"] if hits else []) if c in _K.collections]

    def build(sent: List[str]) -> Dict[str, Any]:
        result: Dict[str, Any] = {}
        if wants_status_rules:
            # First key so the model reads the authoritative thresholds before the schema.
            result["asset_status_rules"] = ASSET_STATUS_RULES
        result["schemas"] = _render(by_collection, rag_fields, memory, sent)
        result["joins"] = joins
        if len(joins) < len(joins_all):
            result["joins_given_earlier"] = len(joins_all) - len(joins)
        result["examples"] = [_format_example(ex) for ex in example_items]
        if examples_seen:
            result["examples_given_earlier"] = [ex.question for ex in examples_seen]
        if extra_available:
            result["other_sections_available"] = extra_available
        if related:
            result["maybe_relevant_collections"] = related
        if memory and (len(joins) < len(joins_all) or examples_seen or "given earlier" in result["schemas"]):
            result["note"] = _ALREADY_GIVEN_NOTE
        return result

    # Token budget: drop optional extras (least important first) until the result fits.
    sent: List[str] = []
    result = build(sent)
    tokens = count_tokens(result)
    trimmed: List[str] = []
    for step in ("related", "examples", "rag_fields", "other_sections"):
        if tokens <= MAX_CONTEXT_TOKENS:
            break
        if step == "related" and related:
            related = []
        elif step == "examples" and len(example_items) > 1:
            example_items = example_items[:1]
        elif step == "rag_fields" and rag_fields:
            rag_fields = {}
        elif step == "other_sections" and extra_available:
            extra_available = {}
        else:
            continue
        trimmed.append(step)
        sent = []
        result = build(sent)
        tokens = count_tokens(result)

    if memory:
        memory.mark(sent + [f"join|{j}" for j in joins] + [f"example|{ex.key}" for ex in example_items])
    logger.info(
        "get_query_context | sections=%s | collections=%s | retrieval=%s | examples=%d | tokens=%d%s%s",
        requested, involved, "rag" if hits else "keyword", len(example_items), tokens,
        f" | trimmed={trimmed}" if trimmed else "",
        f" | reused={len(joins_all) - len(joins)} joins, {len(examples_seen)} examples" if memory else "",
    )
    return result
