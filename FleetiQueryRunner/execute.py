# file: run_llm_mongo.py
import os
import re
import json
import logging
from typing import Any, Dict, List, Tuple, Union, Iterable, Optional

from dotenv import load_dotenv
from pymongo import MongoClient
from datetime import datetime, timezone, timedelta
from dateutil import parser as dtparser
from bson import ObjectId

try:
    import json5  # tolerant parsing: unquoted keys, trailing commas, single quotes
except ImportError:
    json5 = None

try:
    import yaml  # final fallback parser
except ImportError:
    yaml = None

MongoPayload = Union[List[Dict[str, Any]], Dict[str, Any]]
logger = logging.getLogger(__name__)

# Full results are fetched (the agent caps what the model SEES, not what we fetch).
# This is only a defensive ceiling so a pathological query can't exhaust memory.
_MAX_QUERY_ROWS = int(os.getenv("FLEETI_MAX_QUERY_ROWS", "100000"))


def print(*args: Any, **kwargs: Any) -> None:
    logger.debug(" ".join(str(arg) for arg in args))

# Collections that carry the tenant id directly on their documents.
_TENANT_AWARE_COLLECTIONS = frozenset({
    "AlertHistory", "AlertRule", "Asset", "AssetGroup", "AvlRecord",
    "AvlRecordLatest", "AvlRecordLatestFields", "Device", "Driver", "Geofence",
    "Sim", "SubTenant", "SystemAlertRule", "WaslCompany", "WaslDriver", "WaslVehicle",
})

# Field that holds the tenant id, when it is not sub_tenant_id. SubTenant IS the
# tenant: its sub_account_id equals every other collection's sub_tenant_id.
_TENANT_FIELD = {"SubTenant": "sub_account_id"}

# Every collection the agent may read (as the starting collection or via $lookup).
# Anything else is refused. Collections not in _TENANT_AWARE_COLLECTIONS or
# _GLOBAL_COLLECTIONS must be reached through a tenant-aware join.
_ALLOWED_COLLECTIONS = _TENANT_AWARE_COLLECTIONS | frozenset({
    "ColdChainRecord", "ColdChainRecordLatest", "DailyAnalytics", "DeviceModel",
    "DeviceType", "FuelDrain", "FuelRefill", "Trip",
    "WaslPacket", "WaslPacketLatest",
})

# Global reference catalogs with no tenant data: readable without a tenant scope.
_GLOBAL_COLLECTIONS = frozenset({"DeviceModel"})

# Private fields: the agent may not reference them in a query, and they are
# stripped from results whenever the query touches the owning collection.
# A customer sees all of its OWN data (the tenant filter keeps other customers out),
# except login credentials, the internal account id and drivers' health details.
_PRIVATE_FIELDS: Dict[str, frozenset] = {
    "SubTenant": frozenset({"password", "username", "sub_account_id"}),
    "Driver": frozenset({"blood_type", "allergies", "medications", "medicial_certification"}),
}

# Write stages and server-side JavaScript are never allowed. $unionWith and
# $graphLookup are refused because the tenant filter cannot be enforced on them.
_FORBIDDEN_OPERATORS = frozenset({
    "$out", "$merge", "$function", "$accumulator", "$where", "$unionWith", "$graphLookup",
})

# ---------------------------
# String cleanup & extraction
# ---------------------------

def _clean_raw_response(raw: str) -> str:
    """
    Normalize a raw LLM mongo snippet:
    - strip code fences/backticks
    - unescape visible \n and \t
    - remove wrapping quotes
    """
    s = raw.strip()
    
    # Remove markdown code blocks (```javascript, ```json, ```, etc.)
    s = re.sub(r"^```[a-zA-Z]*\n?", "", s, flags=re.MULTILINE)
    s = re.sub(r"\n?```\s*$", "", s, flags=re.MULTILINE)
    
    # Remove any leading/trailing whitespace
    s = s.strip()
    
    # Unescape visible \n and \t
    s = s.replace("\\n", "\n").replace("\\t", "\t")
    
    # Remove wrapping quotes if the entire string is quoted
    if (s.startswith('"') and s.endswith('"')) or (s.startswith("'") and s.endswith("'")):
        s = s[1:-1]
    
    return s.strip()

def _replace_js_constructors(s: str) -> str:
    """
    Replace Mongo shell constructors with Extended JSON so tolerant loaders can parse:
      ISODate("...")    -> {"$date": "..."}
      ObjectId("...")   -> {"$oid": "..."}
      NumberLong("...") -> {"$numberLong":"..."}
    """
    s = re.sub(r'\bObjectId\(\s*"([^"]+)"\s*\)', r'{"$oid":"\1"}', s)
    s = re.sub(r'\bISODate\(\s*"([^"]+)"\s*\)', r'{"$date":"\1"}', s)
    s = re.sub(r'\bNumberLong\(\s*"([^"]+)"\s*\)', r'{"$numberLong":"\1"}', s)
    s = re.sub(r'\bNumberLong\(\s*([0-9]+)\s*\)', r'{"$numberLong":"\1"}', s)
    return s


def _parse_user_utc_offset(user_time_zone: Optional[str]) -> timezone:
    """
    Parse user timezone in forms like:
    - +5
    - +5:00
    - -03:30
    - UTC+5
    - UTC +5:00
    - UTC-03:30
    Fallback to UTC if parsing fails.
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
    delta = timedelta(hours=hours, minutes=minutes) * sign
    return timezone(delta)


def _to_utc_iso_z(
    date_str: str,
    user_tz: timezone,
    reinterpret_utc_as_user_local: bool = False
) -> Optional[str]:
    """
    Convert a date/datetime string to UTC ISO format with Z suffix.
    If no timezone exists in the input, interpret as user's local timezone.
    """
    parsed_dt: Optional[datetime] = None
    try:
        parsed_dt = dtparser.isoparse(date_str)
    except Exception:
        try:
            parsed_dt = dtparser.parse(date_str)
        except Exception:
            return None

    if parsed_dt.tzinfo is None:
        parsed_dt = parsed_dt.replace(tzinfo=user_tz)
    elif reinterpret_utc_as_user_local:
        # If model emits UTC/Z for local-day boundaries, reinterpret the wall time
        # as user's local time before converting to UTC.
        tz_name = str(parsed_dt.tzinfo).upper()
        utc_like = parsed_dt.utcoffset() == timedelta(0) or tz_name in ("UTC", "UTC+00:00", "Z")
        if utc_like and user_tz.utcoffset(None) != timedelta(0):
            parsed_dt = parsed_dt.replace(tzinfo=None).replace(tzinfo=user_tz)

    utc_dt = parsed_dt.astimezone(timezone.utc)
    if utc_dt.microsecond:
        frac = f"{utc_dt.microsecond:06d}".rstrip("0")
        return utc_dt.strftime("%Y-%m-%dT%H:%M:%S") + f".{frac}Z"
    return utc_dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _apply_user_timezone_to_query_dates(query_str: str, user_time_zone: Optional[str]) -> str:
    """
    Find date/datetime literals in common Mongo query formats and convert them to UTC
    based on user timezone.
    Handles:
    - ISODate("...")
    - {"$date": "..."}
    - quoted date/datetime literals
    """
    user_tz = _parse_user_utc_offset(user_time_zone)
    result = query_str

    # ISODate("...")
    def repl_isodate(match: re.Match) -> str:
        quote = match.group(1)
        value = match.group(2).strip()
        converted = _to_utc_iso_z(value, user_tz, reinterpret_utc_as_user_local=True)
        if not converted:
            return match.group(0)
        return f"ISODate({quote}{converted}{quote})"

    result = re.sub(
        r'ISODate\s*\(\s*(["\'])([^"\']+)\1\s*\)',
        repl_isodate,
        result
    )

    # {"$date":"..."} or {'$date':'...'}
    def repl_extjson_date(match: re.Match) -> str:
        key_q = match.group(1)
        value_q = match.group(2)
        value = match.group(3).strip()
        converted = _to_utc_iso_z(value, user_tz, reinterpret_utc_as_user_local=True)
        if not converted:
            return match.group(0)
        return "{" + f"{key_q}$date{key_q}: {value_q}{converted}{value_q}" + "}"

    result = re.sub(
        r'\{\s*(["\'])\$date\1\s*:\s*(["\'])([^"\']+)\2\s*\}',
        repl_extjson_date,
        result
    )

    # Protect ISODate and Extended JSON segments before generic quoted-date conversion
    protected_sections: List[Tuple[str, str]] = []
    protected_counter = 0

    def protect_segment(match: re.Match) -> str:
        nonlocal protected_counter
        placeholder = f"__PROTECTED_DATE_SEGMENT_{protected_counter}__"
        protected_sections.append((placeholder, match.group(0)))
        protected_counter += 1
        return placeholder

    result = re.sub(r'ISODate\s*\(\s*["\'][^"\']+["\']\s*\)', protect_segment, result)
    result = re.sub(r'\{\s*["\']\$date["\']\s*:\s*["\'][^"\']+["\']\s*\}', protect_segment, result)

    # Generic quoted dates:
    # 1) YYYY-MM-DD
    # 2) YYYY-MM-DDTHH:MM[:SS[.ffffff]][Z|+05:00|-0300]
    # 3) YYYY-MM-DD HH:MM[:SS[.ffffff]][Z|+05:00|-0300]
    date_like_pattern = re.compile(
        r'(["\'])('
        r'\d{4}-\d{2}-\d{2}'
        r'(?:[T t ]\d{2}:\d{2}(?::\d{2}(?:\.\d{1,6})?)?(?:\s?(?:Z|[+\-]\d{2}:?\d{2}))?)?'
        r')\1'
    )

    def repl_quoted_date(match: re.Match) -> str:
        quote = match.group(1)
        value = match.group(2).strip()
        converted = _to_utc_iso_z(value, user_tz, reinterpret_utc_as_user_local=True)
        if not converted:
            return match.group(0)
        return f"{quote}{converted}{quote}"

    result = date_like_pattern.sub(repl_quoted_date, result)

    # Restore protected segments
    for placeholder, original in protected_sections:
        result = result.replace(placeholder, original)

    return result

def _extract_collection_and_op(s: str) -> Tuple[str, str, str]:
    """
    Returns (collection_name, operation, inside_args_str)
    Supports:
      db.Collection.aggregate([...])
      db.Collection.find({...})
    """
    s_compact = re.sub(r"\s+", " ", s)
    m = re.search(r"db\.([A-Za-z0-9_]+)\.(aggregate|find)\s*\(", s_compact)
    if not m:
        raise ValueError("Could not find 'db.<Collection>.(aggregate|find)(' in the raw response.")
    coll = m.group(1)
    op = m.group(2)

    start_idx = s.find(f".{op}")
    if start_idx == -1:
        raise ValueError("Could not locate operation start in original string.")
    paren_idx = s.find("(", start_idx)
    if paren_idx == -1:
        raise ValueError("Could not find '(' after operation.")

    depth = 0
    end_idx = None
    for i in range(paren_idx, len(s)):
        ch = s[i]
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                end_idx = i
                break
    if end_idx is None:
        raise ValueError("Unbalanced parentheses in the operation call.")

    inside = s[paren_idx + 1: end_idx].strip()
    return coll, op, inside

# ---------------------------
# Tolerant parsing
# ---------------------------

def _loads_tolerant(s: str):
    """
    Try strict JSON first, then JSON5, then YAML.
    """
    last_err = None
    try:
        return json.loads(s)
    except Exception as e:
        last_err = e

    if json5 is not None:
        try:
            return json5.loads(s)
        except Exception as e:
            last_err = e

    if yaml is not None:
        try:
            return yaml.safe_load(s)
        except Exception as e:
            last_err = e

    # If all parsers fail, provide more context in the error
    error_msg = f"Failed to parse JSON/YAML. Last error: {str(last_err)}\n"
    error_msg += f"First 500 chars of input: {s[:500]}"
    raise ValueError(error_msg) from last_err

def _split_top_level_args(s: str) -> List[str]:
    """
    Split ' {...}, {...} ' at top-level commas.
    """
    parts = []
    depth = 0
    start = 0
    in_str = False
    str_char = None
    escape = False

    def push(end: int):
        part = s[start:end].strip()
        if part:
            parts.append(part)

    for i, ch in enumerate(s):
        if in_str:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == str_char:
                in_str = False
        else:
            if ch in ('"', "'"):
                in_str = True
                str_char = ch
            elif ch in "{[(":
                depth += 1
            elif ch in "}])":
                depth -= 1
            elif ch == "," and depth == 0:
                push(i)
                start = i + 1

    push(len(s))
    return parts

def _parse_payload(op: str, inside: str) -> MongoPayload:
    """
    Build native Python structures from the call's inside string.
    Accepts Mongo shell style & Extended JSON via tolerant loaders.
    """
    try:
        s = _replace_js_constructors(inside)
        # Remove comments (both // and /* */ style)
        s = re.sub(r"/\*.*?\*/", "", s, flags=re.DOTALL)
        s = re.sub(r"//.*?$", "", s, flags=re.MULTILINE).strip()

        if op == "aggregate":
            if not s.lstrip().startswith("["):
                raise ValueError("aggregate(...) must receive an array/pipeline like: [ { $match: ... }, ... ]")
            return _loads_tolerant(s)

        if op == "find":
            args = _split_top_level_args(s)
            if not args:
                raise ValueError("find(...) missing arguments.")
            if len(args) == 1:
                return _loads_tolerant(args[0])
            return {
                "filter": _loads_tolerant(args[0]),
                "projection": _loads_tolerant(args[1]),
            }

        raise ValueError(f"Unsupported operation: {op}")
    except Exception as e:
        # Provide more context about what we're trying to parse
        error_msg = f"Error parsing {op} payload: {str(e)}\n"
        error_msg += f"Input (first 500 chars): {inside[:500]}"
        raise ValueError(error_msg) from e

# ---------------------------
# Extended JSON → native & path fixes
# ---------------------------

def _convert_extended_json(value: Any) -> Any:
    """
    Convert Extended JSON literals to native Python/BSON:
      {"$date": "..."}        -> datetime
      {"$oid": "..."}         -> ObjectId
      {"$numberLong": "..."}  -> int
    Recurse into lists/dicts.
    """
    if isinstance(value, list):
        return [_convert_extended_json(v) for v in value]

    if isinstance(value, dict):
        keys = set(value.keys())
        if keys == {"$date"}:
            v = value["$date"]
            if isinstance(v, (int, float)):
                return datetime.fromtimestamp(v / 1000.0, tz=timezone.utc)
            return dtparser.isoparse(v)
        if keys == {"$oid"}:
            return ObjectId(value["$oid"])
        if keys == {"$numberLong"}:
            return int(value["$numberLong"])
        return {k: _convert_extended_json(v) for k, v in value.items()}

    return value

def _fix_field_path(key: str) -> str:
    """
    Remove Extended JSON artifacts like '.$date' from field names.
    Keep operator keys (start with '$') as-is.
    """
    if key.startswith("$"):
        return key
    if key.endswith(".$date"):
        return key[: -len(".$date")]
    return key

def _rewrite_keys(obj: Any) -> Any:
    """
    Recursively:
      - Convert Extended JSON values (dates/oids/longs)
      - Fix field path keys that accidentally include '.$date'
    Leaves operator keys untouched.
    """
    if isinstance(obj, list):
        return [_rewrite_keys(x) for x in obj]

    if isinstance(obj, dict):
        new = {}
        for k, v in obj.items():
            v_conv = _convert_extended_json(v)
            v_conv = _rewrite_keys(v_conv)
            new_k = k if k.startswith("$") else _fix_field_path(k)
            new[new_k] = v_conv
        return new

    return obj

def _replace_date_strings_with_isodate(query_str: str) -> str:
    """
    Replace date strings in the query with ISODate() function calls.
    Handles formats like:
    - "2025-09-01T00:00:00Z"
    - "2025-11-01 00:00:00+00:00"
    - "2025-11-01T00:00:00.000Z"
    - "2025-11-10T23:59:59Z"
    
    IMPORTANT: Only replaces standalone date strings, NOT dates already inside ISODate() calls
    or Extended JSON format {"$date": "..."}.
    """
    # First, protect existing ISODate() calls and Extended JSON by temporarily replacing them
    # This prevents our regex from matching dates inside them
    
    # Store protected sections
    protected_sections = []
    protected_counter = 0
    
    # Protect ISODate() calls
    def protect_isodate(match):
        nonlocal protected_counter
        placeholder = f"__PROTECTED_ISODATE_{protected_counter}__"
        protected_sections.append((placeholder, match.group(0)))
        protected_counter += 1
        return placeholder
    
    # Protect Extended JSON date format
    def protect_extended_json_date(match):
        nonlocal protected_counter
        placeholder = f"__PROTECTED_EXTJSON_{protected_counter}__"
        protected_sections.append((placeholder, match.group(0)))
        protected_counter += 1
        return placeholder
    
    # Step 1: Protect existing ISODate() calls
    protected_str = re.sub(r'ISODate\s*\(\s*"([^"]+)"\s*\)', protect_isodate, query_str)
    
    # Step 2: Protect Extended JSON date format
    protected_str = re.sub(r'\{\s*"\$date"\s*:\s*"([^"]+)"\s*\}', protect_extended_json_date, protected_str)
    
    # Step 3: Now replace standalone date strings
    # Pattern to match ISO date strings in quotes (both double and single quotes)
    iso_date_pattern = r'(["\'])(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:?\d{2})?)\1'
    
    def replace_date(match):
        quote_char = match.group(1)
        date_str = match.group(2)
        # Normalize: if date has space separator, convert to T separator for ISODate
        # Keep timezone as-is (Z, +00:00, -05:00, etc.)
        normalized_date = date_str.replace(' ', 'T')
        # Return ISODate() with the normalized date string (always use double quotes)
        return f'ISODate("{normalized_date}")'
    
    # Replace all date strings with ISODate()
    result = re.sub(iso_date_pattern, replace_date, protected_str)
    
    # Step 4: Restore protected sections
    for placeholder, original in protected_sections:
        result = result.replace(placeholder, original)
    
    return result


def _is_sub_tenant_filter_key(key: Any) -> bool:
    """Return True when key represents a sub-tenant filter path."""
    if not isinstance(key, str):
        return False
    normalized = key.strip().strip("\"'").lower()
    return normalized == "sub_tenant_id" or normalized.endswith(".sub_tenant_id")


def _strip_sub_tenant_from_filter(filter_obj: Any) -> Any:
    """
    Recursively remove sub_tenant_id filter keys from Mongo filter expressions.
    Intended for $match/find filter objects only.
    """
    if isinstance(filter_obj, list):
        cleaned_list = []
        for item in filter_obj:
            cleaned_item = _strip_sub_tenant_from_filter(item)
            if isinstance(cleaned_item, dict) and not cleaned_item:
                continue
            cleaned_list.append(cleaned_item)
        return cleaned_list

    if not isinstance(filter_obj, dict):
        return filter_obj

    cleaned: Dict[str, Any] = {}
    for key, value in filter_obj.items():
        if _is_sub_tenant_filter_key(key):
            continue

        # Clean logical expression arrays and remove empty clauses.
        if key in ("$and", "$or", "$nor") and isinstance(value, list):
            clauses = []
            for clause in value:
                cleaned_clause = _strip_sub_tenant_from_filter(clause)
                if isinstance(cleaned_clause, dict) and not cleaned_clause:
                    continue
                clauses.append(cleaned_clause)
            if clauses:
                cleaned[key] = clauses
            continue

        cleaned[key] = _strip_sub_tenant_from_filter(value)

    return cleaned


def _strip_sub_tenant_match_from_payload(op: str, payload: MongoPayload) -> MongoPayload:
    """
    Remove sub_tenant_id filters from:
    - aggregate pipeline $match stages
    - $lookup sub-pipeline $match stages
    - find filter object
    """
    if op == "aggregate" and isinstance(payload, list):
        cleaned_pipeline: List[Dict[str, Any]] = []
        for stage in payload:
            if not isinstance(stage, dict):
                cleaned_pipeline.append(stage)
                continue
            if isinstance(stage.get("$match"), dict):
                stage_copy = dict(stage)
                stage_copy["$match"] = _strip_sub_tenant_from_filter(stage_copy["$match"])
                cleaned_pipeline.append(stage_copy)
            elif isinstance(stage.get("$lookup"), dict):
                lookup = dict(stage["$lookup"])
                if isinstance(lookup.get("pipeline"), list):
                    sub_pipeline = []
                    for sub_stage in lookup["pipeline"]:
                        if isinstance(sub_stage, dict) and isinstance(sub_stage.get("$match"), dict):
                            sub_copy = dict(sub_stage)
                            sub_copy["$match"] = _strip_sub_tenant_from_filter(sub_copy["$match"])
                            sub_pipeline.append(sub_copy)
                        else:
                            sub_pipeline.append(sub_stage)
                    lookup["pipeline"] = sub_pipeline
                cleaned_pipeline.append({"$lookup": lookup})
            else:
                cleaned_pipeline.append(stage)
        return cleaned_pipeline

    if op == "find":
        if isinstance(payload, dict) and isinstance(payload.get("filter"), dict):
            payload_copy = dict(payload)
            payload_copy["filter"] = _strip_sub_tenant_from_filter(payload_copy["filter"])
            return payload_copy
        if isinstance(payload, dict):
            return _strip_sub_tenant_from_filter(payload)

    return payload


def _tenant_field(coll: str) -> str:
    return _TENANT_FIELD.get(coll, "sub_tenant_id")


def _inject_sub_tenant_into_lookup_pipeline(
    sub_pipeline: List[Dict[str, Any]], tenant_value: str, field: str = "sub_tenant_id"
) -> List[Dict[str, Any]]:
    """
    Force the tenant filter into the first $match of a $lookup sub-pipeline (prepend a
    $match if there is none). The server value always wins over any tenant value the
    model wrote itself, so a model-written filter can never widen the scope.
    """
    for i, stage in enumerate(sub_pipeline):
        if isinstance(stage, dict) and isinstance(stage.get("$match"), dict):
            result = list(sub_pipeline)
            result[i] = {"$match": {**stage["$match"], field: tenant_value}}
            return result
    return [{"$match": {field: tenant_value}}] + list(sub_pipeline)


def _lookup_is_correlated(lookup: Dict[str, Any]) -> bool:
    """True when a $lookup joins on the outer document (localField or let variables)."""
    return bool(lookup.get("localField")) or bool(lookup.get("let"))


def _inject_sub_tenant_to_payload(
    op: str, payload: MongoPayload, tenant_value: str
) -> MongoPayload:
    """
    For each $lookup (at any depth, including inside $lookup sub-pipelines and $facet)
    that references a tenant-aware collection, force the tenant filter into the
    $lookup sub-pipeline.

    - Pipeline-form $lookup (has 'pipeline' key): inject into first $match or prepend.
    - Simple-form $lookup (no 'pipeline'): convert to pipeline form that replicates the
      equality join via $expr and adds the tenant filter.
    - $lookup into a collection with no tenant field must be correlated to the outer
      (already tenant-scoped) document, otherwise it would pull every tenant's rows.
    """
    if op != "aggregate" or not isinstance(payload, list):
        return payload

    result = []
    for stage in payload:
        if isinstance(stage, dict) and isinstance(stage.get("$facet"), dict):
            result.append({"$facet": {
                name: _inject_sub_tenant_to_payload("aggregate", sub, tenant_value)
                for name, sub in stage["$facet"].items()
            }})
            continue
        if not isinstance(stage, dict) or not isinstance(stage.get("$lookup"), dict):
            result.append(stage)
            continue

        lookup = dict(stage["$lookup"])
        from_coll = lookup.get("from", "")
        if isinstance(lookup.get("pipeline"), list):
            lookup["pipeline"] = _inject_sub_tenant_to_payload("aggregate", lookup["pipeline"], tenant_value)

        if from_coll not in _TENANT_AWARE_COLLECTIONS:
            if from_coll not in _GLOBAL_COLLECTIONS and not _lookup_is_correlated(lookup):
                raise ValueError(
                    f"$lookup into '{from_coll}' must join on a field of the outer document "
                    f"(localField/foreignField or let) - it has no tenant field of its own."
                )
            result.append({"$lookup": lookup})
            continue

        # This $lookup joins a tenant-aware collection — force the tenant filter.
        field = _tenant_field(from_coll)
        if isinstance(lookup.get("pipeline"), list):
            lookup["pipeline"] = _inject_sub_tenant_into_lookup_pipeline(
                lookup["pipeline"], tenant_value, field
            )
        else:
            # Simple form: convert to pipeline form preserving the equality join.
            local_field = lookup.get("localField", "")
            foreign_field = lookup.get("foreignField", "")
            as_field = lookup.get("as", "")
            safe_local = re.sub(r"[^a-zA-Z0-9_]", "_", local_field) if local_field else "field"
            var_name = f"lf_{safe_local}"
            lookup = {
                "from": from_coll,
                "let": {var_name: f"${local_field}"},
                "pipeline": [
                    {
                        "$match": {
                            "$expr": {"$eq": [f"${foreign_field}", f"$${var_name}"]},
                            field: tenant_value,
                        }
                    }
                ],
                "as": as_field,
            }

        result.append({"$lookup": lookup})

    return result

# ---------------------------
# Object-level transforms for parsed payloads (used by run_payload).
# These let the GPT-5 agent pass an already-parsed pipeline/filter so we never
# do string repair: dates arrive as Extended JSON {"$date": "..."} or ISO
# strings, and tenant isolation is enforced directly on the Python object.
# ---------------------------

_DATE_LIKE_RE = re.compile(
    r'^\d{4}-\d{2}-\d{2}'
    r'(?:[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d{1,6})?)?(?:\s?(?:Z|[+\-]\d{2}:?\d{2}))?)?$'
)


def _apply_user_timezone_to_payload(node: Any, user_tz: timezone) -> Any:
    """
    Object-level analogue of _apply_user_timezone_to_query_dates.
    Reinterprets model-emitted wall-clock date-times as the user's local time and
    converts them to UTC. Only touches {"$date": "..."} values and ISO date-time
    strings that carry a time component.
    """
    if isinstance(node, list):
        return [_apply_user_timezone_to_payload(x, user_tz) for x in node]
    if isinstance(node, dict):
        if set(node.keys()) == {"$date"} and isinstance(node.get("$date"), str):
            converted = _to_utc_iso_z(node["$date"], user_tz, reinterpret_utc_as_user_local=True)
            return {"$date": converted or node["$date"]}
        return {k: _apply_user_timezone_to_payload(v, user_tz) for k, v in node.items()}
    if isinstance(node, str):
        s = node.strip()
        if _DATE_LIKE_RE.match(s) and re.search(r"\d{2}:\d{2}", s):
            converted = _to_utc_iso_z(s, user_tz, reinterpret_utc_as_user_local=True)
            return converted or node
    return node


def _coerce_iso_strings_to_datetime(node: Any) -> Any:
    """
    Convert leftover plain ISO date-time strings (with a time component) into BSON
    datetimes so Mongo date comparisons work. Extended JSON {"$date": "..."} is
    handled separately by _convert_extended_json via _rewrite_keys.
    """
    if isinstance(node, list):
        return [_coerce_iso_strings_to_datetime(x) for x in node]
    if isinstance(node, dict):
        return {k: _coerce_iso_strings_to_datetime(v) for k, v in node.items()}
    if isinstance(node, str):
        s = node.strip()
        if _DATE_LIKE_RE.match(s) and re.search(r"\d{2}:\d{2}", s):
            try:
                dt = dtparser.isoparse(s)
            except Exception:
                try:
                    dt = dtparser.parse(s)
                except Exception:
                    return node
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
    return node


def _enforce_starting_collection_tenant(
    coll: str, op: str, payload: MongoPayload, tenant_value: str
) -> Tuple[MongoPayload, Optional[str]]:
    """
    Object-level analogue of api.py's _enforce_sub_tenant_filter.

    Guarantees tenant isolation on the *starting* collection:
      - Tenant-aware collection: force the tenant filter into the first $match
        (aggregate) or the filter (find); prepend a $match if none exists. The
        server value always overrides a tenant value written by the model.
      - Global catalog (e.g. DeviceModel): no tenant data, nothing to enforce.
      - Other collections: require a $lookup into a tenant-aware collection (its
        sub-pipeline filter is injected by _inject_sub_tenant_to_payload) and drop
        every row whose tenant join came back empty, else reject.

    Returns (payload, error_message). A non-None error means the caller MUST
    reject the query instead of executing it.
    """
    if coll in _TENANT_AWARE_COLLECTIONS:
        field = _tenant_field(coll)
        if op == "aggregate" and isinstance(payload, list):
            for i, stage in enumerate(payload):
                if isinstance(stage, dict) and isinstance(stage.get("$match"), dict):
                    new_payload = list(payload)
                    new_payload[i] = {**stage, "$match": {**stage["$match"], field: tenant_value}}
                    return new_payload, None
            return [{"$match": {field: tenant_value}}] + list(payload), None

        if op == "find" and isinstance(payload, dict):
            if "filter" in payload:
                return {**payload, "filter": {**(payload.get("filter") or {}), field: tenant_value}}, None
            return {**payload, field: tenant_value}, None

        return payload, (
            f"Query on tenant-aware collection '{coll}' has an unsupported shape; "
            f"refusing to run without sub_tenant_id."
        )

    if coll in _GLOBAL_COLLECTIONS:
        return payload, None

    # Non-tenant-aware starting collection: require a tenant-aware $lookup, and keep
    # only the rows that actually joined to this tenant (inner-join semantics), so
    # other tenants' rows never pass through with an empty join array.
    if op == "aggregate" and isinstance(payload, list):
        for i, stage in enumerate(payload):
            if (
                isinstance(stage, dict)
                and isinstance(stage.get("$lookup"), dict)
                and stage["$lookup"].get("from") in _TENANT_AWARE_COLLECTIONS
                and stage["$lookup"].get("as")
            ):
                if not _lookup_is_correlated(stage["$lookup"]):
                    break
                keep_joined = {"$match": {stage["$lookup"]["as"]: {"$ne": []}}}
                return list(payload[: i + 1]) + [keep_joined] + list(payload[i + 1:]), None
    return payload, (
        f"Query on '{coll}' has no $lookup into a tenant-aware collection; "
        f"cannot enforce tenant isolation."
    )


# ---------------------------
# Active-vehicle enforcement (server-side, like tenant isolation).
# The bot only ever answers for ACTIVE vehicles, so every query that touches the
# Asset collection (as the starting collection or via a $lookup) is restricted to
# active ones. A vehicle is ACTIVE only when ALL of these hold TOGETHER:
#   device_availability == "AssignedToDevice"
#   AND status is "Active" OR "Maintenance" (a vehicle under maintenance is still active)
#   AND device_details.imei EXISTS, is non-null, and is not blank/whitespace (a real device)
#   AND expiry_date EXISTS (non-null) AND expiry_date > now
# Anything else is INACTIVE and excluded: not assigned to a device, any other status
# (Inactive, Blocked, ...), no device IMEI, a lapsed expiry_date, or NO expiry_date at all.
# A missing/null expiry_date does NOT mean "never expires" — such a vehicle is inactive,
# because an active subscription must carry a future expiry date.
#
# This mirrors the portal's own active-assets query EXACTLY (same predicates, same
# case-sensitive status match) so FLEETI's active count agrees with the portal dashboard.
# Kept as a flat filter dict (status via $in, not a top-level $or) so its keys merge
# cleanly into any larger $match — tenant injection and the simple-form $lookup rewrite
# below both spread extra keys alongside it — with no top-level operator collisions.
# ---------------------------

# Exact status values that count as active (case-sensitive, to match the portal query).
_ACTIVE_STATUSES = ["Active", "Maintenance"]
# Matches an empty / whitespace-only IMEI; used under $not to require a real device id.
_BLANK_IMEI_REGEX = r"^\s*$"


def _active_asset_filter() -> Dict[str, Any]:
    now = datetime.now(timezone.utc)
    return {
        "device_availability": "AssignedToDevice",
        "status": {"$in": _ACTIVE_STATUSES},
        "device_details.imei": {"$exists": True, "$ne": None, "$not": {"$regex": _BLANK_IMEI_REGEX}},
        "expiry_date": {"$exists": True, "$ne": None, "$gt": now},
    }


# ---------------------------
# Safety guards: allowed collections, read-only, private fields.
# ---------------------------

def _walk(node: Any) -> Iterable[Tuple[Optional[str], Any]]:
    """Yield (key, value) for every dict entry and (None, item) for every list item, recursively."""
    if isinstance(node, dict):
        for k, v in node.items():
            yield k, v
            yield from _walk(v)
    elif isinstance(node, list):
        for item in node:
            yield None, item
            yield from _walk(item)


def _collections_in_payload(coll: str, payload: MongoPayload) -> set:
    """Starting collection plus every collection joined with $lookup (at any depth)."""
    found = {coll}
    for key, value in _walk(payload):
        if key == "$lookup" and isinstance(value, dict) and value.get("from"):
            found.add(value["from"])
    return found


def _last_segment(path: str) -> str:
    return path.lstrip("$").rsplit(".", 1)[-1]


def _validate_payload(coll: str, payload: MongoPayload) -> set:
    """
    Refuse a query that touches a collection outside the allowlist, uses a write stage
    or server-side JavaScript, or references a private field. Returns the set of
    collections the query touches.
    """
    touched = _collections_in_payload(coll, payload)
    unknown = sorted(c for c in touched if c not in _ALLOWED_COLLECTIONS)
    if unknown:
        raise ValueError(f"Collection(s) not available to the assistant: {', '.join(unknown)}")

    private = frozenset().union(*(_PRIVATE_FIELDS.get(c, frozenset()) for c in touched))
    for key, value in _walk(payload):
        if key in _FORBIDDEN_OPERATORS:
            raise ValueError(f"Operator {key} is not allowed (read-only access).")
        if not private:
            continue
        if isinstance(key, str) and not key.startswith("$") and _last_segment(key) in private:
            raise ValueError(f"Field '{_last_segment(key)}' is private and cannot be queried.")
        if isinstance(value, str) and value.startswith("$") and not value.startswith("$$") \
                and _last_segment(value) in private:
            raise ValueError(f"Field '{_last_segment(value)}' is private and cannot be queried.")
    return touched


def _strip_private_fields(node: Any, private: frozenset) -> Any:
    """Remove private keys at any depth (covers $$ROOT and find-without-projection)."""
    if isinstance(node, list):
        return [_strip_private_fields(x, private) for x in node]
    if isinstance(node, dict):
        return {k: _strip_private_fields(v, private) for k, v in node.items() if k not in private}
    return node


def _inject_active_into_asset_lookup(lookup: Dict[str, Any]) -> Dict[str, Any]:
    """Ensure an Asset $lookup only joins active vehicles (handles pipeline & simple form)."""
    lookup = dict(lookup)
    if isinstance(lookup.get("pipeline"), list):
        lookup["pipeline"] = [{"$match": _active_asset_filter()}] + list(lookup["pipeline"])
        return lookup
    # Simple form (localField/foreignField) -> convert to pipeline form preserving the join.
    local_field = lookup.get("localField", "")
    foreign_field = lookup.get("foreignField", "")
    as_field = lookup.get("as", "")
    safe_local = re.sub(r"[^a-zA-Z0-9_]", "_", local_field) if local_field else "field"
    var_name = f"aaf_{safe_local}"
    match_body = _active_asset_filter()
    match_body["$expr"] = {"$eq": [f"${foreign_field}", f"$${var_name}"]}
    return {
        "from": "Asset",
        "let": {var_name: f"${local_field}"},
        "pipeline": [{"$match": match_body}],
        "as": as_field,
    }


def _enforce_active_assets_on_payload(coll: str, op: str, payload: MongoPayload) -> MongoPayload:
    """Restrict every Asset access in the payload to active vehicles."""
    if op == "aggregate" and isinstance(payload, list):
        result: List[Any] = []
        for stage in payload:
            if (
                isinstance(stage, dict)
                and isinstance(stage.get("$lookup"), dict)
                and stage["$lookup"].get("from") == "Asset"
            ):
                lookup = _inject_active_into_asset_lookup(stage["$lookup"])
                result.append({"$lookup": lookup})
                # Inner-join semantics: a record whose linked vehicle isn't active must NOT
                # appear at all (no orphan rows with a blank plate). Drop rows where the
                # active-Asset join came back empty, regardless of how the model $unwinds.
                as_field = lookup.get("as")
                if as_field:
                    result.append({"$match": {as_field: {"$ne": []}}})
            else:
                result.append(stage)
        # Starting collection is Asset -> prepend an active-only $match. Always injected:
        # the filter is a $nor clause, so it cannot be recognized (or forged) by sniffing
        # the model's own $match keys, and an extra AND is only ever more restrictive.
        if coll == "Asset":
            result = [{"$match": _active_asset_filter()}] + result
        return result

    if op == "find" and coll == "Asset":
        if isinstance(payload, dict) and "filter" in payload:
            flt = payload.get("filter") or {}
            return {
                **payload,
                "filter": {"$and": [_active_asset_filter(), flt]} if flt else _active_asset_filter(),
            }
        if isinstance(payload, dict):
            return {"$and": [_active_asset_filter(), payload]} if payload else _active_asset_filter()

    return payload


# ---------------------------
# Runner
# ---------------------------

class LlmMongoRunner:
    def __init__(self, mongo_db: str = None, mongo_uri: str = None):
        load_dotenv()
        resolved_mongo_uri = mongo_uri or os.getenv("MONGO_URI")
        resolved_mongo_db = mongo_db or os.getenv("MONGO_DB")
        if not resolved_mongo_uri or not resolved_mongo_db:
            raise RuntimeError("MONGO_URI and mongo_db must be provided (or MONGO_DB set in .env)")
        self.client = MongoClient(resolved_mongo_uri)
        self.db = self.client[resolved_mongo_db]
        self.last_executed_query: Optional[str] = None

    def run(
        self,
        raw_response: str,
        limit: int = 50,
        user_time_zone: Optional[str] = None,
        remove_sub_tenant_match: bool = False,
        sub_tenant_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Parses and executes an LLM-produced Mongo command string.
        Supports db.<Collection>.aggregate([...]) and .find({...}).
        """
        try:
            cleaned = _clean_raw_response(raw_response)
            cleaned = _apply_user_timezone_to_query_dates(cleaned, user_time_zone)
            # Replace date strings with ISODate() before parsing
            cleaned = _replace_date_strings_with_isodate(cleaned)
            coll, op, inside = _extract_collection_and_op(cleaned)
            payload = _parse_payload(op, inside)
            payload = _rewrite_keys(payload)  # normalize field paths & convert Extended JSON
            if remove_sub_tenant_match:
                payload = _strip_sub_tenant_match_from_payload(op, payload)
            elif sub_tenant_id:
                payload = _inject_sub_tenant_to_payload(op, payload, sub_tenant_id)

            # Build and store the final query string before execution
            if op == "aggregate":
                self.last_executed_query = (
                    f"db.{coll}.aggregate({json.dumps(payload, default=str)})"
                )
            elif op == "find":
                if isinstance(payload, dict) and "filter" in payload:
                    self.last_executed_query = (
                        f"db.{coll}.find({json.dumps(payload['filter'], default=str)}"
                        + (f", {json.dumps(payload['projection'], default=str)}" if payload.get("projection") else "")
                        + ")"
                    )
                else:
                    self.last_executed_query = f"db.{coll}.find({json.dumps(payload, default=str)})"

            query_log_lines = [
                "📋 Executing MongoDB Query:",
                f"Collection: {coll}",
                f"Operation: {op}",
            ]
            if op == "aggregate":
                query_log_lines.append(f"Pipeline: {json.dumps(payload, indent=2, default=str)}")
            elif op == "find":
                if isinstance(payload, dict) and "filter" in payload:
                    query_log_lines.append(f"Filter: {json.dumps(payload.get('filter', {}), indent=2, default=str)}")
                    if payload.get("projection"):
                        query_log_lines.append(f"Projection: {json.dumps(payload.get('projection', {}), indent=2, default=str)}")
                else:
                    query_log_lines.append(f"Filter: {json.dumps(payload, indent=2, default=str)}")
            query_log_lines.append(f"Limit: {limit}")
            logger.info("\n".join(query_log_lines))

            # Print the final query before execution
            print("\n" + "=" * 60)
            print(f"📋 Executing MongoDB Query:")
            print(f"Collection: {coll}")
            print(f"Operation: {op}")
            if op == "aggregate":
                print(f"Pipeline: {json.dumps(payload, indent=2, default=str)}")
            elif op == "find":
                if isinstance(payload, dict) and "filter" in payload:
                    print(f"Filter: {json.dumps(payload.get('filter', {}), indent=2, default=str)}")
                    if payload.get("projection"):
                        print(f"Projection: {json.dumps(payload.get('projection', {}), indent=2, default=str)}")
                else:
                    print(f"Filter: {json.dumps(payload, indent=2, default=str)}")
            print(f"Limit: {limit}")
            print("=" * 60 + "\n")

            collection = self.db[coll]

            if op == "aggregate":
                if not isinstance(payload, list):
                    raise ValueError("aggregate payload must be a list of stages.")
                cursor = collection.aggregate(payload, allowDiskUse=True)
                return list(_take(cursor, limit))

            if op == "find":
                if isinstance(payload, dict) and "filter" in payload:
                    cursor = collection.find(payload["filter"], payload.get("projection"))
                else:
                    cursor = collection.find(payload)
                return list(_take(cursor, limit))

            raise ValueError(f"Unsupported operation: {op}")
        except Exception as e:
            # Provide more context in error message
            error_msg = f"Error executing MongoDB query: {str(e)}\n"
            error_msg += f"Raw response (first 500 chars): {raw_response[:500]}"
            raise RuntimeError(error_msg) from e

    def run_payload(
        self,
        coll: str,
        op: str,
        payload: MongoPayload,
        limit: Optional[int] = None,
        user_time_zone: Optional[str] = None,
        sub_tenant_id: Optional[str] = None,
        remove_sub_tenant_match: bool = False,
    ) -> List[Dict[str, Any]]:
        """
        Execute an ALREADY-PARSED MongoDB payload (no string repair).

        Returns the FULL result set (capped only by the defensive _MAX_QUERY_ROWS
        ceiling) — the agent decides how much of it the model sees.

        Used by the GPT-5 agent: function-call arguments arrive as valid JSON, so
        `payload` is a real Python list (aggregate pipeline) or dict (find filter,
        optionally {"filter": ..., "projection": ...}). We run the same robust
        object-level transforms as the legacy path — timezone normalization,
        Extended JSON conversion, and tenant isolation — then execute.
        """
        try:
            op = (op or "aggregate").strip().lower()
            if op not in ("aggregate", "find"):
                raise ValueError(f"Unsupported operation: {op}")

            # Allowlist, read-only and private-field checks run on the model's own
            # payload, before the server adds anything (e.g. SubTenant's sub_account_id).
            touched = _validate_payload(coll, payload)
            private = frozenset().union(*(_PRIVATE_FIELDS.get(c, frozenset()) for c in touched))

            if user_time_zone:
                user_tz = _parse_user_utc_offset(user_time_zone)
                payload = _apply_user_timezone_to_payload(payload, user_tz)

            payload = _rewrite_keys(payload)            # {"$date"|$oid|$numberLong} -> native
            payload = _coerce_iso_strings_to_datetime(payload)  # bare ISO strings -> datetime

            # Restrict any Asset access to active vehicles (before tenant so the tenant
            # filter merges into the same Asset $match).
            payload = _enforce_active_assets_on_payload(coll, op, payload)

            if remove_sub_tenant_match:
                payload = _strip_sub_tenant_match_from_payload(op, payload)
            elif sub_tenant_id:
                payload, guard_error = _enforce_starting_collection_tenant(
                    coll, op, payload, sub_tenant_id
                )
                if guard_error:
                    raise ValueError(guard_error)
                payload = _inject_sub_tenant_to_payload(op, payload, sub_tenant_id)

            effective_limit = _MAX_QUERY_ROWS if (not limit or limit <= 0) else min(limit, _MAX_QUERY_ROWS)
            rows = self._execute(coll, op, payload, effective_limit)
            return _strip_private_fields(rows, private) if private else rows
        except Exception as e:
            error_msg = f"Error executing MongoDB payload: {str(e)}\n"
            error_msg += f"Collection={coll} op={op}"
            raise RuntimeError(error_msg) from e

    def _execute(self, coll: str, op: str, payload: MongoPayload, limit: int) -> List[Dict[str, Any]]:
        """Build the logged query string, log it, and execute. Shared by run_payload."""
        if op == "aggregate":
            self.last_executed_query = (
                f"db.{coll}.aggregate({json.dumps(payload, default=str)})"
            )
        elif op == "find":
            if isinstance(payload, dict) and "filter" in payload:
                self.last_executed_query = (
                    f"db.{coll}.find({json.dumps(payload['filter'], default=str)}"
                    + (f", {json.dumps(payload['projection'], default=str)}" if payload.get("projection") else "")
                    + ")"
                )
            else:
                self.last_executed_query = f"db.{coll}.find({json.dumps(payload, default=str)})"

        query_log_lines = [
            "📋 Executing MongoDB Query:",
            f"Collection: {coll}",
            f"Operation: {op}",
        ]
        if op == "aggregate":
            query_log_lines.append(f"Pipeline: {json.dumps(payload, indent=2, default=str)}")
        elif op == "find":
            if isinstance(payload, dict) and "filter" in payload:
                query_log_lines.append(f"Filter: {json.dumps(payload.get('filter', {}), indent=2, default=str)}")
                if payload.get("projection"):
                    query_log_lines.append(f"Projection: {json.dumps(payload.get('projection', {}), indent=2, default=str)}")
            else:
                query_log_lines.append(f"Filter: {json.dumps(payload, indent=2, default=str)}")
        query_log_lines.append(f"Limit: {limit}")
        logger.info("\n".join(query_log_lines))

        collection = self.db[coll]

        if op == "aggregate":
            if not isinstance(payload, list):
                raise ValueError("aggregate payload must be a list of stages.")
            cursor = collection.aggregate(payload, allowDiskUse=True)
            return list(_take(cursor, limit))

        if op == "find":
            if isinstance(payload, dict) and "filter" in payload:
                cursor = collection.find(payload["filter"], payload.get("projection"))
            else:
                cursor = collection.find(payload)
            return list(_take(cursor, limit))

        raise ValueError(f"Unsupported operation: {op}")


def _take(it: Iterable[Dict[str, Any]], n: int) -> Iterable[Dict[str, Any]]:
    count = 0
    for doc in it:
        yield doc
        count += 1
        if count >= n:
            break

# ---------------------------
# Example usage
# ---------------------------
if __name__ == "__main__":
    # query to get the trips for a specific asset
    raw = "db.Trips.aggregate([\n  {\n    $lookup: {\n      from: \"Asset\",\n      localField: \"driver_info.asset_id\",\n      foreignField: \"asset_id\",\n      as: \"asset\"\n    }\n  },\n  {\n    $unwind: \"$asset\"\n  },\n  {\n    $match: {\n      \"asset.plate_number\": \"3688 FHD\"\n    }\n  },\n  {\n    $addFields: {\n      created_at: {\n        $dateToString: {\n          format: \"%Y-%m-%dT%H:%M:%S\",\n          date: \"$created_at\"\n        }\n      }\n    }\n  },\n  {\n    $match: {\n      created_at: {\n        $gte: ISODate(\"2025-10-20T00:00:00.000Z\"),\n        $lte: ISODate(\"2025-11-20T00:05:00.000Z\")\n      }\n    }\n  },\n  {\n    $sort: {\n      created_at: -1\n    }\n  },\n  {\n    $limit: 1\n  },\n  {\n    $project: {\n      _id: 0,\n      created_at: 1,\n      imei: 1,\n      device_id: 1,\n      start_at: 1,\n      end_at: 1,\n      duration: 1,\n      start_location: 1,\n      start_odometer: 1,\n      start_fuel_level: 1,\n      end_location: 1,\n      end_odometer: 1,\n      end_fuel_level: 1,\n      distance_covered: 1,\n      distance_covered_orthodromic: 1,\n      avg_speed: 1,\n      max_speed: 1,\n      idle_time: 1,\n      driver_info: 1,\n      harsh_braking_occurrence: 1,\n      harsh_acceleration_occurrence: 1,\n      harsh_cornering_occurrence: 1,\n      over_speeding_occurrence: 1,\n      idling_occurrence: 1,\n      zigzagging_occurrence: 1,\n      crashing_count: 1,\n      sudden_stop_count: 1,\n      sharp_turn_count: 1,\n      frequent_start_stop_count: 1,\n      fuel_consumed_ltrs: 1,\n      fuel_refill_count: 1,\n      behaviour_score: 1,\n      safety_score: 1,\n      packet_info: 1\n    }\n  }\n])"

    runner = LlmMongoRunner()
    results = runner.run(raw, limit=10)
    for doc in results:
        print(doc)
