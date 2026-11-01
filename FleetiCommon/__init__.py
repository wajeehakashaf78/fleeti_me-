"""
FleetiCommon - shared helpers used by both the legacy /chat pipeline and the
new GPT-5 agentic /chat/v2 flow.

These functions were originally defined inline in api.py. They are pure (no
hidden global state beyond the already-shared mongo_handler) and are extracted
here so the new FleetiAgent tools can reuse them verbatim. Behavior is identical
to the original definitions.
"""

import re
import logging
from datetime import timezone, timedelta
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

from dateutil import parser as dtparser

from FleetiReports.mongo_handler import mongo_handler
from FleetiReports.api_handler import APIHandler
from FleetiReports.models import LLMResponse

logger = logging.getLogger(__name__)


# ================================
# Reports base URL + tenant scoping
# ================================
def build_reports_base_url(base_url: str) -> str:
    return base_url.rstrip("/") + "/api/admin/reports"


def extract_hostname(base_url: Optional[str]) -> Optional[str]:
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


def should_remove_sub_tenant_match(sub_tenant_id: Optional[str], base_url: Optional[str]) -> bool:
    """
    Skip sub_tenant_id query filtering when either:
      - The JWT did not provide a sub_tenant_id (nothing to filter by), or
      - The FE base URL host equals the JWT sub_tenant_id (the subdomain
        already scopes the data, so an additional filter is redundant).
    """
    if not sub_tenant_id:
        return True
    host = extract_hostname(base_url)
    if not host:
        return False
    return host == sub_tenant_id.strip().lower().strip(".")


# ================================
# Date range / timezone helpers
# ================================
def parse_date_range(date_range_str: str) -> Tuple[str, str]:
    if "," in date_range_str:
        parts = date_range_str.split(",", 1)
        return parts[0].strip(), parts[1].strip()
    return date_range_str.strip(), date_range_str.strip()


def parse_user_utc_offset(user_time_zone: Optional[str]) -> timezone:
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


_UTC_OFFSET_TO_IANA: Dict[int, str] = {
    -720: "Etc/GMT+12",
    -660: "Pacific/Midway",
    -600: "Pacific/Honolulu",
    -570: "Pacific/Marquesas",
    -540: "America/Anchorage",
    -480: "America/Los_Angeles",
    -420: "America/Denver",
    -360: "America/Chicago",
    -300: "America/New_York",
    -270: "America/Caracas",
    -240: "America/Halifax",
    -210: "America/St_Johns",
    -180: "America/Sao_Paulo",
    -120: "America/Noronha",
     -60: "Atlantic/Azores",
       0: "UTC",
      60: "Europe/London",
     120: "Europe/Paris",
     180: "Asia/Riyadh",
     210: "Asia/Tehran",
     240: "Asia/Dubai",
     270: "Asia/Kabul",
     300: "Asia/Karachi",
     330: "Asia/Kolkata",
     345: "Asia/Kathmandu",
     360: "Asia/Dhaka",
     390: "Asia/Yangon",
     420: "Asia/Bangkok",
     480: "Asia/Singapore",
     525: "Australia/Eucla",
     540: "Asia/Tokyo",
     570: "Australia/Darwin",
     600: "Australia/Sydney",
     630: "Pacific/Norfolk",
     660: "Pacific/Noumea",
     720: "Pacific/Auckland",
     765: "Pacific/Chatham",
     780: "Pacific/Apia",
     840: "Pacific/Kiritimati",
}


def offset_to_iana_timezone(user_time_zone: Optional[str]) -> Optional[str]:
    """
    Convert a UTC offset string (+5, +5:00, UTC+5:00, -03:30) to an IANA
    timezone name (e.g. Asia/Karachi). Returns None when unparseable or unmapped.
    """
    if not user_time_zone:
        return None
    m = re.match(
        r"^\s*(?:UTC\s*)?([+-])\s*(\d{1,2})(?::?\s*(\d{2}))?\s*$",
        user_time_zone,
        flags=re.IGNORECASE,
    )
    if not m:
        return None
    sign = 1 if m.group(1) == "+" else -1
    hours = int(m.group(2))
    minutes = int(m.group(3) or 0)
    if hours > 14 or minutes > 59:
        return None
    return _UTC_OFFSET_TO_IANA.get(sign * (hours * 60 + minutes))


def has_explicit_time_component(value: str) -> bool:
    return bool(re.search(r"\d{2}:\d{2}(?::\d{2})?", value))


def to_utc_iso_z_for_report(
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


def normalize_report_date_range_to_utc(
    date_range_str: str,
    user_time_zone: Optional[str]
) -> Tuple[str, str]:
    """
    1) Parse start/end from date_range.
    2) If time is missing:
       - start gets 00:00:00
       - end gets 23:59:59
       - when same date, enforce those boundaries.
    3) Convert both to UTC Z format.
    """
    start_raw, end_raw = parse_date_range(date_range_str)
    user_tz = parse_user_utc_offset(user_time_zone)

    start_value = start_raw
    end_value = end_raw

    if not has_explicit_time_component(start_value):
        start_value = f"{start_value} 00:00:00"
    if not has_explicit_time_component(end_value):
        end_value = f"{end_value} 23:59:59"

    try:
        start_day = dtparser.parse(start_raw).date()
        end_day = dtparser.parse(end_raw).date()
        if start_day == end_day:
            start_value = f"{start_day.isoformat()} 00:00:00"
            end_value = f"{end_day.isoformat()} 23:59:59"
    except Exception:
        pass

    start_utc = to_utc_iso_z_for_report(start_value, user_tz=user_tz)
    end_utc = to_utc_iso_z_for_report(end_value, user_tz=user_tz)
    return start_utc, end_utc


# ================================
# Duty Hour date range (duty window + on/off duty)
# ================================
# Default local wall-clock duty window: 10:00 AM -> 7:00 PM. on-duty = the window
# itself; off-duty = its complement, so the start/end times are swapped.
DUTY_DEFAULT_START_TIME = "10:00"
DUTY_DEFAULT_END_TIME = "19:00"


def _parse_time_of_day(value: Optional[str], default: str) -> str:
    """Parse a wall-clock time ('10:00', '7:00 PM', '19:00') to 'HH:MM:SS'.
    Falls back to `default` when missing/unparseable."""
    raw = (value or "").strip()
    for candidate in (raw, default):
        if not candidate:
            continue
        try:
            return dtparser.parse(candidate).strftime("%H:%M:%S")
        except Exception:
            continue
    return "00:00:00"


def is_off_duty(duty_type: Optional[str]) -> bool:
    """True when the user asked for an OFF-duty report (default is on-duty)."""
    norm = (duty_type or "on").strip().lower().replace("-", " ").replace("_", " ")
    return norm in ("off", "off duty", "offduty")


def normalize_duty_hour_range_to_utc(
    date_range_str: str,
    user_time_zone: Optional[str],
    duty_type: Optional[str] = None,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
) -> Tuple[str, str]:
    """
    Build the Duty Hour report's UTC start/end from the date range + duty window.

    Defaults: on-duty, 10:00 -> 19:00 local. The window's time-of-day is applied to
    the start/end DATES (any time inside date_range is ignored), then converted to UTC
    using the user's timezone — server-side, never the agent.
      - ON  duty: start = start_date @ start_time, end = end_date @ end_time
      - OFF duty: start = start_date @ end_time,   end = end_date @ start_time  (complement)
    """
    start_raw, end_raw = parse_date_range(date_range_str)
    user_tz = parse_user_utc_offset(user_time_zone)
    start_day = dtparser.parse(start_raw).date()
    end_day = dtparser.parse(end_raw).date()

    st = _parse_time_of_day(start_time, DUTY_DEFAULT_START_TIME)
    et = _parse_time_of_day(end_time, DUTY_DEFAULT_END_TIME)

    if is_off_duty(duty_type):
        local_start = f"{start_day.isoformat()} {et}"
        local_end = f"{end_day.isoformat()} {st}"
    else:
        local_start = f"{start_day.isoformat()} {st}"
        local_end = f"{end_day.isoformat()} {et}"

    start_utc = to_utc_iso_z_for_report(local_start, user_tz=user_tz)
    end_utc = to_utc_iso_z_for_report(local_end, user_tz=user_tz)
    return start_utc, end_utc


# ================================
# Report payload dedupe
# ================================
def dedupe_items_by_date_asset_id(items: List[Any]) -> List[Any]:
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


def dedupe_report_api_response(api_response: Any) -> Any:
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
        data_wrapper["items"] = dedupe_items_by_date_asset_id(data_wrapper["items"])

    nested_data = data_wrapper.get("data")
    if isinstance(nested_data, dict) and isinstance(nested_data.get("items"), list):
        nested_data["items"] = dedupe_items_by_date_asset_id(nested_data["items"])
    elif isinstance(nested_data, list):
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


# ================================
# Report request processing
# ================================
# Customer-specific report variants that hit the SAME backend API Type as a standard
# report, but carry a distinct report_type so the FE can render the variant view.
# The agent requests e.g. "IdlingKeyrent"; the API still receives Type="Idling".
_API_TYPE_ALIASES: Dict[str, str] = {
    "IdlingKeyrent": "Idling",
    "OverspeedingKeyrent": "Overspeeding",
}


async def process_report_request(
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
        resolved_assets = query_result.get("asset_imeis") if report_type == "Wasl" else query_result.get("asset_ids")
        if query_result["success"] and resolved_assets:
            asset_ids = ",".join(resolved_assets)
    elif pre_req.group_names:
        query_result = mongo_handler.get_asset_ids_by_group_names(
            db_name,
            pre_req.group_names,
            sub_tenant_id=resolved_sub_tenant_id
        )
        result["mongodb_query_result"] = query_result
        resolved_assets = query_result.get("asset_imeis") if report_type == "Wasl" else query_result.get("asset_ids")
        if query_result["success"] and resolved_assets:
            asset_ids = ",".join(resolved_assets)

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
        if report_type == "DutyHour":
            # Duty Hour applies a duty-time window (default 10:00-19:00) with an
            # on/off-duty swap, instead of the generic 00:00:00 / 23:59:59 boundaries.
            start_date, end_date = normalize_duty_hour_range_to_utc(
                pre_req.date_range,
                user_time_zone,
                duty_type=pre_req.duty_type,
                start_time=pre_req.duty_start_time,
                end_time=pre_req.duty_end_time,
            )
        else:
            start_date, end_date = normalize_report_date_range_to_utc(
                pre_req.date_range,
                user_time_zone
            )

    iana_tz = offset_to_iana_timezone(user_time_zone)

    if report_type == "Trip":
        if asset_ids and start_date and end_date:
            result["api_response"] = await api_handler.fetch_trip_report(
                asset_ids, start_date, end_date, time_zone=iana_tz
            )
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
    elif report_type == "FuelSummary":
        if asset_ids and start_date and end_date:
            result["api_response"] = await api_handler.fetch_fuel_summary(asset_ids, start_date, end_date)
    elif report_type == "DutyHour":
        if asset_ids and start_date and end_date:
            result["api_response"] = await api_handler.fetch_duty_hour_report(
                asset_ids, start_date, end_date, time_zone=iana_tz
            )
    elif report_type == "AlertHistory":
        if asset_ids and start_date and end_date:
            result["api_response"] = await api_handler.fetch_alerts_history_report(
                asset_ids, start_date, end_date
            )
    elif report_type in ("DriverBehaviour", "DrivingBehaviour", "DriverBehavior"):
        if driver_ids and start_date and end_date:
            result["api_response"] = await api_handler.fetch_generic_report(
                report_type, driver_ids=driver_ids, start_date=start_date, end_date=end_date,
                time_zone=iana_tz,
            )
    else:
        # Generic /fetch-dates reports (Type-based). Keyrent variants share a standard
        # backend Type but keep their distinct report_type in the returned payload.
        api_type = _API_TYPE_ALIASES.get(report_type, report_type)
        if asset_ids and start_date and end_date:
            result["api_response"] = await api_handler.fetch_generic_report(
                api_type, asset_ids=asset_ids, start_date=start_date, end_date=end_date,
                time_zone=iana_tz,
            )

    result["api_response"] = dedupe_report_api_response(result.get("api_response"))
    if start_date and end_date and result.get("api_response") is not None:
        result["start_datetime"] = start_date
        result["end_datetime"] = end_date
    return result


def report_outcome_status(api_response: Any, mongodb_query_result: Any) -> str:
    """
    Classify a processed report result. Mirrors the empty/failure detection in
    the legacy /chat handler so callers can decide whether to return a
    structured payload or fall back to a natural-language message.

    Returns one of: "data", "empty", "failure", "not_found".
    """
    is_failure = (
        isinstance(api_response, dict)
        and api_response.get("success") is False
    )
    is_not_found = (
        api_response is None
        and isinstance(mongodb_query_result, dict)
        and mongodb_query_result.get("success") is True
        and (
            ("asset_ids" in mongodb_query_result and len(mongodb_query_result.get("asset_ids") or []) == 0)
            or ("driver_ids" in mongodb_query_result and len(mongodb_query_result.get("driver_ids") or []) == 0)
        )
    )

    data_wrapper = api_response.get("data") if isinstance(api_response, dict) else None
    nested_data = data_wrapper.get("data") if isinstance(data_wrapper, dict) else None
    is_empty = False
    if isinstance(data_wrapper, dict) and isinstance(data_wrapper.get("items"), list):
        is_empty = len(data_wrapper.get("items")) == 0
    elif isinstance(nested_data, dict) and isinstance(nested_data.get("items"), list):
        is_empty = len(nested_data.get("items")) == 0
    elif isinstance(nested_data, list):
        is_empty = len(nested_data) == 0

    if is_failure:
        return "failure"
    if is_not_found:
        return "not_found"
    if is_empty:
        return "empty"
    return "data"
