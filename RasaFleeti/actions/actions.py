from __future__ import annotations

import json
import logging
import re
import calendar
from datetime import datetime, date, timedelta
from typing import Any, Dict, List, Optional, Text
import dateparser
import requests
from dateparser.search import search_dates
from pymongo import MongoClient
from rasa_sdk import Action, FormValidationAction, Tracker
from rasa_sdk.events import EventType, SlotSet, ActiveLoop
from rasa_sdk.executor import CollectingDispatcher

logger = logging.getLogger(__name__)

BASE_URL = "https://dev-test.dev-iot.tracking.me"
TRIP_REPORT_ENDPOINT = "/api/admin/reports/trip"
FLEET_SUMMARY_ENDPOINT = "/api/admin/reports/fleet-summary"
FLEET_PERFORMANCE_ENDPOINT = "/api/admin/reports/fleet-performance"
FUEL_CONSUMPTION_ENDPOINT = "/api/admin/reports/fuel-consumption"
ODOMETER_REPORT_ENDPOINT = "/api/admin/reports/odometer"
UTILIZATION_REPORT_ENDPOINT = "/api/admin/reports/utilization"
IDLE_REPORT_ENDPOINT = "/api/admin/reports/idling"
STOP_REPORT_ENDPOINT = "/api/admin/reports/stop-time"
RAW_DATA_REPORT_ENDPOINT = "/api/admin/reports/raw-data"
TRACK_DATA_REPORT_ENDPOINT = "/api/admin/reports/raw-track-data"
OVER_SPEEDING_REPORT_ENDPOINT = "/api/admin/reports/over-speeding"
TEMPERATURE_HUMIDITY_REPORT_ENDPOINT = "/api/admin/reports/temperature-humidity"
WEIGHT_SENSOR_REPORT_ENDPOINT = "/api/admin/reports/weight-sensor"
COMMANDS_HISTORY_REPORT_ENDPOINT = "/api/admin/reports/command-history"
EVENTS_REPORT_ENDPOINT = "/api/admin/reports/event"
DRIVER_BEHAVIOR_REPORT_ENDPOINT = "/api/admin/reports/driver-behaviour"

AUTHORIZATION = (    
    "Bearer "
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJodHRwOi8vc2NoZW1hcy54bWxzb2FwLm9yZy93cy8yMDA1LzA1L2lkZW50aXR5L2NsYWltcy9uYW1laWRlbnRpZmllciI6ImZiODM1ZWJkLTkyOTktNGRhNC04Y2IxLTllY2VhM2E5YzVkNyIsImh0dHA6Ly9zY2hlbWFzLnhtbHNvYXAub3JnL3dzLzIwMDUvMDUvaWRlbnRpdHkvY2xhaW1zL2VtYWlsYWRkcmVzcyI6Imsuc2hhZmlxdWVAdHJhY2tpaW5nLm1lIiwiaHR0cDovL3NjaGVtYXMueG1sc29hcC5vcmcvd3MvMjAwNS8wNS9pZGVudGl0eS9jbGFpbXMvbmFtZSI6IkRldlRlc3QiLCJTZWN1cml0eVN0YW1wIjoiQU5GNTQ1M0tPT0tJWVVWRTNVTUk0TkJFRkJNQlVNS1giLCJodHRwOi8vc2NoZW1hcy5taWNyb3NvZnQuY29tL3dzLzIwMDgvMDYvaWRlbnRpdHkvY2xhaW1zL3JvbGUiOiJBZG1pbiIsImV4cCI6MTc2NjIyODA5MiwiaXNzIjoiaHR0cHM6Ly9sb2NhbGhvc3Q6NzA0Ni8iLCJhdWQiOiJodHRwOi8vbG9jYWxob3N0OjMwMDAvIn0.5UvG39caaJN6rCuf4GSk-7RB08_sqKWJi5vNVFUWzlo"
)
MONGO_URI = "mongodb://wajeeha:Start123987%2B@10.190.9.35:27017/?directConnection=true"
MONGO_DB = "dev-test"
MONGO_COLLECTION = "Asset"
SUB_TENANT_ID = ""
REPORT_PAGE = 1
REPORT_SIZE = 71

REPORT_SPECS: Dict[Text, Dict[str, bool]] = {
    "trips statistics report": {"requires_assets": True, "requires_dates": True},
    "idle time report": {"requires_assets": True, "requires_dates": True},
    "stop time report": {"requires_assets": True, "requires_dates": True},
    "odometer report": {"requires_assets": True, "requires_dates": True},
    "fuel trip consumption report": {"requires_assets": True, "requires_dates": True},
    # Fleet summary is a tenant-wide report; it does not require specific
    # assets or dates.
    "fleet summary report": {"requires_assets": False, "requires_dates": False},
    # Fleet performance summary is date-based but not asset-specific.
    "fleet performance summary report": {"requires_assets": False, "requires_dates": True},
    # Utilization report is date-based but not asset-specific.
    "utilization report": {"requires_assets": False, "requires_dates": True},
    # Raw data report requires both assets and dates
    "raw data report": {"requires_assets": True, "requires_dates": True},
    # Track data report requires both assets and dates
    "track data report": {"requires_assets": True, "requires_dates": True},
    # Over speeding report requires both assets and dates
    "over speeding report": {"requires_assets": True, "requires_dates": True},
    # Driver behavior report requires driver and dates
    "driver behavior report": {"requires_assets": False, "requires_dates": True, "requires_driver": True},
    # Temperature & humidity report requires both assets and dates
    "temperature & humidity report": {"requires_assets": True, "requires_dates": True},
    # Weight sensor report requires both assets and dates
    "weight sensor report": {"requires_assets": True, "requires_dates": True},
    # Commands history report requires both assets and dates
    "commands history report": {"requires_assets": True, "requires_dates": True},
    # Events report requires both assets and dates
    "events report": {"requires_assets": True, "requires_dates": True},
}

ASSET_SPLIT_REGEX = re.compile(r"[,/&]|\band\b", re.IGNORECASE)
# Keep letters, digits, hyphens, and spaces so plates like "3688 FHD" are preserved.
ASSET_CLEAN_REGEX = re.compile(r"[^A-Za-z0-9\- ]")
DATE_LIKE_REGEX = re.compile(r"^(?:\d{4}|\d{2}-\d{2}|\d{2}-\d{2}-\d{4}|\d{4}-\d{2}-\d{2})$")
ASSET_GUESS_REGEX = re.compile(r"[A-Za-z0-9]{2,}(?:[ -][A-Za-z0-9]{1,})*")


def call_date_based_api(
    endpoint: str,
    start_date: str,
    end_date: Optional[str] = None,
    page: int = 1,
    size: int = 10,
    extra_payload: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Call a date-based API endpoint with the given parameters.
    
    Args:
        endpoint: The API endpoint to call
        start_date: Start date in YYYY-MM-DD format
        end_date: End date in YYYY-MM-DD format (defaults to start_date)
        page: Page number for pagination
        size: Number of items per page
        
    Returns:
        Dictionary containing the API response or error information
    """
    def to_iso_timestamp(dt_str: str, is_end: bool = False) -> str:
        """Convert YYYY-MM-DD to ISO 8601 timestamp with time component."""
        try:
            if "T" in dt_str:
                return dt_str
            dt = datetime.strptime(dt_str, "%Y-%m-%d")
            if is_end:
                return f"{dt.strftime('%Y-%m-%d')}T23:59:59.999Z"
            return f"{dt.strftime('%Y-%m-%d')}T00:00:00.000Z"
        except ValueError:
            return dt_str

    url = f"{BASE_URL}{endpoint}"
    payload: Dict[str, Any] = {
        "page": page,
        "size": size,
        "startDate": to_iso_timestamp(start_date, False),
        "endDate": to_iso_timestamp(end_date or start_date, True),
    }
    if extra_payload:
        payload.update(extra_payload)
    
    headers = {
        "Authorization": AUTHORIZATION,
        "Content-Type": "application/json"
    }
    
    try:
        response = requests.post(url, json=payload, headers=headers, timeout=60)
        response.raise_for_status()
        return {
            "status": response.status_code,
            "body": response.json() if response.content else {}
        }
    except requests.RequestException as exc:
        logger.error("API call to %s failed: %s", endpoint, exc)
        return {"error": str(exc)}



def plate_variations(plate: Text) -> List[Text]:
    normalized = re.sub(r"\s+", " ", plate.strip().upper())
    variants = {
        normalized,
        normalized.replace(" ", ""),
        normalized.replace(" ", "-"),
        normalized.replace("-", ""),
        normalized.replace("-", " "),
    }
    return [v for v in variants if v]


def normalize_spaces(text: Optional[Text]) -> Optional[Text]:
    """Normalize multiple spaces to single space in text.
    
    This function uses split() and join() to normalize all whitespace
    (spaces, tabs, newlines) to single spaces.
    
    Args:
        text: The text to normalize, can be None
        
    Returns:
        Normalized text with single spaces, or None if input was None
    """
    if not text:
        return text
    return " ".join(str(text).split())


def normalize_input(tracker: Tracker) -> None:
    """Normalize multiple spaces in the latest user message and its entities.
    
    This should be called at the very start of any validation function
    to ensure all processing works with normalized text (single spaces only).
    
    Args:
        tracker: The Rasa tracker containing the latest message
    """
    latest = tracker.latest_message or {}
    text = latest.get("text") or ""
    
    if text:
        # Normalize the text using split() and join()
        normalized_text = normalize_spaces(text)
        if normalized_text != text:
            latest["text"] = normalized_text
            
            # Also normalize entity values
            entities = latest.get("entities") or []
            for entity in entities:
                entity_value = entity.get("value")
                if entity_value:
                    normalized_value = normalize_spaces(entity_value)
                    if normalized_value != entity_value:
                        entity["value"] = normalized_value


def normalise_report_type(value: Optional[Text]) -> Optional[Text]:
    if not value:
        return None
    text = value.lower().strip()
    if text in REPORT_SPECS:
        return text
    
    # Trips statistics report - handle "trips" alone, "trip", "trips report", etc.
    # Check for trips-related terms (must come before fleet checks to avoid conflicts)
    if text in ["trips", "trip"]:
        return "trips statistics report"
    if ("trip" in text or "trips" in text) and ("report" in text or "stat" in text or "statistics" in text or "data" in text):
        return "trips statistics report"
    
    # Fleet performance summary report - must check before fleet summary
    if "fleet" in text and "performance" in text:
        if "summary" in text or "stats" in text or "statistics" in text:
            return "fleet performance summary report"
        # "fleet performance" alone or "fleet performance report"
        return "fleet performance summary report"
    if "performance" in text and ("summary" in text or "stats" in text) and "fleet" not in text:
        # Just "performance report" or "performance summary" - could be fleet performance
        return "fleet performance summary report"
    
    # Fleet summary report - check after fleet performance
    if "fleet" in text and ("summary" in text or "overview" in text):
        return "fleet summary report"
    if text in ["summary report", "fleet overview"]:
        return "fleet summary report"
    
    # Fuel trip consumption report
    if "fuel" in text:
        if "consumption" in text or "usage" in text or "trip" in text:
            return "fuel trip consumption report"
        if "report" in text:
            return "fuel trip consumption report"
        # Just "fuel" or "fuel report"
        return "fuel trip consumption report"
    if "consumption" in text and "fuel" not in text:
        # Just "consumption report" - likely fuel
        return "fuel trip consumption report"
    
    # Odometer report
    if "odometer" in text or "mileage" in text or text == "distance report":
        return "odometer report"
    
    # Idle time report
    if "idle" in text or "idling" in text:
        return "idle time report"
    
    # Stop time report
    if "stop" in text or "stoppage" in text:
        return "stop time report"
    
    # Utilization report
    if "utilization" in text or "utilisation" in text:
        return "utilization report"
    if ("work" in text and ("hour" in text or "hours" in text or "time" in text)) or text in ["usage report", "usage hours"]:
        return "utilization report"
    
    # Raw data report
    if "raw" in text and ("data" in text or "report" in text or "information" in text or "export" in text):
        return "raw data report"
    
    # Track data report
    if ("track" in text and "data" in text) or ("tracking" in text and "data" in text):
        return "track data report"
    if ("all" in text and "parameter" in text) or ("parameter" in text and "report" in text):
        return "track data report"
    if "gps" in text and "data" in text:
        return "track data report"
    if "location" in text and "data" in text:
        return "track data report"
    if text in ["track data", "tracking report", "track information", "all data report"]:
        return "track data report"
    
    # Over speeding report
    if ("over" in text and "speed" in text) or "speeding" in text:
        return "over speeding report"
    if "speed" in text and ("violation" in text or "violations" in text):
        return "over speeding report"
    if text == "speed report":
        return "over speeding report"
    
    # Temperature & humidity report
    if ("temperature" in text or "temp" in text) and "humidity" in text:
        return "temperature & humidity report"
    if text in ["temperature report", "humidity report", "climate report", "environmental report"]:
        return "temperature & humidity report"
    if "temp" in text and "humidity" in text:
        return "temperature & humidity report"
    
    # Weight sensor report
    if "weight" in text and "sensor" in text:
        return "weight sensor report"
    if text in ["weight report", "load sensor report", "weight data report", "sensor report"]:
        return "weight sensor report"
    
    # Driver behavior report
    if "driver" in text and ("behavior" in text or "behaviour" in text or "performance" in text):
        return "driver behavior report"
    if text in ["behavior report", "behaviour report", "driver report"]:
        return "driver behavior report"
    
    # Commands history report
    if "command" in text and ("history" in text or "log" in text):
        return "commands history report"
    if text in ["commands report", "command report"]:
        return "commands history report"
    
    # Events report
    if "event" in text and ("report" in text or "log" in text or "history" in text):
        return "events report"
    if text in ["events", "activity report", "activities report"]:
        return "events report"
    
    return None


def extract_assets(raw_value: Any) -> List[Text]:
    if raw_value is None:
        return []
    if isinstance(raw_value, list):
        # If it's a list, we still need to split items that contain "and" or other separators
        raw_items = []
        for item in raw_value:
            item_str = str(item)
            # Normalize spaces before processing
            item_str = normalize_spaces(item_str) or ""
            # Split items that contain separators
            split_items = ASSET_SPLIT_REGEX.split(item_str)
            raw_items.extend(split_items)
    else:
        raw_str = str(raw_value)
        # Normalize spaces before processing
        raw_str = normalize_spaces(raw_str) or ""
        raw_items = ASSET_SPLIT_REGEX.split(raw_str)
    assets: List[Text] = []
    for item in raw_items:
        item_str = str(item).strip()
        if not item_str:
            continue
            
        # First, remove date-related content that might be attached to the asset
        # This handles cases like "390 and vehicle 3688 fhd from 1 sep to 30 sep"
        # We want to stop at words like "from", "to", "between", etc.
        date_stop_pattern = re.compile(r'\s+(from|to|between|on|for|of)\s+', re.IGNORECASE)
        if date_stop_pattern.search(item_str):
            # Split on date stop words first, take only the part before the date
            item_str = date_stop_pattern.split(item_str)[0].strip()
            if not item_str:
                continue
        
        # Remove "vehicle" word (case-insensitive) before processing
        item_str = re.sub(r'\bvehicle\b', '', item_str, flags=re.IGNORECASE).strip()
        if not item_str:
            continue
        
        cleaned = ASSET_CLEAN_REGEX.sub("", item_str).upper().strip()
        if not cleaned:
            continue
        
        # Skip if the cleaned result is just "AND" or other connector words
        if cleaned in {"AND", "OR", "&"} or len(cleaned) < 2:
            continue

        # If the text clearly contains extra words like a date range or month
        # description, keep only the first two tokens which usually correspond
        # to the plate (e.g. "3688 FHD FROM 1 SEP TO 30 SEP" or
        # "3688 FHD OF SEPTEMBER MONTH" -> "3688 FHD").
        tokens = cleaned.split()
        if len(tokens) > 2:
            month_tokens = {
                "JAN",
                "JANUARY",
                "FEB",
                "FEBRUARY",
                "MAR",
                "MARCH",
                "APR",
                "APRIL",
                "MAY",
                "JUN",
                "JUNE",
                "JUL",
                "JULY",
                "AUG",
                "AUGUST",
                "SEP",
                "SEPT",
                "SEPTEMBER",
                "OCT",
                "OCTOBER",
                "NOV",
                "NOVEMBER",
                "DEC",
                "DECEMBER",
                "MONTH",
                "YESTERDAY",
                "TODAY",
                "WEEK",
                "WEEKS",
                "YEAR",
                "YEARS",
                "DAY",
                "DAYS",
            }
            # Tokens that clearly indicate the text is adding a date/range
            # after the plate. We include "ON" so that phrases like
            # "3688 FHD ON 7/10/2025" are reduced back to just "3688 FHD".
            trigger_tokens = {"FROM", "TO", "BETWEEN", "OF", "ON"} | month_tokens

            # If the phrase clearly starts with a 4-digit year and also
            # contains month/date-like tokens, treat it as a date fragment,
            # not as a plate at all.
            first = tokens[0]
            if first.isdigit() and len(first) == 4 and any(
                t in trigger_tokens for t in tokens[1:]
            ):
                continue

            # If the phrase looks like a leading day + month (e.g. "22 SEPTEMBER")
            # then this is almost certainly part of a date, not a plate; skip it.
            if first.isdigit() and 1 <= len(first) <= 2 and len(tokens) >= 2 and tokens[1] in month_tokens:
                continue

            if any(t in trigger_tokens for t in tokens[2:]):
                cleaned = " ".join(tokens[:2])

        # Additional normalization for cases like "390 FOR LAST YEAR 2024" or
        # "390 VEHICLE" where the first token is the actual numeric plate and
        # the rest are contextual words, and also cases like "2025 FOR 390"
        # or "JUNE 20TH 2025 FOR VEHICLE 390" where a leading date/year and
        # context precede the real plate. We keep the plate number only.
        tokens = cleaned.split()
        if tokens:
            # If the word VEHICLE is present, restrict the candidate span to
            # what comes after VEHICLE, so that a phrase like
            # "JUNE 20TH 2025 FOR VEHICLE 390" becomes just "390" (and then
            # goes through the numeric/context rules below).
            if "VEHICLE" in tokens:
                veh_idx = tokens.index("VEHICLE")
                if veh_idx < len(tokens) - 1:
                    cleaned = " ".join(tokens[veh_idx + 1 :])
                    tokens = cleaned.split()

            if not tokens:
                continue

            first_token = tokens[0]

            # If the phrase starts with a year and later contains another
            # numeric token, treat the trailing numeric token as the plate, e.g.
            # "2025 FOR 390" -> "390".
            if first_token.isdigit() and len(first_token) == 4 and len(tokens) >= 3:
                plate_candidate: Optional[str] = None
                for t in reversed(tokens[1:]):
                    if t.isdigit() and len(t) >= 2 and t != first_token:
                        plate_candidate = t
                        break
                if plate_candidate:
                    cleaned = plate_candidate
                    tokens = [cleaned]
                    first_token = cleaned

            # If the phrase starts with a numeric token and contains any
            # time/date related words afterwards, reduce it to just the
            # numeric plate (e.g. "390 FOR LAST YEAR 2024" -> "390").
            time_words = {
                "LAST",
                "THIS",
                "YEAR",
                "YEARS",
                "MONTH",
                "MONTHS",
                "WEEK",
                "WEEKS",
                "DAY",
                "DAYS",
                "TODAY",
                "YESTERDAY",
                "FROM",
                "TO",
                "BETWEEN",
            }
            if first_token.isdigit() and any(t in time_words for t in tokens[1:]):
                cleaned = first_token
            else:
                # If we have exactly two tokens and the second one is a
                # generic context word like VEHICLE or FOR, also reduce it
                # to just the numeric plate (e.g. "390 VEHICLE" -> "390").
                context_words = {
                    "VEHICLE",
                    "CAR",
                    "TRUCK",
                    "BUS",
                    "PLATE",
                    "FOR",
                    "OF",
                    "TIME",
                    "PERIOD",
                    "RANGE",
                }
                if (
                    len(tokens) == 2
                    and first_token.isdigit()
                    and tokens[1] in context_words
                ):
                    cleaned = first_token

        # Skip values that look like pure dates or years, to avoid treating them as plates.
        # But be careful: 4-digit numbers could be vehicle plates (like "1010") or years (like "2024")
        # Only skip if it's clearly a year (1900-2100 range) or matches date patterns with separators
        if DATE_LIKE_REGEX.match(cleaned):
            # Check if it's a 4-digit number - could be a year or a plate number
            if re.match(r'^\d{4}$', cleaned):
                # If it's a 4-digit number, check if it's in a reasonable year range
                # Years are typically 1900-2100, vehicle plates can be any 4 digits
                year_value = int(cleaned)
                if 1900 <= year_value <= 2100:
                    # This looks like a year, skip it
                    continue
                # Otherwise, it's likely a vehicle plate number (like "1010"), accept it
            else:
                # It matches other date patterns (with dashes), skip it
                continue
        
        # Skip if the cleaned result is too short (less than 2 characters) or is just a connector word
        if len(cleaned) < 2 or cleaned in {"AND", "OR", "&"}:
            continue
        
        # Handle cases where "AND" appears at the end (e.g., "390 AND")
        if cleaned.endswith(" AND"):
            cleaned = cleaned[:-4].strip()
            if not cleaned or len(cleaned) < 2:
                continue
        
        # Also handle cases where "AND" appears in the middle and we want to split it
        # But only if it looks like it's connecting two assets
        if " AND " in cleaned:
            # If it contains " AND " in the middle, this might be two assets
            # But we've already split on "and" earlier, so this shouldn't happen
            # However, if it does, we'll take the first part
            parts = cleaned.split(" AND ", 1)
            if parts and parts[0].strip():
                cleaned = parts[0].strip()
            else:
                continue

        assets.append(cleaned)

    # De-duplicate while preserving order and filter out invalid assets
    # Also remove assets that are substrings of other assets (e.g., "FHD" is part of "3688 FHD")
    deduped: List[Text] = []
    
    # First pass: collect all valid assets
    valid_assets = []
    for a in assets:
        # Skip if it's just "AND" or other invalid patterns
        if a in {"AND", "OR", "&"} or len(a) < 2:
            continue
        valid_assets.append(a)
    
    # Second pass: remove assets that are substrings of other assets
    # Sort by length (longest first) to prefer more complete assets
    valid_assets_sorted = sorted(valid_assets, key=lambda x: len(x), reverse=True)
    
    for a in valid_assets_sorted:
        # Check if this asset is already covered by a longer asset
        is_substring = False
        a_upper = a.upper()
        
        for existing in deduped:
            existing_upper = existing.upper()
            
            # If 'a' is exactly equal to 'existing', skip (exact duplicate)
            if a_upper == existing_upper:
                is_substring = True
                break
            
            # Check if 'a' is a complete token in 'existing'
            # e.g., "FHD" should match in "3688 FHD" but not in "FHD123"
            existing_tokens = existing_upper.split()
            if a_upper in existing_tokens:
                # 'a' is a token within 'existing', so skip it
                is_substring = True
                break
            
            # Check if 'a' appears at the start of 'existing' (e.g., "3688" at start of "3688 FHD")
            if existing_upper.startswith(a_upper + " "):
                is_substring = True
                break
            
            # Check if 'a' appears at the end of 'existing' (e.g., "FHD" at end of "3688 FHD")
            if existing_upper.endswith(" " + a_upper) or existing_upper == a_upper:
                is_substring = True
                break
        
        if not is_substring:
            deduped.append(a)
    
    return deduped


def call_fleet_summary_api() -> Dict[Text, Any]:
    """Call the fleet summary endpoint.

    This report is tenant-wide and does not require asset or date filters.
    """
    url = f"{BASE_URL}{FLEET_SUMMARY_ENDPOINT}"
    payload: Dict[Text, Any] = {}
    headers = {
        "Authorization": AUTHORIZATION,
        "Content-Type": "application/json",
    }
    try:
        response = requests.get(url, json=payload, headers=headers, timeout=60)
        response.raise_for_status()
        try:
            body: Any = response.json()
        except ValueError:
            body = response.text
        return {"status": response.status_code, "body": body}
    except requests.RequestException as exc:
        logger.error("Fleet summary API failed: %s", exc)
        return {"error": str(exc)}


def call_fleet_performance_api(start_date: Text, end_date: Text) -> Dict[Text, Any]:
    """Call the fleet performance summary endpoint with pagination and error handling.
    
    This function handles large result sets by:
    1. Using smaller page sizes
    2. Automatically retrying with smaller batches
    3. Splitting date ranges when needed
    """
    
    def to_full_day(dt_str: Text, is_end: bool) -> Text:
        """Convert YYYY-MM-DD into a full-day UTC timestamp."""
        if "T" in dt_str:
            # If already in ISO format with time, ensure it has milliseconds and Z
            if dt_str.endswith("Z"):
                if "." in dt_str:
                    # Already has milliseconds, ensure 3 decimal places
                    parts = dt_str.split(".")
                    if len(parts) == 2:
                        millis = parts[1].rstrip("Z")
                        if len(millis) > 3:
                            millis = millis[:3]
                        elif len(millis) < 3:
                            millis = millis.ljust(3, '0')
                        return f"{parts[0]}.{millis}Z"
                else:
                    # No milliseconds, add them
                    return dt_str.replace("Z", ".000Z")
            return dt_str
            
        try:
            d = datetime.strptime(dt_str, "%Y-%m-%d").date()
        except ValueError:
            return dt_str
            
        if is_end:
            return f"{d.isoformat()}T23:59:59.999Z"
        return f"{d.isoformat()}T00:00:00.000Z"

    url = f"{BASE_URL}{FLEET_PERFORMANCE_ENDPOINT}"
    start_date_iso = to_full_day(start_date, is_end=False)
    end_date_iso = to_full_day(end_date, is_end=True)
    
    # Try with a smaller page size first
    payload = {
        "page": 1,
        "size": 5,  # Reduced from 10 to 5
        "startDate": start_date_iso,
        "endDate": end_date_iso
    }
    
    headers = {
        "Authorization": AUTHORIZATION,
        "Content-Type": "application/json",
        "Accept": "application/json"
    }
    
    try:
        logger.info(f"Calling fleet performance API with payload: {json.dumps(payload)}")
        response = requests.post(
            url,
            json=payload,
            headers=headers,
            timeout=120  # Increased timeout
        )
        
        if response.status_code == 200:
            try:
                return {
                    "status": response.status_code,
                    "body": response.json(),
                    "pagination": {
                        "page": payload["page"],
                        "size": payload["size"]
                    }
                }
            except ValueError:
                return {
                    "status": response.status_code,
                    "body": response.text,
                    "pagination": {
                        "page": payload["page"],
                        "size": payload["size"]
                    }
                }
        
        # If we get a 400, try with an even smaller page size
        if response.status_code == 400 and "exceeds 104857600 bytes" in response.text:
            payload["size"] = 3  # Try with even smaller page size
            logger.info(f"Retrying with smaller page size: {payload}")
            response = requests.post(url, json=payload, headers=headers, timeout=120)
            
            if response.status_code == 200:
                try:
                    return {
                        "status": response.status_code,
                        "body": response.json(),
                        "pagination": {
                            "page": payload["page"],
                            "size": payload["size"]
                        }
                    }
                except ValueError:
                    return {
                        "status": response.status_code,
                        "body": response.text,
                        "pagination": {
                            "page": payload["page"],
                            "size": payload["size"]
                        }
                    }
        
        # If we still get an error, try splitting the date range
        if response.status_code == 400:
            # Split the date range in half and try again
            try:
                # Parse the start and end dates
                start = datetime.strptime(start_date_iso.replace("Z", ""), "%Y-%m-%dT%H:%M:%S.%f") if "." in start_date_iso else datetime.strptime(start_date_iso.replace("Z", ""), "%Y-%m-%dT%H:%M:%S")
                end = datetime.strptime(end_date_iso.replace("Z", ""), "%Y-%m-%dT%H:%M:%S.%f") if "." in end_date_iso else datetime.strptime(end_date_iso.replace("Z", ""), "%Y-%m-%dT%H:%M:%S")
                
                # Calculate midpoint and format it correctly
                mid_date = start + (end - start) / 2
                mid_date_str = mid_date.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
                
                logger.info(f"Splitting date range: {start_date_iso} to {end_date_iso}")
                
                # First half
                result1 = call_fleet_performance_api(
                    start_date_iso,
                    mid_date_str
                )
                
                # Second half
                result2 = call_fleet_performance_api(
                    mid_date_str,
                    end_date_iso
                )
                
                # Combine results if both calls were successful
                if result1.get("status") == 200 and result2.get("status") == 200:
                    combined = {
                        "items": result1.get("body", {}).get("items", []) + 
                                result2.get("body", {}).get("items", []),
                        "totalCount": result1.get("body", {}).get("totalCount", 0) + 
                                     result2.get("body", {}).get("totalCount", 0),
                        "pageNumber": 1,
                        "totalPages": 1,
                        "hasNextPage": False,
                        "hasPreviousPage": False
                    }
                    return {
                        "status": 200,
                        "body": {
                            "success": True,
                            "data": combined,
                            "message": "Combined results from multiple date ranges"
                        }
                    }
                return {
                    "status": 400,
                    "error": f"Failed to retrieve data for split date ranges: {result1.get('error')} | {result2.get('error')}"
                }
                
            except Exception as e:
                return {
                    "status": 500,
                    "error": f"Error processing split date ranges: {str(e)}"
                }
        
        # If all else fails, return the error
        try:
            error_msg = response.json()
        except:
            error_msg = response.text
            
        return {
            "status": response.status_code,
            "error": error_msg
        }
        
    except requests.RequestException as exc:
        logger.error(f"Fleet performance API request failed: {exc}")
        return {
            "status": 500,
            "error": str(exc)
        }


def parse_date_range(text: Optional[Text]) -> Optional[Dict[str, Text]]:
    if not text:
        return None
    # Normalize spaces before processing
    working = normalize_spaces(text) or ""
    if not working:
        return None
    lowered = working.lower()
    today = date.today()

    # Handle date ranges with "and" or "to" between them (e.g., "2 june 2025 and 30 sep 2025")
    # Also handle numeric dates with various separators (dots, dashes, slashes, spaces)
    # Also handle dates without years (e.g., "june 5 to september 22") - will default to current year
    date_range_match = re.search(
        r"(\d{1,2}\s+(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s*\d{0,4}|(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+\d{1,2}\s*\d{0,4}|\d{4}[-/.\s]\d{1,2}[-/.\s]\d{1,2}|\d{1,2}[-/.\s]\d{1,2}[-/.\s]\d{4})"
        r"\s*(?:to|and|,|\s+)\s*"
        r"(\d{1,2}\s+(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s*\d{0,4}|(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+\d{1,2}\s*\d{0,4}|\d{4}[-/.\s]\d{1,2}[-/.\s]\d{1,2}|\d{1,2}[-/.\s]\d{1,2}[-/.\s]\d{4})",
        lowered,
        re.IGNORECASE
    )

    if date_range_match:
        start_date_str = date_range_match.group(1).strip()
        end_date_str = date_range_match.group(2).strip()
        
        # Check if dates are in numeric format (dot, dash, slash, or space-separated) and parse them explicitly
        # Try dot-separated first
        dot_pattern = re.compile(r"(\d{1,2})\.(\d{1,2})\.(\d{4})")
        start_dot = dot_pattern.match(start_date_str)
        end_dot = dot_pattern.match(end_date_str)
        
        if start_dot and end_dot:
            # Parse dot-separated dates explicitly as DD.MM.YYYY format (European format only)
            d1 = int(start_dot.group(1))
            m1 = int(start_dot.group(2))
            y1 = int(start_dot.group(3))
            d2 = int(end_dot.group(1))
            m2 = int(end_dot.group(2))
            y2 = int(end_dot.group(3))
            
            start_date = None
            end_date = None
            
            # Parse as DD.MM.YYYY format (European format only)
            try:
                if 1 <= d1 <= 31 and 1 <= m1 <= 12 and 1 <= d2 <= 31 and 1 <= m2 <= 12:
                    start_date = date(y1, m1, d1)
                    end_date = date(y2, m2, d2)
            except ValueError:
                pass
            
            if start_date and end_date:
                # Ensure start <= end
                if start_date > end_date:
                    start_date, end_date = end_date, start_date
                return {
                    "start": start_date.isoformat(),
                    "end": end_date.isoformat(),
                    "summary": f"{start_date_str} to {end_date_str}"
                }
        
        # Try dash-separated
        dash_pattern = re.compile(r"(\d{1,2})-(\d{1,2})-(\d{4})")
        start_dash = dash_pattern.match(start_date_str)
        end_dash = dash_pattern.match(end_date_str)
        
        if start_dash and end_dash:
            d1 = int(start_dash.group(1))
            m1 = int(start_dash.group(2))
            y1 = int(start_dash.group(3))
            d2 = int(end_dash.group(1))
            m2 = int(end_dash.group(2))
            y2 = int(end_dash.group(3))
            
            start_date = None
            end_date = None
            
            try:
                if 1 <= d1 <= 31 and 1 <= m1 <= 12 and 1 <= d2 <= 31 and 1 <= m2 <= 12:
                    start_date = date(y1, m1, d1)
                    end_date = date(y2, m2, d2)
            except ValueError:
                pass
            
            if start_date and end_date:
                if start_date > end_date:
                    start_date, end_date = end_date, start_date
                return {
                    "start": start_date.isoformat(),
                    "end": end_date.isoformat(),
                    "summary": f"{start_date_str} to {end_date_str}"
                }
        
        # Try slash-separated
        slash_pattern = re.compile(r"(\d{1,2})/(\d{1,2})/(\d{4})")
        start_slash = slash_pattern.match(start_date_str)
        end_slash = slash_pattern.match(end_date_str)
        
        if start_slash and end_slash:
            d1 = int(start_slash.group(1))
            m1 = int(start_slash.group(2))
            y1 = int(start_slash.group(3))
            d2 = int(end_slash.group(1))
            m2 = int(end_slash.group(2))
            y2 = int(end_slash.group(3))
            
            start_date = None
            end_date = None
            
            try:
                if 1 <= d1 <= 31 and 1 <= m1 <= 12 and 1 <= d2 <= 31 and 1 <= m2 <= 12:
                    start_date = date(y1, m1, d1)
                    end_date = date(y2, m2, d2)
            except ValueError:
                pass
            
            if start_date and end_date:
                if start_date > end_date:
                    start_date, end_date = end_date, start_date
                return {
                    "start": start_date.isoformat(),
                    "end": end_date.isoformat(),
                    "summary": f"{start_date_str} to {end_date_str}"
                }
        
        # Try space-separated
        space_pattern = re.compile(r"(\d{1,2})\s+(\d{1,2})\s+(\d{4})")
        start_space = space_pattern.match(start_date_str)
        end_space = space_pattern.match(end_date_str)
        
        if start_space and end_space:
            d1 = int(start_space.group(1))
            m1 = int(start_space.group(2))
            y1 = int(start_space.group(3))
            d2 = int(end_space.group(1))
            m2 = int(end_space.group(2))
            y2 = int(end_space.group(3))
            
            start_date = None
            end_date = None
            
            try:
                if 1 <= d1 <= 31 and 1 <= m1 <= 12 and 1 <= d2 <= 31 and 1 <= m2 <= 12:
                    start_date = date(y1, m1, d1)
                    end_date = date(y2, m2, d2)
            except ValueError:
                pass
            
            if start_date and end_date:
                if start_date > end_date:
                    start_date, end_date = end_date, start_date
                return {
                    "start": start_date.isoformat(),
                    "end": end_date.isoformat(),
                    "summary": f"{start_date_str} to {end_date_str}"
                }
        
        # Parse the dates using dateparser for other formats
        # Check if dates have years, if not, default to current year
        start_has_year = bool(re.search(r'\d{4}', start_date_str))
        end_has_year = bool(re.search(r'\d{4}', end_date_str))
        
        # If no year in start date, add current year
        if not start_has_year:
            # Try to insert year after month name or day
            # Handle formats like "5 june" or "june 5"
            if re.search(r'\d{1,2}\s+(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)', start_date_str, re.IGNORECASE):
                # Format: "5 june" -> "5 june 2025"
                start_date_str = f"{start_date_str} {today.year}"
            elif re.search(r'(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\s+\d{1,2}', start_date_str, re.IGNORECASE):
                # Format: "june 5" -> "june 5 2025"
                start_date_str = f"{start_date_str} {today.year}"
        
        # If no year in end date, add current year
        if not end_has_year:
            # Try to insert year after month name or day
            if re.search(r'\d{1,2}\s+(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)', end_date_str, re.IGNORECASE):
                # Format: "22 september" -> "22 september 2025"
                end_date_str = f"{end_date_str} {today.year}"
            elif re.search(r'(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\s+\d{1,2}', end_date_str, re.IGNORECASE):
                # Format: "september 22" -> "september 22 2025"
                end_date_str = f"{end_date_str} {today.year}"
        
        start_date = dateparser.parse(start_date_str, settings={'PREFER_DAY_OF_MONTH': 'first', 'DATE_ORDER': 'DMY', 'PREFER_DATES_FROM': 'current_period'})
        end_date = dateparser.parse(end_date_str, settings={'PREFER_DAY_OF_MONTH': 'last', 'DATE_ORDER': 'DMY', 'PREFER_DATES_FROM': 'current_period'})
        
        if start_date and end_date:
            # Ensure end_date is at the end of the day
            if end_date == start_date:
                end_date = end_date.replace(hour=23, minute=59, second=59)
            return {
                "start": start_date.strftime('%Y-%m-%d'),
                "end": end_date.strftime('%Y-%m-%d'),
                "summary": f"{start_date_str} to {end_date_str}"
            }

    # Explicit "year 2023 to year 2025" style ranges. These should expand to the
    # full calendar years for the start and end years.
    year_range_match = re.search(
        r"year\s+(\d{4})\s*(?:to|-|and)\s*year\s+(\d{4})",
        lowered,
    )
    if year_range_match:
        start_year = int(year_range_match.group(1))
        end_year = int(year_range_match.group(2))
        if end_year < start_year:
            start_year, end_year = end_year, start_year
        start = date(start_year, 1, 1)
        end = date(end_year, 12, 31)
        return {"start": start.isoformat(), "end": end.isoformat(), "summary": working}

    # Special handling for common relative phrases so that we return meaningful
    # ranges instead of a single guessed day.

    # Yesterday -> single day yesterday
    if "yesterday" in lowered:
        d = today - timedelta(days=1)
        return {"start": d.isoformat(), "end": d.isoformat()}

    # Today -> single day today
    if "today" in lowered:
        return {"start": today.isoformat(), "end": today.isoformat()}

    # Last week -> previous calendar week (Mon-Sun)
    if "last week" in lowered:
        this_week_start = today - timedelta(days=today.weekday())  # Monday of this week
        last_week_end = this_week_start - timedelta(days=1)
        last_week_start = last_week_end - timedelta(days=6)
        return {
            "start": last_week_start.isoformat(),
            "end": last_week_end.isoformat(),
        }

    # This week -> from Monday of this week up to today
    if "this week" in lowered:
        this_week_start = today - timedelta(days=today.weekday())
        return {
            "start": this_week_start.isoformat(),
            "end": today.isoformat(),
        }

    # This month -> from 1st of this month up to today
    if "this month" in lowered:
        first_day = date(today.year, today.month, 1)
        return {"start": first_day.isoformat(), "end": today.isoformat()}

    # This year / this whole year -> from 1st Jan of this year up to today.
    # We only treat "whole year" as the current year when no explicit year
    # digits are present, so that phrases like "year 2024" are still handled
    # by the explicit year logic later.
    if "this year" in lowered or ("this" in lowered and "whole year" in lowered and not any(ch.isdigit() for ch in lowered)):
        first_day = date(today.year, 1, 1)
        return {"start": first_day.isoformat(), "end": today.isoformat()}

    # Plain "last year" (no explicit year number) -> previous calendar year.
    if "last year" in lowered and not any(ch.isdigit() for ch in lowered):
        y = today.year - 1
        first_day = date(y, 1, 1)
        last_day = date(y, 12, 31)
        return {"start": first_day.isoformat(), "end": last_day.isoformat()}

    # "last 6 months" (or "last six months"): previous six full calendar months,
    # ending with the month before the current one.
    if "last 6 month" in lowered or "last six month" in lowered or "last six months" in lowered:
        end_year = today.year
        end_month = today.month - 1
        if end_month == 0:
            end_month = 12
            end_year -= 1
        # End is the last day of end_month
        end_last_day = calendar.monthrange(end_year, end_month)[1]
        end_date = date(end_year, end_month, end_last_day)

        # Start is first day of the month 5 months before end_month
        start_year = end_year
        start_month = end_month - 5
        while start_month <= 0:
            start_month += 12
            start_year -= 1
        start_date = date(start_year, start_month, 1)

        return {"start": start_date.isoformat(), "end": end_date.isoformat()}

    # Handle "last N months" patterns (e.g., "last 3 months", "last 2 months")
    # Also handle "past N months", "previous N months"
    # This returns N full calendar months ending with the month before the current one
    last_months_patterns = [
        r"last\s+(\d+)\s+months?",
        r"past\s+(\d+)\s+months?",
        r"previous\s+(\d+)\s+months?",
    ]
    for pattern in last_months_patterns:
        last_months_match = re.search(pattern, lowered, re.IGNORECASE)
        if last_months_match:
            num_months = int(last_months_match.group(1))
            if num_months > 0:
                # End is the last day of the month before the current one
                end_year = today.year
                end_month = today.month - 1
                if end_month == 0:
                    end_month = 12
                    end_year -= 1
                end_last_day = calendar.monthrange(end_year, end_month)[1]
                end_date = date(end_year, end_month, end_last_day)
                
                # Start is first day of the month (num_months - 1) months before end_month
                start_year = end_year
                start_month = end_month - (num_months - 1)
                while start_month <= 0:
                    start_month += 12
                    start_year -= 1
                
                start_date = date(start_year, start_month, 1)
                
                return {
                    "start": start_date.isoformat(),
                    "end": end_date.isoformat(),
                }
    
    # Special handling for relative phrase "last month". Instead of relying
    # on dateparser to guess a single day, we expand this to the full previous
    # calendar month.
    if "last month" in lowered:
        year = today.year
        month = today.month - 1
        if month == 0:
            month = 12
            year -= 1
        first_day = date(year, month, 1)
        last_day = date(year, month, calendar.monthrange(year, month)[1])
        return {"start": first_day.isoformat(), "end": last_day.isoformat()}

    # Handle "last N days" patterns (e.g., "last 7 days", "last 30 days")
    # Also handle "past N days", "previous N days", etc.
    # This should return a range from N days ago to today (inclusive)
    last_days_patterns = [
        r"last\s+(\d+)\s+days?",
        r"past\s+(\d+)\s+days?",
        r"previous\s+(\d+)\s+days?",
        r"(\d+)\s+days?\s+ago",
    ]
    for pattern in last_days_patterns:
        last_days_match = re.search(pattern, lowered, re.IGNORECASE)
        if last_days_match:
            num_days = int(last_days_match.group(1))
            if num_days > 0:
                # "last N days" typically means the past N days including today
                # So if today is day N, we go back N-1 days to get the start
                start_date = today - timedelta(days=num_days - 1)
                end_date = today
                return {
                    "start": start_date.isoformat(),
                    "end": end_date.isoformat(),
                }

    # Handle quarter-based date ranges
    # Quarters: Q1 (Jan-Mar), Q2 (Apr-Jun), Q3 (Jul-Sep), Q4 (Oct-Dec)
    
    # Check for explicit quarter with year (e.g., "Q1 2025", "first quarter 2025")
    quarter_year_pattern = re.search(
        r"(?:first|1st|second|2nd|third|3rd|fourth|4th)\s+quarter\s+(\d{4})|"
        r"q([1-4])\s+(\d{4})|"
        r"quarter\s+([1-4])\s+(\d{4})",
        lowered,
        re.IGNORECASE
    )
    if quarter_year_pattern:
        year_val = None
        quarter_num = None
        
        # Extract year and quarter number based on which pattern matched
        if quarter_year_pattern.group(1):  # "first quarter 2025" pattern
            year_val = int(quarter_year_pattern.group(1))
            if "first" in lowered or "1st" in lowered:
                quarter_num = 1
            elif "second" in lowered or "2nd" in lowered:
                quarter_num = 2
            elif "third" in lowered or "3rd" in lowered:
                quarter_num = 3
            elif "fourth" in lowered or "4th" in lowered:
                quarter_num = 4
        elif quarter_year_pattern.group(2):  # "Q1 2025" pattern
            quarter_num = int(quarter_year_pattern.group(2))
            year_val = int(quarter_year_pattern.group(3))
        elif quarter_year_pattern.group(4):  # "quarter 1 2025" pattern
            quarter_num = int(quarter_year_pattern.group(4))
            year_val = int(quarter_year_pattern.group(5))
        
        if quarter_num and year_val:
            # Calculate quarter date range
            if quarter_num == 1:
                start_date = date(year_val, 1, 1)
                end_date = date(year_val, 3, 31)
            elif quarter_num == 2:
                start_date = date(year_val, 4, 1)
                end_date = date(year_val, 6, 30)
            elif quarter_num == 3:
                start_date = date(year_val, 7, 1)
                end_date = date(year_val, 9, 30)
            elif quarter_num == 4:
                start_date = date(year_val, 10, 1)
                end_date = date(year_val, 12, 31)
            
            return {
                "start": start_date.isoformat(),
                "end": end_date.isoformat(),
            }
    
    # Handle "last quarter 2025" as Q4 2025 (special case)
    last_quarter_year_match = re.search(r"last\s+quarter\s+(\d{4})", lowered, re.IGNORECASE)
    if last_quarter_year_match:
        year_val = int(last_quarter_year_match.group(1))
        start_date = date(year_val, 10, 1)
        end_date = date(year_val, 12, 31)
        return {
            "start": start_date.isoformat(),
            "end": end_date.isoformat(),
        }
    
    # Handle "this quarter", "current quarter", or just "quarter" (current year's current quarter)
    if "this quarter" in lowered or "current quarter" in lowered or (lowered.strip() == "quarter"):
        current_month = today.month
        current_year = today.year
        
        if current_month <= 3:  # Q1
            start_date = date(current_year, 1, 1)
            end_date = date(current_year, 3, 31)
        elif current_month <= 6:  # Q2
            start_date = date(current_year, 4, 1)
            end_date = date(current_year, 6, 30)
        elif current_month <= 9:  # Q3
            start_date = date(current_year, 7, 1)
            end_date = date(current_year, 9, 30)
        else:  # Q4
            start_date = date(current_year, 10, 1)
            end_date = date(current_year, 12, 31)
        
        return {
            "start": start_date.isoformat(),
            "end": end_date.isoformat(),
        }
    
    # Handle "last quarter" (previous quarter)
    if "last quarter" in lowered:
        current_month = today.month
        current_year = today.year
        
        # Determine previous quarter
        if current_month <= 3:  # Currently in Q1, so last quarter is Q4 of previous year
            start_date = date(current_year - 1, 10, 1)
            end_date = date(current_year - 1, 12, 31)
        elif current_month <= 6:  # Currently in Q2, so last quarter is Q1
            start_date = date(current_year, 1, 1)
            end_date = date(current_year, 3, 31)
        elif current_month <= 9:  # Currently in Q3, so last quarter is Q2
            start_date = date(current_year, 4, 1)
            end_date = date(current_year, 6, 30)
        else:  # Currently in Q4, so last quarter is Q3
            start_date = date(current_year, 7, 1)
            end_date = date(current_year, 9, 30)
        
        return {
            "start": start_date.isoformat(),
            "end": end_date.isoformat(),
        }
    
    # Handle quarter names without explicit year (defaults to current year)
    # e.g., "first quarter", "Q1", "quarter 1"
    quarter_pattern = re.search(
        r"(?:first|1st)\s+quarter|"
        r"(?:second|2nd)\s+quarter|"
        r"(?:third|3rd)\s+quarter|"
        r"(?:fourth|4th)\s+quarter|"
        r"q([1-4])(?!\s*\d)|"
        r"quarter\s+([1-4])(?!\s*\d)",
        lowered,
        re.IGNORECASE
    )
    if quarter_pattern:
        quarter_num = None
        current_year = today.year
        
        # Extract quarter number
        if "first" in lowered or "1st" in lowered:
            quarter_num = 1
        elif "second" in lowered or "2nd" in lowered:
            quarter_num = 2
        elif "third" in lowered or "3rd" in lowered:
            quarter_num = 3
        elif "fourth" in lowered or "4th" in lowered:
            quarter_num = 4
        elif quarter_pattern.group(1):  # "Q1" pattern
            quarter_num = int(quarter_pattern.group(1))
        elif quarter_pattern.group(2):  # "quarter 1" pattern
            quarter_num = int(quarter_pattern.group(2))
        
        if quarter_num:
            # Calculate quarter date range for current year
            if quarter_num == 1:
                start_date = date(current_year, 1, 1)
                end_date = date(current_year, 3, 31)
            elif quarter_num == 2:
                start_date = date(current_year, 4, 1)
                end_date = date(current_year, 6, 30)
            elif quarter_num == 3:
                start_date = date(current_year, 7, 1)
                end_date = date(current_year, 9, 30)
            elif quarter_num == 4:
                start_date = date(current_year, 10, 1)
                end_date = date(current_year, 12, 31)
            
            return {
                "start": start_date.isoformat(),
                "end": end_date.isoformat(),
            }

    # Handle ranges like "june 5 to september 22" or "5 june to 22 september" (with or without year)
    # by defaulting the year to the current one when it is omitted.
    cross_month_range_pattern = re.compile(
        r"\b(?:(?P<m1>jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec|"
        r"january|february|march|april|june|july|august|september|october|november|december)\s+"
        r"(?P<d1>\d{1,2})(?:st|nd|rd|th)?|"
        r"(?P<d1b>\d{1,2})(?:st|nd|rd|th)?\s+"
        r"(?P<m1b>jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec|"
        r"january|february|march|april|june|july|august|september|october|november|december))"
        r"(?:\s+(?P<year1>\d{4}))?\s*(?:to|-|and)\s*"
        r"(?:(?P<m2>jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec|"
        r"january|february|march|april|june|july|august|september|october|november|december)\s+"
        r"(?P<d2>\d{1,2})(?:st|nd|rd|th)?|"
        r"(?P<d2b>\d{1,2})(?:st|nd|rd|th)?\s+"
        r"(?P<m2b>jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec|"
        r"january|february|march|april|june|july|august|september|october|november|december))"
        r"(?:\s+(?P<year2>\d{4}))?\b",
        re.IGNORECASE,
    )
    m_cross = cross_month_range_pattern.search(working)
    if m_cross:
        # Extract day and month for start date
        if m_cross.group("d1"):
            day1 = int(m_cross.group("d1"))
            month_str1 = m_cross.group("m1").lower()
        else:
            day1 = int(m_cross.group("d1b"))
            month_str1 = m_cross.group("m1b").lower()
        
        # Extract day and month for end date
        if m_cross.group("d2"):
            day2 = int(m_cross.group("d2"))
            month_str2 = m_cross.group("m2").lower()
        else:
            day2 = int(m_cross.group("d2b"))
            month_str2 = m_cross.group("m2b").lower()
        
        month_map = {
            "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
            "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6,
            "jul": 7, "july": 7, "aug": 8, "august": 8,
            "sep": 9, "sept": 9, "september": 9, "oct": 10, "october": 10,
            "nov": 11, "november": 11, "dec": 12, "december": 12,
        }
        month1 = month_map.get(month_str1)
        month2 = month_map.get(month_str2)
        
        if month1 and month2:
            # Use year from match if present, otherwise default to current year
            year_val = int(m_cross.group("year1") or m_cross.group("year2") or today.year)
            try:
                start_d = date(year_val, month1, day1)
                end_d = date(year_val, month2, day2)
                # Ensure start <= end
                if start_d > end_d:
                    start_d, end_d = end_d, start_d
                return {"start": start_d.isoformat(), "end": end_d.isoformat()}
            except ValueError:
                # Invalid day for that month/year; fall through to generic parsing.
                pass

    # Handle ranges like "1 sep to 30 sep" (with or without an explicit year)
    # by defaulting the year to the current one when it is omitted.
    # This is a very common way users phrase report periods.
    same_month_range_pattern = re.compile(
        r"\b(?P<d1>\d{1,2})(?:st|nd|rd|th)?\s+"
        r"(?P<m1>jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec|"
        r"january|february|march|april|june|july|august|september|october|november|december)"
        r"\s*(?:to|-|and)\s*"
        r"(?P<d2>\d{1,2})(?:st|nd|rd|th)?\s+"
        r"(?P<m2>jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec|"
        r"january|february|march|april|june|july|august|september|october|november|december)"
        r"(?:\s+(?P<year>\d{4}))?\b",
        re.IGNORECASE,
    )
    m_same = same_month_range_pattern.search(working)
    if m_same:
        day1 = int(m_same.group("d1"))
        day2 = int(m_same.group("d2"))
        month_str1 = m_same.group("m1").lower()
        month_str2 = m_same.group("m2").lower()
        month_map = {
            "jan": 1,
            "january": 1,
            "feb": 2,
            "february": 2,
            "mar": 3,
            "march": 3,
            "apr": 4,
            "april": 4,
            "may": 5,
            "jun": 6,
            "june": 6,
            "jul": 7,
            "july": 7,
            "aug": 8,
            "august": 8,
            "sep": 9,
            "sept": 9,
            "september": 9,
            "oct": 10,
            "october": 10,
            "nov": 11,
            "november": 11,
            "dec": 12,
            "december": 12,
        }
        month1 = month_map.get(month_str1)
        month2 = month_map.get(month_str2)
        if month1 and month2 and month1 == month2:
            year_val = int(m_same.group("year")) if m_same.group("year") else today.year
            try:
                start_d = date(year_val, month1, min(day1, day2))
                end_d = date(year_val, month1, max(day1, day2))
                return {"start": start_d.isoformat(), "end": end_d.isoformat()}
            except ValueError:
                # Invalid day for that month/year; fall through to generic parsing.
                pass

    # Before falling back to dateparser, check for explicit month-name dates
    # like "june 20th 2025" or "20 june 2025" and construct the date
    # directly, so that the day-of-month is preserved.
    month_name_pattern1 = re.compile(
        r"\b(?P<month>jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec|"
        r"january|february|march|april|june|july|august|september|october|november|december)\s+"
        r"(?P<day>\d{1,2})(?:st|nd|rd|th)?(?:\s*,\s*|\s+)(?P<year>\d{4})\b",
        re.IGNORECASE,
    )
    month_name_pattern2 = re.compile(
        r"\b(?P<day>\d{1,2})(?:st|nd|rd|th)?\s+"
        r"(?P<month>jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec|"
        r"january|february|march|april|june|july|august|september|october|november|december)(?:\s*,\s*|\s+)"
        r"(?P<year>\d{4})\b",
        re.IGNORECASE,
    )

    for pattern in (month_name_pattern1, month_name_pattern2):
        m = pattern.search(working)
        if m:
            day_val = int(m.group("day"))
            year_val = int(m.group("year"))
            month_str = m.group("month").lower()
            month_map = {
                "jan": 1,
                "january": 1,
                "feb": 2,
                "february": 2,
                "mar": 3,
                "march": 3,
                "apr": 4,
                "april": 4,
                "may": 5,
                "jun": 6,
                "june": 6,
                "jul": 7,
                "july": 7,
                "aug": 8,
                "august": 8,
                "sep": 9,
                "sept": 9,
                "september": 9,
                "oct": 10,
                "october": 10,
                "nov": 11,
                "november": 11,
                "dec": 12,
                "december": 12,
            }
            month_val = month_map.get(month_str)
            if month_val:
                try:
                    d = date(year_val, month_val, day_val)
                    iso = d.isoformat()
                    return {"start": iso, "end": iso}
                except ValueError:
                    # Invalid day for that month/year; fall through to
                    # generic parsing.
                    break

    # Handle cases like "september 2025" (month + year, no explicit day) as the
    # full calendar month.
    month_year_pattern = re.compile(
        r"\b(?P<month>jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec|"
        r"january|february|march|april|june|july|august|september|october|november|december)\s+"
        r"(?P<year>\d{4})\b",
        re.IGNORECASE,
    )
    m_my = month_year_pattern.search(working)
    if m_my:
        month_str = m_my.group("month").lower()
        year_val = int(m_my.group("year"))
        month_map = {
            "jan": 1,
            "january": 1,
            "feb": 2,
            "february": 2,
            "mar": 3,
            "march": 3,
            "apr": 4,
            "april": 4,
            "may": 5,
            "jun": 6,
            "june": 6,
            "jul": 7,
            "july": 7,
            "aug": 8,
            "august": 8,
            "sep": 9,
            "sept": 9,
            "september": 9,
            "oct": 10,
            "october": 10,
            "nov": 11,
            "november": 11,
            "dec": 12,
            "december": 12,
        }
        month_val = month_map.get(month_str)
        if month_val:
            first_day = date(year_val, month_val, 1)
            last_day = date(year_val, month_val, calendar.monthrange(year_val, month_val)[1])
            return {"start": first_day.isoformat(), "end": last_day.isoformat()}

    # Handle month-only phrases like "month jan", "month of january", "for the month of september",
    # or "january month" (no explicit year) as the full calendar month of the current year.
    # Check for patterns like "for the month of [month]" or "month of [month]" or "[month] month"
    month_only_patterns = [
        re.compile(
            r"\b(?:for\s+)?(?:the\s+)?month\s+of\s+(?P<month>jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec|"
            r"january|february|march|april|june|july|august|september|october|november|december)\b",
            re.IGNORECASE,
        ),
        re.compile(
            r"\bmonth\s+(?P<month>jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec|"
            r"january|february|march|april|june|july|august|september|october|november|december)\b",
            re.IGNORECASE,
        ),
        re.compile(
            r"\b(?P<month>jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec|"
            r"january|february|march|april|june|july|august|september|october|november|december)\s+month\b",
            re.IGNORECASE,
        ),
    ]
    
    if "month" in lowered:
        for month_only_pattern in month_only_patterns:
            m_mo = month_only_pattern.search(working)
            if m_mo:
                month_str = m_mo.group("month").lower()
                month_map = {
                    "jan": 1,
                    "january": 1,
                    "feb": 2,
                    "february": 2,
                    "mar": 3,
                    "march": 3,
                    "apr": 4,
                    "april": 4,
                    "may": 5,
                    "jun": 6,
                    "june": 6,
                    "jul": 7,
                    "july": 7,
                    "aug": 8,
                    "august": 8,
                    "sep": 9,
                    "sept": 9,
                    "september": 9,
                    "oct": 10,
                    "october": 10,
                    "nov": 11,
                    "november": 11,
                    "dec": 12,
                    "december": 12,
                }
                month_val = month_map.get(month_str)
                if month_val:
                    year_val = today.year
                    first_day = date(year_val, month_val, 1)
                    last_day = date(year_val, month_val, calendar.monthrange(year_val, month_val)[1])
                    return {"start": first_day.isoformat(), "end": last_day.isoformat()}

    # Handle dot-separated dates (DD.MM.YYYY format - European format only)
    # This must be done before dateparser to ensure correct parsing
    dot_date_pattern = re.compile(
        r"\b(\d{1,2})\.(\d{1,2})\.(\d{4})\b"
    )
    dot_date_match = dot_date_pattern.search(working)
    if dot_date_match:
        day = int(dot_date_match.group(1))
        month = int(dot_date_match.group(2))
        year = int(dot_date_match.group(3))
        
        # Parse as DD.MM.YYYY format (European format only)
        parsed_date = None
        try:
            if 1 <= day <= 31 and 1 <= month <= 12:
                parsed_date = date(year, month, day)
        except ValueError:
            pass
        
        if parsed_date:
            # Check if there's a date range (e.g., "05.01.2025 to 10.01.2025")
            range_match = re.search(
                r"\b(\d{1,2})\.(\d{1,2})\.(\d{4})\s*(?:to|and|,|-|–|—)\s*(\d{1,2})\.(\d{1,2})\.(\d{4})\b",
                working,
                re.IGNORECASE
            )
            if range_match:
                # Parse both dates as DD.MM.YYYY format (European format only)
                d1 = int(range_match.group(1))
                m1 = int(range_match.group(2))
                y1 = int(range_match.group(3))
                d2 = int(range_match.group(4))
                m2 = int(range_match.group(5))
                y2 = int(range_match.group(6))
                
                start_date = None
                end_date = None
                
                # Parse as DD.MM.YYYY format (European format only)
                try:
                    if 1 <= d1 <= 31 and 1 <= m1 <= 12 and 1 <= d2 <= 31 and 1 <= m2 <= 12:
                        start_date = date(y1, m1, d1)
                        end_date = date(y2, m2, d2)
                except ValueError:
                    pass
                
                if start_date and end_date:
                    # Ensure start <= end
                    if start_date > end_date:
                        start_date, end_date = end_date, start_date
                    return {
                        "start": start_date.isoformat(),
                        "end": end_date.isoformat(),
                    }
            
            # Single date
            return {
                "start": parsed_date.isoformat(),
                "end": parsed_date.isoformat(),
            }

    # Handle dash-separated dates (DD-MM-YYYY format - European format only)
    dash_date_pattern = re.compile(
        r"\b(\d{1,2})-(\d{1,2})-(\d{4})\b"
    )
    dash_date_match = dash_date_pattern.search(working)
    if dash_date_match:
        day = int(dash_date_match.group(1))
        month = int(dash_date_match.group(2))
        year = int(dash_date_match.group(3))
        
        # Parse as DD-MM-YYYY format (European format only)
        parsed_date = None
        try:
            if 1 <= day <= 31 and 1 <= month <= 12:
                parsed_date = date(year, month, day)
        except ValueError:
            pass
        
        if parsed_date:
            # Check if there's a date range (e.g., "05-01-2025 to 10-01-2025")
            range_match = re.search(
                r"\b(\d{1,2})-(\d{1,2})-(\d{4})\s*(?:to|and|,|–|—)\s*(\d{1,2})-(\d{1,2})-(\d{4})\b",
                working,
                re.IGNORECASE
            )
            if range_match:
                # Parse both dates as DD-MM-YYYY format (European format only)
                d1 = int(range_match.group(1))
                m1 = int(range_match.group(2))
                y1 = int(range_match.group(3))
                d2 = int(range_match.group(4))
                m2 = int(range_match.group(5))
                y2 = int(range_match.group(6))
                
                start_date = None
                end_date = None
                
                try:
                    if 1 <= d1 <= 31 and 1 <= m1 <= 12 and 1 <= d2 <= 31 and 1 <= m2 <= 12:
                        start_date = date(y1, m1, d1)
                        end_date = date(y2, m2, d2)
                except ValueError:
                    pass
                
                if start_date and end_date:
                    if start_date > end_date:
                        start_date, end_date = end_date, start_date
                    return {
                        "start": start_date.isoformat(),
                        "end": end_date.isoformat(),
                    }
            
            # Single date
            return {
                "start": parsed_date.isoformat(),
                "end": parsed_date.isoformat(),
            }

    # Handle slash-separated dates (DD/MM/YYYY format - European format only)
    slash_date_pattern = re.compile(
        r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b"
    )
    slash_date_match = slash_date_pattern.search(working)
    if slash_date_match:
        day = int(slash_date_match.group(1))
        month = int(slash_date_match.group(2))
        year = int(slash_date_match.group(3))
        
        # Parse as DD/MM/YYYY format (European format only)
        parsed_date = None
        try:
            if 1 <= day <= 31 and 1 <= month <= 12:
                parsed_date = date(year, month, day)
        except ValueError:
            pass
        
        if parsed_date:
            # Check if there's a date range (e.g., "05/01/2025 to 10/01/2025")
            range_match = re.search(
                r"\b(\d{1,2})/(\d{1,2})/(\d{4})\s*(?:to|and|,|-|–|—)\s*(\d{1,2})/(\d{1,2})/(\d{4})\b",
                working,
                re.IGNORECASE
            )
            if range_match:
                # Parse both dates as DD/MM/YYYY format (European format only)
                d1 = int(range_match.group(1))
                m1 = int(range_match.group(2))
                y1 = int(range_match.group(3))
                d2 = int(range_match.group(4))
                m2 = int(range_match.group(5))
                y2 = int(range_match.group(6))
                
                start_date = None
                end_date = None
                
                try:
                    if 1 <= d1 <= 31 and 1 <= m1 <= 12 and 1 <= d2 <= 31 and 1 <= m2 <= 12:
                        start_date = date(y1, m1, d1)
                        end_date = date(y2, m2, d2)
                except ValueError:
                    pass
                
                if start_date and end_date:
                    if start_date > end_date:
                        start_date, end_date = end_date, start_date
                    return {
                        "start": start_date.isoformat(),
                        "end": end_date.isoformat(),
                    }
            
            # Single date
            return {
                "start": parsed_date.isoformat(),
                "end": parsed_date.isoformat(),
            }

    # Handle space-separated dates (DD MM YYYY format - European format only)
    # This pattern matches dates with spaces, but ensures it's not part of a larger number or text
    space_date_pattern = re.compile(
        r"\b(\d{1,2})\s+(\d{1,2})\s+(\d{4})\b"
    )
    space_date_match = space_date_pattern.search(working)
    if space_date_match:
        day = int(space_date_match.group(1))
        month = int(space_date_match.group(2))
        year = int(space_date_match.group(3))
        
        # Parse as DD MM YYYY format (European format only)
        parsed_date = None
        try:
            if 1 <= day <= 31 and 1 <= month <= 12:
                parsed_date = date(year, month, day)
        except ValueError:
            pass
        
        if parsed_date:
            # Check if there's a date range (e.g., "05 01 2025 to 10 01 2025")
            range_match = re.search(
                r"\b(\d{1,2})\s+(\d{1,2})\s+(\d{4})\s*(?:to|and|,|-|–|—)\s*(\d{1,2})\s+(\d{1,2})\s+(\d{4})\b",
                working,
                re.IGNORECASE
            )
            if range_match:
                # Parse both dates as DD MM YYYY format (European format only)
                d1 = int(range_match.group(1))
                m1 = int(range_match.group(2))
                y1 = int(range_match.group(3))
                d2 = int(range_match.group(4))
                m2 = int(range_match.group(5))
                y2 = int(range_match.group(6))
                
                start_date = None
                end_date = None
                
                try:
                    if 1 <= d1 <= 31 and 1 <= m1 <= 12 and 1 <= d2 <= 31 and 1 <= m2 <= 12:
                        start_date = date(y1, m1, d1)
                        end_date = date(y2, m2, d2)
                except ValueError:
                    pass
                
                if start_date and end_date:
                    if start_date > end_date:
                        start_date, end_date = end_date, start_date
                    return {
                        "start": start_date.isoformat(),
                        "end": end_date.isoformat(),
                    }
            
            # Single date
            return {
                "start": parsed_date.isoformat(),
                "end": parsed_date.isoformat(),
            }

    # Replace common connectors with "to" while preserving overall structure,
    # so that date ranges like "16/10/2025 - 20/10/2025" or
    # "Oct 1–Oct 5, 2025" are easier for dateparser to interpret.
    for connector in [" and ", " & ", ",", " - ", " – ", " — "]:
        if connector.strip() in ["and", "&", ",", "-", "–", "—"]:
            working = working.replace(connector, " to ")

    matches = search_dates(working, languages=["en"], settings={"PREFER_DAY_OF_MONTH": "first", "DATE_ORDER": "DMY"})
    if not matches:
        return None


    # original text clearly contains a different day number with a month name
    # (e.g. "june 20th 2025"), correct the day-of-month using that explicit
    # number to avoid everything collapsing to the 1st.
    if len(matches) == 1:
        _phrase, dt0 = matches[0]
        date0 = dt0.date()
        if date0.day == 1:
            month_names_short = [
                "jan",
                "feb",
                "mar",
                "apr",
                "may",
                "jun",
                "jul",
                "aug",
                "sep",
                "oct",
                "nov",
                "dec",
            ]
            month_names_long = [
                "january",
                "february",
                "march",
                "april",
                "may",
                "june",
                "july",
                "august",
                "september",
                "october",
                "november",
                "december",
            ]
            if any(m in lowered for m in month_names_short + month_names_long):
                # Find all day-like numbers in the text and pick a reasonable
                # candidate that is not 1 and within [1, 31], ignoring likely
                # year values.
                candidates: List[int] = []
                for m in re.finditer(r"\b(\d{1,2})(?:st|nd|rd|th)?\b", lowered):
                    val = int(m.group(1))
                    if 1 <= val <= 31 and val != 1:
                        candidates.append(val)
                if candidates:
                    day_val = candidates[-1]
                    try:
                        corrected = date(date0.year, date0.month, day_val)
                        matches = [(matches[0][0], datetime.combine(corrected, datetime.min.time()))]
                    except ValueError:
                        # If the day is invalid for that month, fall back to the
                        # original parsed date.
                        pass

    unique_dates: List[datetime] = []
    seen: set = set()
    for _phrase, dt in matches:
        date_only = dt.date()
        iso_value = date_only.isoformat()
        if iso_value not in seen:
            seen.add(iso_value)
            unique_dates.append(datetime.combine(date_only, datetime.min.time()))
    if not unique_dates:
        return None

    # Filter out clearly unrealistic years (e.g. a plate number like "3688"
    # being interpreted as year 3688). We keep a reasonable range for
    # reporting use cases.
    realistic_dates = [
        dt for dt in unique_dates if 1900 <= dt.year <= 2100
    ]
    if not realistic_dates:
        return None

    # Sort the unique dates chronologically.
    unique_dates = sorted(realistic_dates)

    # If the text seems to be talking about a whole year (e.g. "last year 2024"
    # or "year 2024") and dateparser has identified at least one date in that
    # year, expand the range to the full calendar year.
    lowered = text.lower()
    distinct_years = sorted({dt.year for dt in unique_dates})
    month_names = [
        "january",
        "february",
        "march",
        "april",
        "may",
        "june",
        "july",
        "august",
        "september",
        "october",
        "november",
        "december",
    ]
    has_month_name = any(m in lowered for m in month_names)

    if len(distinct_years) == 1 and not has_month_name:
        y = distinct_years[0]
        year_str = str(y)
        tokens = lowered.split()
        # Only treat this as a pure year expression when the text clearly
        # refers to the year itself (e.g. "year 2024", "2024 year", or
        # simply "2024"), not when it is a full date like "2025-07-05".
        is_plain_year = (tokens == [year_str]) or (
            len(tokens) == 2
            and (
                (tokens[0] == "year" and tokens[1] == year_str)
                or (tokens[1] == "year" and tokens[0] == year_str)
            )
        )
        if is_plain_year:
            first_day = date(y, 1, 1)
            last_day = date(y, 12, 31)
            start = first_day.isoformat()
            end = last_day.isoformat()
        else:
            start = unique_dates[0].date().isoformat()
            end = unique_dates[-1].date().isoformat()
    # If the text seems to be talking about a whole month (e.g. "september month")
    # and dateparser has identified at least one date in that month, expand the
    # range to cover the full calendar month for that date (from day 1 to the
    # last day of the month).
    elif "month" in lowered and has_month_name:
        base_dt = unique_dates[0]
        y = base_dt.year
        m = base_dt.month
        first_day = date(y, m, 1)
        last_day = date(y, m, calendar.monthrange(y, m)[1])
        start = first_day.isoformat()
        end = last_day.isoformat()
    else:
        start = unique_dates[0].date().isoformat()
        end = unique_dates[-1].date().isoformat()

    return {
        "start": start,
        "end": end,
    }

class ValidateReportForm(FormValidationAction):
    def name(self) -> Text:
        return "validate_report_form"

    async def required_slots(
        self,
        slots_mapped_in_domain: List[Text],
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any],
    ) -> List[Text]:
        required = ["report_type"]
        # Normalise report_type so synonyms like "driver behaviour report" map
        # correctly to the keys used in REPORT_SPECS and endpoint routing.
        raw_report_type = tracker.get_slot("report_type")
        report_type = normalise_report_type(raw_report_type) or raw_report_type
        report_spec = REPORT_SPECS.get(report_type or "")
        if not report_spec:
            return required
        needs_assets = report_spec.get("requires_assets")
        needs_dates = report_spec.get("requires_dates")
        needs_driver = report_spec.get("requires_driver")

        # For driver-based reports, ask for driver first, then date range.
        if needs_driver:
            required.append("driver")
            if needs_dates:
                required.append("date_range")
        else:
            # Original order for asset/date-based reports.
            if needs_assets:
                required.append("assets")
            if needs_dates:
                required.append("date_range")
        return required

    def validate_driver(
        self,
        slot_value: Any,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any],
    ) -> Dict[Text, Any]:
        """Validate driver name and ensure it's provided for driver behavior reports."""
        # Normalize input spaces BEFORE any processing
        normalize_input(tracker)
        
        if not slot_value:
            dispatcher.utter_message(text="Please provide a driver name for the driver behavior report.")
            return {"driver": None}
        return {"driver": slot_value}

    def validate_report_type(
        self,
        slot_value: Any,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any],
    ) -> Dict[Text, Any]:
        # Normalize input spaces BEFORE any processing
        normalize_input(tracker)
        
        # First try to normalize from slot_value
        normalised = normalise_report_type(slot_value)
        
        # If slot_value didn't yield a result, try extracting from the latest message text
        if not normalised:
            latest = tracker.latest_message or {}
            text = latest.get("text") or ""
            if text:
                logger.info(
                    "validate_report_type: slot_value=%r didn't yield result, trying text=%r",
                    slot_value,
                    text,
                )
                # Try to find report type in the text
                normalised = normalise_report_type(text)
                logger.info(
                    "validate_report_type: normalise_report_type(text) returned=%r",
                    normalised,
                )
                # Also check entities for report_type
                if not normalised:
                    entities = latest.get("entities") or []
                    for entity in entities:
                        if entity.get("entity") == "report_type":
                            entity_value = entity.get("value")
                            if entity_value:
                                normalised = normalise_report_type(entity_value)
                                if normalised:
                                    logger.info(
                                        "validate_report_type: found report_type from entity=%r",
                                        entity_value,
                                    )
                                    break
        
        if normalised:
            updates: Dict[Text, Any] = {"report_type": normalised}
            latest = tracker.latest_message or {}
            entities = latest.get("entities") or []
            
            # Always clear old slots when setting a report type to ensure fresh start
            # This prevents stale data from previous reports from interfering
            current_report_type = tracker.get_slot("report_type")
            is_new_report_type = current_report_type != normalised
            
            # Always clear old slots when a new report type is detected OR when form is restarting
            # This ensures the form doesn't use stale data from previous reports
            if is_new_report_type or current_report_type is None:
                logger.info(
                    "validate_report_type: detected new report type, clearing old slots. old=%r new=%r",
                    current_report_type,
                    normalised,
                )
                # Clear old slots immediately - they'll be set from current message if provided
                updates["assets"] = None
                updates["date_range"] = None
                updates["start_date"] = None
                updates["end_date"] = None
                updates["driver"] = None
            
            # For utilization and fleet performance reports, ensure we get a date range
            if normalised in ["utilization report", "fleet performance summary report"]:
                date_values = [
                    str(entity.get("value"))
                    for entity in entities
                    if entity.get("entity") == "date" and entity.get("value")
                ]
                
                # If no date entities found, clear any existing date range to force the prompt
                if not date_values and not tracker.get_slot("date_range"):
                    return {
                        "report_type": normalised,
                        "date_range": None,
                        "start_date": None,
                        "end_date": None
                    }
                    
                text = latest.get("text") or " ".join(date_values)
                if text:
                    logger.info(
                        "validate_report_type: auto date from entities=%r joined=%r",
                        date_values,
                        text,
                    )
                    parsed = parse_date_range(text)
                    logger.info(
                        "validate_report_type: auto parsed date_range=%r", parsed
                    )
                    if parsed:
                        start = parsed["start"]
                        end = parsed["end"]
                        summary = start if start == end else f"{start} to {end}"
                        updates.update(
                            {
                                "date_range": summary,
                                "start_date": start,
                                "end_date": end,
                            }
                        )
            
            # Existing date handling for other report types
            elif not tracker.get_slot("date_range"):
                date_values = [
                    str(entity.get("value"))
                    for entity in entities
                    if entity.get("entity") == "date" and entity.get("value")
                ]
                text = latest.get("text") or " ".join(date_values)
                if text:
                    logger.info(
                        "validate_report_type: auto date from entities=%r joined=%r",
                        date_values,
                        text,
                    )
                    parsed = parse_date_range(text)
                    logger.info(
                        "validate_report_type: auto parsed date_range=%r", parsed
                    )
                    if parsed:
                        start = parsed["start"]
                        end = parsed["end"]
                        summary = start if start == end else f"{start} to {end}"
                        updates.update(
                            {
                                "date_range": summary,
                                "start_date": start,
                                "end_date": end,
                            }
                        )

            # For reports that require assets, handle asset extraction from the current message.
            needs_assets = REPORT_SPECS.get(normalised, {}).get("requires_assets", False)
            needs_dates = REPORT_SPECS.get(normalised, {}).get("requires_dates", False)
            needs_driver = REPORT_SPECS.get(normalised, {}).get("requires_driver", False)
            
            # If this is a new report type (already cleared slots above), ensure we don't clear again
            # But if same report type, only clear slots that aren't needed
            if not is_new_report_type:
                # Same report type - only clear slots that aren't needed for this report
                if not needs_assets and "assets" not in updates:
                    updates["assets"] = None
                if not needs_dates and "date_range" not in updates:
                    updates["date_range"] = None
                    updates["start_date"] = None
                    updates["end_date"] = None
                if not needs_driver and "driver" not in updates:
                    updates["driver"] = None
                
            # Try to extract assets from the current message entities
            asset_values = [
                str(entity.get("value"))
                for entity in entities
                if entity.get("entity") == "asset" and entity.get("value")
            ]
            if asset_values:
                extracted = extract_assets(asset_values)
                logger.info(
                    "validate_report_type: auto assets from entities=%r extracted=%r",
                    asset_values,
                    extracted,
                )
                if extracted:
                    updates["assets"] = extracted
            # Note: We no longer recover assets from history to avoid using stale data
            # from previous requests. Assets must be explicitly provided in the current message.

            return updates
            
        dispatcher.utter_message(
            text="I can run the following reports: fleet statistics/trips report, fleet summary report, fleet performance summary report, fuel trip consumption report, odometer report, Utilization Report/Work Hour Report, Stop time report , idle time report , Raw Data Report , Track Data Report/All Parameters , Over Speeding Report , Driving Behaviour Report , Temperature & Humidity Report , Weight Sensor Report , Commands History Report , Events Report."
        )
        return {"report_type": None}

    def validate_assets(
        self,
        slot_value: Any,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any],
    ) -> Dict[Text, Any]:
        # Normalize input spaces BEFORE any processing
        normalize_input(tracker)
        
        report_type = tracker.get_slot("report_type") or ""
        report_spec = REPORT_SPECS.get(report_type, {})
        
        # First, try to extract assets from the current message entities
        # This ensures we get all assets from the current request, not just from slot_value
        latest = tracker.latest_message or {}
        entities = latest.get("entities") or []
        asset_values = [
            str(entity.get("value"))
            for entity in entities
            if entity.get("entity") == "asset" and entity.get("value")
        ]
        
        # Extract assets from entities first (most reliable)
        if asset_values:
            extracted_from_entities = extract_assets(asset_values)
            logger.info(
                "validate_assets: asset entities=%r extracted_from_entities=%r",
                asset_values,
                extracted_from_entities,
            )
            if extracted_from_entities:
                return {"assets": extracted_from_entities}
        
        # If no assets found in entities, try extracting from the current message text
        # This handles cases where the NLU didn't recognize the asset as an entity
        text = latest.get("text") or ""
        assets_from_text = []
        if text and not asset_values:
            # Try to extract assets directly from the message text
            assets_from_text = extract_assets(text)
            logger.info(
                "validate_assets: no entities found, trying text extraction. text=%r extracted=%r",
                text,
                assets_from_text,
            )
            if assets_from_text:
                return {"assets": assets_from_text}
        
        # If no assets found in current message (neither entities nor text extraction),
        # check if slot_value matches the current message text (from domain mapping)
        # If it does, use it. Otherwise, clear old assets to avoid using stale data
        if text and not asset_values and not assets_from_text:
            assets_from_slot = extract_assets(slot_value)
            # Check if slot_value is the same as the current message text (set by domain mapping)
            # If so, it's the current input, not old data
            slot_text = str(slot_value).strip() if slot_value else ""
            if slot_text and slot_text.lower() == text.lower():
                # slot_value matches current message - this is the current input, use it
                if assets_from_slot:
                    logger.info(
                        "validate_assets: slot_value matches current message, using it. assets=%r",
                        assets_from_slot,
                    )
                    return {"assets": assets_from_slot}
            elif assets_from_slot:
                # Old assets exist but not in current message - clear them
                logger.info(
                    "validate_assets: clearing old assets=%r (not in current message)",
                    assets_from_slot,
                )
                # Don't send message here - let the form handle prompting
                return {"assets": None}
        
        # Fall back to slot_value if no entities found and message doesn't require clearing
        assets = extract_assets(slot_value)
        logger.info("validate_assets: slot_value=%r extracted_assets=%r", slot_value, assets)
        
        # Don't send messages in validation - let the form handle prompting
        # Just return None if assets are required but not found
        if report_spec.get("requires_assets") and not assets:
            return {"assets": None}
        return {"assets": assets}

    def validate_date_range(
        self,
        slot_value: Any,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any],
    ) -> Dict[Text, Any]:
        # Normalize input spaces BEFORE any processing
        normalize_input(tracker)
        
        report_type = tracker.get_slot("report_type") or ""
        report_spec = REPORT_SPECS.get(report_type, {})
        # slot_value can be a single string, or a list of values. However,
        # to robustly handle phrases like "2 june 2025 to 30 nov 2025",
        # we prefer to parse the full latest user message text and only
        # fall back to entities or the slot value when necessary.
        if isinstance(slot_value, list):
            joined = " ".join(str(v) for v in slot_value)
        else:
            joined = slot_value

        latest = tracker.latest_message or {}
        text = latest.get("text") or ""

        if text:
            lowered = text.lower()
            for kw in ["from", "between"]:
                idx = lowered.find(kw)
                if idx != -1:
                    text = text[idx:]
                    break
            joined = text
        else:
            entities = latest.get("entities") or []
            date_values = [
                str(entity.get("value"))
                for entity in entities
                if entity.get("entity") == "date" and entity.get("value")
            ]
            if date_values:
                joined = " ".join(date_values)

        logger.info("validate_date_range: raw_slot_value=%r joined_text=%r", slot_value, joined)
        parsed = parse_date_range(joined) if joined else None
        logger.info("validate_date_range: parsed=%r", parsed)
        if not parsed:
            # Don't send messages in validation - let the form handle prompting
            # Just return None if dates are required but not found
            if report_spec.get("requires_dates"):
                return {"date_range": None}
            return {"date_range": None, "start_date": None, "end_date": None}
        start = parsed["start"]
        end = parsed["end"]
        summary = start if start == end else f"{start} to {end}"
        return {"date_range": summary, "start_date": start, "end_date": end}


def get_driver_id_by_name(driver_name: Text) -> Optional[str]:
    """
    Get driver ID by driver's full name from MongoDB.
    
    Args:
        driver_name: Full name of the driver to search for
        
    Returns:
        str: Driver ID if found, None otherwise
    """
    try:
        with MongoClient(MONGO_URI) as client:
            collection = client[MONGO_DB]["Driver"]

            raw_name = (driver_name or "").strip()
            if not raw_name:
                return None

            name_parts = raw_name.split()
            first_name = name_parts[0]
            last_name = " ".join(name_parts[1:]) if len(name_parts) > 1 else ""

            # Build a flexible query: match by full name, or by first/last name individually.
            regex_full = re.escape(raw_name)
            or_clauses: List[Dict[str, Any]] = [
                {
                    "$expr": {
                        "$regexMatch": {
                            "input": {"$concat": ["$profile.first_name", " ", "$profile.last_name"]},
                            "regex": regex_full,
                            "options": "i",
                        }
                    }
                }
            ]

            if first_name:
                or_clauses.append({"profile.first_name": {"$regex": re.escape(first_name), "$options": "i"}})
            if last_name:
                or_clauses.append({"profile.last_name": {"$regex": re.escape(last_name), "$options": "i"}})

            query: Dict[str, Any] = {
                "sub_tenant_id": SUB_TENANT_ID or "",
                "$or": or_clauses,
            }

            result = collection.find_one(query, {"_id": 1, "profile.first_name": 1, "profile.last_name": 1})

            if result and result.get("_id"):
                logger.info(
                    "Resolved driver name %r to driverId=%r (%s %s)",
                    raw_name,
                    result["_id"],
                    result.get("profile", {}).get("first_name", ""),
                    result.get("profile", {}).get("last_name", ""),
                )
                return str(result["_id"])

            logger.warning("No driver found matching name %r with query %r", raw_name, query)

    except Exception as exc:
        logger.error("MongoDB lookup failed for driver name %r: %s", driver_name, exc)

    return None


def get_asset_id_by_plate(plate_number: Text) -> Optional[str]:
    try:
        with MongoClient(MONGO_URI) as client:
            collection = client[MONGO_DB][MONGO_COLLECTION]
            for candidate in plate_variations(plate_number):
                result = collection.find_one(
                    {
                        "details.plate_number": {
                            "$regex": f"^{re.escape(candidate)}$",
                            "$options": "i",
                        },
                        "sub_tenant_id": SUB_TENANT_ID,
                    },
                    {"_id": 1},
                )
                if result and result.get("_id"):
                    return str(result["_id"])
    except Exception as exc:  # pragma: no cover - safety net for db issues
        logger.error("Mongo lookup failed for %s: %s", plate_number, exc)
    return None


def call_report_api(asset_id: Text, start_date: Text, end_date: Text, endpoint: Text) -> Dict[Text, Any]:
    url = f"{BASE_URL}{endpoint}"

    # If the dates look like plain calendar dates (YYYY-MM-DD), expand them to
    # full-day UTC timestamps so the backend includes all events for that
    # calendar day, rather than treating start=end as a zero-length window.
    def to_full_day(dt_str: Text, is_end: bool) -> Text:
        # Already looks like a timestamp: leave as-is.
        if "T" in dt_str:
            return dt_str
        try:
            d = datetime.strptime(dt_str, "%Y-%m-%d").date()
        except ValueError:
            # Not a plain YYYY-MM-DD; send as-is.
            return dt_str
        if is_end:
            return f"{d.isoformat()}T23:59:59.999Z"
        return f"{d.isoformat()}T00:00:00.000Z"

    start_out = to_full_day(start_date, is_end=False)
    end_out = to_full_day(end_date, is_end=True)

    payload = {
        "startDate": start_out,
        "endDate": end_out,
        "assetId": asset_id,
        "page": REPORT_PAGE,
        "size": REPORT_SIZE,
    }
    headers = {
        "Authorization": AUTHORIZATION,
        "Content-Type": "application/json",
    }
    try:
        response = requests.post(url, json=payload, headers=headers, timeout=60)
        response.raise_for_status()
        body: Any
        try:
            body = response.json()
        except ValueError:
            body = response.text
        return {"status": response.status_code, "body": body}
    except requests.RequestException as exc:
        logger.error("Report API failed for asset %s: %s", asset_id, exc)
        return {"error": str(exc)}


class ActionRunReport(Action):
    def name(self) -> Text:
        return "action_run_report"

    async def run(
        self,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any],
    ) -> List[Dict[Text, Any]]:
        # Normalize input spaces BEFORE any processing
        normalize_input(tracker)
        
        # Check if the user's message contains "report" - if not, this might be misclassified
        # and should go to MongoDB agent instead
        latest = tracker.latest_message or {}
        user_text = latest.get("text") or ""
        latest_intent = latest.get("intent", {}).get("name", "")
        
        # If intent is a report intent but text doesn't contain "report", it might be misclassified
        # Route to MongoDB agent for textual fleet queries
        if latest_intent.startswith("request_") and latest_intent.endswith("_report"):
            if user_text and "report" not in user_text.lower():
                logger.warning(f"Report intent detected but no 'report' word in text. Routing to MongoDB agent. Intent: {latest_intent}, Text: {user_text}")
                # This is likely a textual fleet query, route to MongoDB agent
                # Call the MongoDB agent directly
                try:
                    entities = latest.get("entities") or []
                    asset_values = [
                        str(entity.get("value"))
                        for entity in entities
                        if entity.get("entity") == "asset" and entity.get("value")
                    ]
                    if not asset_values:
                        extracted_assets = extract_assets(user_text)
                        if extracted_assets:
                            asset_values = extracted_assets
                    plate_number = asset_values[0] if asset_values else None
                    asset_id = None
                    if plate_number:
                        asset_id = get_asset_id_by_plate(plate_number)
                    agent_response = call_mongo_agent(
                        user_query=user_text,
                        asset_id=asset_id,
                        plate_number=plate_number
                    )
                    if "error" in agent_response:
                        answer = agent_response.get("answer") or agent_response.get("error", "I encountered an error while processing your query.")
                        dispatcher.utter_message(text=answer)
                    elif "answer" in agent_response:
                        dispatcher.utter_message(text=agent_response["answer"])
                    else:
                        response_text = json.dumps(agent_response, indent=2, default=str)
                        dispatcher.utter_message(text=f"Here is the information:\n{response_text}")
                    return []
                except Exception as exc:
                    logger.error("Error routing to MongoDB agent: %s", exc, exc_info=True)
                    dispatcher.utter_message(text="I encountered an error while processing your query. Please try again.")
                    return []
        
        report_type = tracker.get_slot("report_type")
        assets_slot = tracker.get_slot("assets")
        assets = extract_assets(assets_slot)
        driver_name = tracker.get_slot("driver")
        start_date = tracker.get_slot("start_date")
        end_date = tracker.get_slot("end_date") or start_date

        report_spec = REPORT_SPECS.get(report_type or "", {})
        assets_required = report_spec.get("requires_assets", False)
        dates_required = report_spec.get("requires_dates", False)

        # If there is no report context at all (no type, no assets, no dates),
        # treat this as a stray call and simply prompt the user instead of showing an error.
        if not report_type and not assets and not start_date and not end_date:
            dispatcher.utter_message(
                text=(
                    "Tell me which report you need (trips report, "
                    "idle time report, stop time report, fleet summary report, "
                    "or utilization report) and for which vehicle and dates if applicable."
                )
            )
            return []

        if not report_type:
            dispatcher.utter_message(text="I did not receive a report type.")
            return []

        # Enforce asset requirements only for report types that need them.
        if assets_required and not assets:
            dispatcher.utter_message(text="I could not find any valid plate numbers to run the report.")
            return []

        # Fleet summary and similar reports may not require dates. For report
        # types that do require dates, attempt to infer them from the latest
        # message if the slot is still empty.
        if not dates_required:
            start_date = start_date
            end_date = end_date
        elif not start_date:
            latest = tracker.latest_message or {}
            entities = latest.get("entities") or []
            date_values = [
                str(entity.get("value"))
                for entity in entities
                if entity.get("entity") == "date" and entity.get("value")
            ]
            joined: Optional[Text]
            if date_values:
                joined = " ".join(date_values)
            else:
                text = latest.get("text") or ""
                if text:
                    lowered = text.lower()
                    for kw in ["from", "between"]:
                        idx = lowered.find(kw)
                        if idx != -1:
                            text = text[idx:]
                            break
                    joined = text
                else:
                    joined = None

            logger.info("action_run_report: fallback joined_date_text=%r", joined)
            parsed = parse_date_range(joined) if joined else None
            logger.info("action_run_report: fallback parsed_date_range=%r", parsed)
            if parsed:
                start_date = parsed["start"]
                end_date = parsed["end"]
            else:
                end_date = None

        if dates_required and not start_date:
            dispatcher.utter_message(text="I still need a date range before I can run the report.")
            return []

        # Special handling for driver behavior report: requires driver name and dates, but no assets
        driver_id: Optional[str] = None
        if report_type == "driver behavior report":
            if not driver_name:
                dispatcher.utter_message(text="Please provide a driver name for the driver behavior report.")
                return []
            driver_id = get_driver_id_by_name(driver_name)
            if not driver_id:
                dispatcher.utter_message(
                    text=f"I could not find any driver matching '{driver_name}'. Please check the name and try again."
                )
                return []

        results: List[Dict[Text, Any]] = []
        missing_assets: List[Text] = []

        # Debug log to inspect which dates and assets are being used.
        logger.info(
            "Running report: type=%r assets_slot=%r assets=%r start_date=%r end_date=%r",
            report_type,
            assets_slot,
            assets,
            start_date,
            end_date,
        )

        if report_type == "fleet summary report":
            api_result = call_fleet_summary_api()
            results.append({"plate": None, "assetId": None, **api_result})
        elif report_type == "fleet performance summary report":
            api_result = call_fleet_performance_api(start_date, end_date or start_date)
            results.append({"plate": None, "assetId": None, **api_result})
        elif report_type == "utilization report":
            api_result = call_date_based_api(
                endpoint=UTILIZATION_REPORT_ENDPOINT,
                start_date=start_date,
                end_date=end_date or start_date,
                page=REPORT_PAGE,
                size=REPORT_SIZE
            )
            results.append({"plate": None, "assetId": None, **api_result})
        elif report_type == "driver behavior report":
            api_result = call_date_based_api(
                endpoint=DRIVER_BEHAVIOR_REPORT_ENDPOINT,
                start_date=start_date,
                end_date=end_date or start_date,
                page=REPORT_PAGE,
                size=REPORT_SIZE,
                extra_payload={"driverId": driver_id},
            )
            results.append({"plate": None, "assetId": None, **api_result})
        else:
            # Handle other report types that need assets (trips, idle, stop-time, etc.)
            if report_type == "idle time report":
                endpoint = IDLE_REPORT_ENDPOINT
            elif report_type == "trips statistics report":
                endpoint = TRIP_REPORT_ENDPOINT
            elif report_type == "stop time report":
                endpoint = STOP_REPORT_ENDPOINT
            elif report_type == "fuel trip consumption report":
                endpoint = FUEL_CONSUMPTION_ENDPOINT
            elif report_type == "odometer report":
                endpoint = ODOMETER_REPORT_ENDPOINT
            elif report_type == "raw data report":
                endpoint = RAW_DATA_REPORT_ENDPOINT
            elif report_type == "track data report":
                endpoint = TRACK_DATA_REPORT_ENDPOINT
            elif report_type == "over speeding report":
                endpoint = OVER_SPEEDING_REPORT_ENDPOINT
            elif report_type == "temperature & humidity report":
                endpoint = TEMPERATURE_HUMIDITY_REPORT_ENDPOINT
            elif report_type == "weight sensor report":
                endpoint = WEIGHT_SENSOR_REPORT_ENDPOINT
            elif report_type == "commands history report":
                endpoint = COMMANDS_HISTORY_REPORT_ENDPOINT
            elif report_type == "events report":
                endpoint = EVENTS_REPORT_ENDPOINT
            else:
                dispatcher.utter_message(
                    text=f"I don't know how to run the report type '{report_type}'. Please try another report."
                )
                return []

            # Process assets for reports that need them
            for plate in assets:
                asset_id = get_asset_id_by_plate(plate)
                if not asset_id:
                    missing_assets.append(plate)
                    continue
                api_result = call_report_api(asset_id, start_date, end_date, endpoint)
                results.append({"plate": plate, "assetId": asset_id, **api_result})

        messages: List[str] = []
        if results:
            serialized = json.dumps(results, indent=2, default=str)
            # Protect against sending an overly large message to the channel, which can
            # cause streaming errors like 'Chunk too big'. We keep a preview only.
            max_len = 2000
            if len(serialized) > max_len:
                truncated_len = len(serialized) - max_len
                preview = serialized[:max_len] + f"\n... (truncated, {truncated_len} characters omitted)"
            else:
                preview = serialized
            dispatcher.utter_message(
                text=f"Finished the {report_type}. Here is a preview of the raw data:\n{preview}"
            )
        else:
            messages.append("I could not fetch any data because no matching assets were found.")

        if missing_assets:
            messages.append(
                "No asset id was found for: " + ", ".join(sorted(set(missing_assets)))
            )

        if messages:
            dispatcher.utter_message(text=" \n".join(messages))

        # Clear all form slots after report completion to allow fresh start for next report
        # Also deactivate the form so the next query starts fresh
        return [
            SlotSet("assets", None),
            SlotSet("date_range", None),
            SlotSet("start_date", None),
            SlotSet("end_date", None),
            SlotSet("driver", None),
            SlotSet("assets_display", None),
            SlotSet("confirmed_assets", None),
            SlotSet("confirmed_assets_display", None),
            SlotSet("report_type", None),  # Clear report_type for fresh start
            ActiveLoop(None),  # Explicitly deactivate the form
        ]


def call_mongo_agent(user_query: Text, asset_id: Optional[str] = None, plate_number: Optional[str] = None) -> Dict[Text, Any]:
    """
    Call the MongoDB agent to answer textual fleet queries.
    
    Args:
        user_query: The user's query text
        asset_id: Optional asset ID if available
        plate_number: Optional plate number if available
        
    Returns:
        Dictionary containing the agent's response or error information
    """
    try:
        # TODO: Replace this with your actual MongoDB agent endpoint/function
        # This is a placeholder that you should replace with your actual MongoDB agent implementation
        
        # Option 1: If you have a MongoDB agent API endpoint
        # url = "YOUR_MONGODB_AGENT_ENDPOINT_URL"
        # payload = {
        #     "query": user_query,
        #     "asset_id": asset_id,
        #     "plate_number": plate_number,
        #     "sub_tenant_id": SUB_TENANT_ID
        # }
        # headers = {
        #     "Authorization": AUTHORIZATION,
        #     "Content-Type": "application/json"
        # }
        # response = requests.post(url, json=payload, headers=headers, timeout=60)
        # response.raise_for_status()
        # return {
        #     "status": response.status_code,
        #     "body": response.json() if response.content else {},
        #     "answer": response.json().get("answer") or response.json().get("response") or ""
        # }
        
        # Option 2: If you have a direct MongoDB agent function/class
        # from your_mongo_agent_module import MongoAgent
        # agent = MongoAgent(MONGO_URI, MONGO_DB)
        # answer = agent.query(user_query, asset_id=asset_id, plate_number=plate_number)
        # return {
        #     "status": 200,
        #     "answer": answer
        # }
        
        # Placeholder implementation - replace with your actual MongoDB agent call
        logger.info(f"Calling MongoDB agent with query: {user_query}, asset_id: {asset_id}, plate: {plate_number}")
        
        # For now, return a placeholder response
        # You should replace this with your actual MongoDB agent implementation
        return {
            "status": 200,
            "answer": f"I'm processing your query about {plate_number or 'the vehicle'}. Please implement the MongoDB agent function to get the actual answer.",
            "query": user_query,
            "asset_id": asset_id,
            "plate_number": plate_number
        }
        
    except Exception as exc:
        logger.error(f"MongoDB agent call failed: {exc}", exc_info=True)
        return {
            "status": 500,
            "error": str(exc),
            "answer": "I encountered an error while processing your query. Please try again."
        }


class ActionHandleTextualFleet(Action):
    def name(self) -> Text:
        return "action_handle_textual_fleet"

    async def run(
        self,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any],
    ) -> List[Dict[Text, Any]]:
        """Handle textual fleet information queries using MongoDB agent."""
        try:
            # Normalize input spaces BEFORE any processing
            normalize_input(tracker)
            
            # Get the user's query text
            latest = tracker.latest_message or {}
            user_query = latest.get("text") or ""
            
            if not user_query:
                dispatcher.utter_message(
                    text="I didn't receive your query. Please ask me about vehicle information."
                )
                return []
            
            # CONFLICT RESOLUTION: Check if this is just a vehicle number/date without a meaningful question
            # If so, let ActionPromptReportType handle it instead (to avoid conflict)
            user_query_lower = user_query.lower().strip()
            
            # Check if query contains question words or action verbs (indicating a textual fleet query)
            question_words = ['what', 'where', 'when', 'who', 'why', 'how', 'which', 'show', 'list', 'get', 
                            'tell', 'give', 'find', 'display', 'retrieve', 'fetch', 'is', 'are', 'was', 'were']
            action_verbs = ['show', 'list', 'get', 'tell', 'give', 'find', 'display', 'retrieve', 'fetch', 
                          'check', 'see', 'view', 'look', 'search']
            
            has_question_word = any(word in user_query_lower for word in question_words)
            has_action_verb = any(verb in user_query_lower for verb in action_verbs)
            
            # Extract assets and dates to check if query is just a vehicle/date
            entities = latest.get("entities") or []
            has_asset_entity = any(entity.get("entity") == "asset" for entity in entities)
            has_date_entity = any(entity.get("entity") == "date" for entity in entities)
            
            # Try to extract assets/dates from text
            extracted_assets = extract_assets(user_query) if not has_asset_entity else []
            parsed_date = parse_date_range(user_query) if not has_date_entity else None
            
            has_asset = has_asset_entity or bool(extracted_assets)
            has_date = has_date_entity or bool(parsed_date)
            
            # If query is just a vehicle number/date without question/action words, it's not a textual fleet query
            # Let ActionPromptReportType handle it instead
            if (has_asset or has_date) and not has_question_word and not has_action_verb:
                logger.info(f"action_handle_textual_fleet: Query is just vehicle/date without question. Skipping MongoDB agent. Query: {user_query}")
                # Return empty to let other actions (like ActionPromptReportType) handle it
                return []
            
            # Extract asset/vehicle from entities or message text
            entities = latest.get("entities") or []
            asset_values = [
                str(entity.get("value"))
                for entity in entities
                if entity.get("entity") == "asset" and entity.get("value")
            ]
            
            # If no asset in entities, try extracting from text
            if not asset_values:
                extracted_assets = extract_assets(user_query)
                if extracted_assets:
                    asset_values = extracted_assets
            
            plate_number = asset_values[0] if asset_values else None
            asset_id = None
            
            # Try to get asset ID if plate number is available
            if plate_number:
                asset_id = get_asset_id_by_plate(plate_number)
                if not asset_id:
                    logger.warning(f"Could not find asset ID for plate: {plate_number}")
            
            # Call MongoDB agent with the user query
            logger.info(
                f"Processing textual fleet query: query={user_query}, plate={plate_number}, asset_id={asset_id}"
            )
            
            agent_response = call_mongo_agent(
                user_query=user_query,
                asset_id=asset_id,
                plate_number=plate_number
            )
            
            # Extract the answer from the response
            if "error" in agent_response:
                answer = agent_response.get("answer") or agent_response.get("error", "I encountered an error while processing your query.")
                dispatcher.utter_message(text=answer)
            elif "answer" in agent_response:
                answer = agent_response["answer"]
                dispatcher.utter_message(text=answer)
            else:
                # Fallback: return the full response if answer field is not present
                response_text = json.dumps(agent_response, indent=2, default=str)
                dispatcher.utter_message(
                    text=f"Here is the information:\n{response_text}"
                )
            
            return []
            
        except Exception as exc:
            logger.error("action_handle_textual_fleet: Error occurred: %s", exc, exc_info=True)
            dispatcher.utter_message(
                text="I encountered an error while processing your query. Please try again."
            )
            return []


class ActionPromptReportType(Action):
    def name(self) -> Text:
        return "action_prompt_report_type"

    async def run(
        self,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any],
    ) -> List[Dict[Text, Any]]:
        """Prompt user to provide report type when they provide vehicle/date without report type and form is not active."""
        # Check if form is not active
        active_loop = tracker.active_loop
        logger.info(f"action_prompt_report_type: Called with active_loop={active_loop}")
        
        if active_loop is None:
            # Form is not active, check if user provided asset or date
            latest = tracker.latest_message or {}
            entities = latest.get("entities") or []
            text = latest.get("text") or ""
            latest_intent = latest.get("intent", {}).get("name", "")
            
            # Skip system intents (request_fleet_info)
            system_intents = {"request_fleet_info"}
            if latest_intent in system_intents:
                return []
            
            # CONFLICT RESOLUTION: Check if this looks like a textual fleet query
            # If query has question words or action verbs, it's likely a textual fleet query, not a report request
            # Don't prompt for report type in this case - let ActionHandleTextualFleet handle it
            text_lower = text.lower().strip() if text else ""
            question_words = ['what', 'where', 'when', 'who', 'why', 'how', 'which', 'show', 'list', 'get', 
                            'tell', 'give', 'find', 'display', 'retrieve', 'fetch', 'is', 'are', 'was', 'were']
            action_verbs = ['show', 'list', 'get', 'tell', 'give', 'find', 'display', 'retrieve', 'fetch', 
                          'check', 'see', 'view', 'look', 'search']
            
            has_question_word = any(word in text_lower for word in question_words)
            has_action_verb = any(verb in text_lower for verb in action_verbs)
            
            # If query looks like a textual fleet query (has question/action words) and no "report" word,
            # don't prompt for report type - let textual fleet action handle it
            if (has_question_word or has_action_verb) and "report" not in text_lower:
                logger.info(f"action_prompt_report_type: Query looks like textual fleet query. Skipping report type prompt. Query: {text}")
                return []
            
            logger.info(f"action_prompt_report_type: text='{text}', intent='{latest_intent}', entities={entities}")
            
            # Check for asset entities
            has_asset_entity = any(
                entity.get("entity") == "asset" and entity.get("value")
                for entity in entities
            )
            
            # Also try to extract assets from text directly (in case NLU didn't classify as entity)
            has_asset_text = False
            if text:
                # First try extract_assets function (this handles most cases)
                if not has_asset_entity:
                    extracted = extract_assets(text)
                    if extracted:
                        has_asset_text = True
                        logger.info(f"action_prompt_report_type: extract_assets found: {extracted}")
                
                # Always check for common vehicle patterns as well (fallback and additional check)
                # This ensures we catch cases like "3688 fhd" even if extract_assets doesn't work
                if not has_asset_text and not has_asset_entity:
                    # More specific patterns to avoid false positives
                    # Handle "vehicle" at beginning OR end, and "plate" at beginning
                    vehicle_patterns = [
                        r'\bvehicle\s+[A-Za-z0-9\s-]{2,}',  # "vehicle 390", "vehicle 3688 fhd"
                        r'[A-Za-z0-9\s-]{2,}\s+vehicle\b',  # "3688 fhd vehicle", "390 vehicle"
                        r'\bplate\s+[A-Za-z0-9\s-]{2,}',    # "plate 390"
                        r'^[A-Za-z0-9\s-]{2,15}$',          # Just "390" or "3688 fhd" (increased limit for longer IDs)
                    ]
                    # Also check if text is just numbers or alphanumeric (likely a vehicle ID)
                    text_clean = text.strip().upper()
                    # Remove common words that might interfere ("also", "and", "for", "of", etc.)
                    text_for_check = re.sub(r'\b(also|and|for|of|the|a|an)\b', '', text_clean, flags=re.IGNORECASE).strip()
                    
                    # Check if it's just numbers (like "390", "1234") - these are likely vehicle IDs
                    if re.match(r'^\d{2,15}$', text_clean):
                        has_asset_text = True
                        logger.info(f"action_prompt_report_type: Detected numeric vehicle ID: {text_clean}")
                    # Check if it's a simple vehicle identifier (numbers, letters, spaces, hyphens, 2-15 chars)
                    # This handles "3688 fhd", "ABC-123", etc.
                    # First check text_for_check (with common words removed)
                    elif text_for_check and re.match(r'^[A-Z0-9\s-]{2,15}$', text_for_check) and not any(word in text_for_check.lower() for word in ['report', 'this', 'last', 'next', 'year', 'month', 'week', 'day', 'quarter']):
                        has_asset_text = True
                        logger.info(f"action_prompt_report_type: Detected alphanumeric vehicle ID (cleaned): {text_for_check}")
                    # Also check the original text_clean (before removing common words) for patterns like "3688 fhd"
                    elif text_clean and re.match(r'^[A-Z0-9\s-]{2,15}$', text_clean) and not any(word in text_clean.lower() for word in ['report', 'this', 'last', 'next', 'year', 'month', 'week', 'day', 'quarter']):
                        has_asset_text = True
                        logger.info(f"action_prompt_report_type: Detected alphanumeric vehicle ID (original): {text_clean}")
                    # Explicit check for patterns like "3688 fhd" - number followed by letters
                    elif re.match(r'^\d+\s+[A-Z]+$', text_clean) or re.match(r'^[A-Z]+\s+\d+$', text_clean):
                        has_asset_text = True
                        logger.info(f"action_prompt_report_type: Detected number+letter pattern: {text_clean}")
                    else:
                        # Try regex patterns as fallback
                        for pattern in vehicle_patterns:
                            if re.search(pattern, text, re.IGNORECASE):
                                has_asset_text = True
                                logger.info(f"action_prompt_report_type: Matched vehicle pattern: {pattern}")
                                break
            
            # Check for date entities
            has_date_entity = any(
                entity.get("entity") == "date" and entity.get("value")
                for entity in entities
            )
            
            # Also check if text looks like a date (in case NLU didn't classify as entity)
            has_date_text = False
            if text and not has_date_entity:
                # Try parsing the text as a date
                parsed_date = parse_date_range(text)
                if parsed_date:
                    has_date_text = True
            
            has_asset = has_asset_entity or has_asset_text
            has_date = has_date_entity or has_date_text
            
            # Check if report type was provided in entities or slot
            has_report_type_entity = any(
                entity.get("entity") == "report_type" and entity.get("value")
                for entity in entities
            )
            has_report_type_slot = tracker.get_slot("report_type") is not None
            
            # Check if current intent is a report intent
            is_report_intent = latest_intent.startswith("request_") and latest_intent.endswith("_report")
            
            # Check if intent is provide_report_detail with report_type entity (user providing report type)
            is_providing_report_type = (
                latest_intent == "provide_report_detail" and 
                has_report_type_entity
            )
            
            # IMPORTANT: If user provides just a vehicle number or date (like "390" or "last month")
            # WITHOUT a report type in the CURRENT message, we should prompt for report type
            # even if there's a stale report_type slot from a previous report.
            # This handles the case where user just finished a report and wants to start a new one.
            # We only skip prompting if:
            # 1. User explicitly provided report_type in current message (entity), OR
            # 2. User's intent is a report intent (request_*_report), OR
            # 3. User is providing report type detail (provide_report_detail with report_type entity)
            # We DON'T check has_report_type_slot because it might be stale from previous report
            
            # Log detection results
            logger.info(f"action_prompt_report_type: text='{text}', has_asset={has_asset}, has_date={has_date}, has_report_type_entity={has_report_type_entity}, has_report_type_slot={has_report_type_slot}, is_report_intent={is_report_intent}, is_providing_report_type={is_providing_report_type}")
            
            # Check if text contains "report" word - if so, it's likely a report request
            # This handles cases like "temperature report" that might not be classified correctly
            if text_lower and "report" in text_lower:
                # Try to extract and normalize the report type from the text
                normalised_report_type = normalise_report_type(text)
                if normalised_report_type:
                    # We found a valid report type, set it and activate the form
                    logger.info(f"action_prompt_report_type: Detected report type '{normalised_report_type}' from text '{text}'. Activating form.")
                    # Set the report type slot and activate the form
                    # The form will then ask for required slots (assets, dates, etc.)
                    return [
                        SlotSet("report_type", normalised_report_type),
                        ActiveLoop("report_form"),
                    ]
                else:
                    # Text contains "report" but we couldn't extract the type
                    # This might be a misclassified report request - prompt user to clarify
                    logger.info(f"action_prompt_report_type: Detected report request (contains 'report') but couldn't extract type. Intent: {latest_intent}, Text: {text}")
                    # Prompt user to select a report type
                    dispatcher.utter_message(
                        response="utter_ask_report_form_report_type"
                    )
                    return [ActiveLoop(None)]
            
            # If user provided asset or date but no report type in CURRENT message, prompt for report type
            # Note: We don't check has_report_type_slot because it might be stale from previous report
            if (has_asset or has_date) and not has_report_type_entity and not is_report_intent and not is_providing_report_type:
                logger.info("action_prompt_report_type: Prompting user for report type")
                dispatcher.utter_message(
                    response="utter_ask_report_form_report_type"
                )
                # Explicitly ensure form is not activated
                return [ActiveLoop(None)]
            else:
                logger.info("action_prompt_report_type: Not prompting (conditions not met)")
                # If we can't handle this query, ask for clarification
                if text and text.strip():
                    logger.warning(f"action_prompt_report_type: Cannot handle query: '{text}', intent: '{latest_intent}'. Asking for clarification.")
                    dispatcher.utter_message(
                        text="I can help you with fleet reports and fleet information. Please specify what you need - for example, 'trips report for vehicle 390' or 'what is the location of vehicle 390?'"
                    )
                    return []
        
        return []


