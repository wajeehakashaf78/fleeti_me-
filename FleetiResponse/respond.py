import re
import logging
from datetime import datetime, timezone, timedelta
from typing import Any, Optional

from dateutil import parser as dtparser

logger = logging.getLogger(__name__)


_TEMPORAL_KEY_PARTS = (
    "timestamp",
    "time_stamp",
    "timefield",
    "datetime",
    "date_time",
    "created_at",
    "updated_at",
    "deleted_at",
    "start_at",
    "end_at",
    "started_at",
    "ended_at",
    "recorded_at",
    "received_at",
    "generated_at",
    "event_time",
    "device_time",
    "server_time",
    "gps_time",
    "start_time",
    "end_time",
    "last_time",
    "first_time",
)

_DURATION_KEY_PARTS = (
    "duration",
    "elapsed",
    "idle_time",
    "drive_time",
    "driving_time",
    "stop_time",
    "parking_time",
)


def _parse_user_utc_offset(user_time_zone: Optional[str]) -> Optional[timezone]:
    """
    Parse timezone offsets like +5, +5:00, UTC+5, or UTC +5:00.
    Returns None when no valid user timezone is provided.
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

    return timezone(timedelta(hours=hours * sign, minutes=minutes * sign))


def _is_temporal_key(key: Any) -> bool:
    if not isinstance(key, str):
        return False
    normalized = key.strip().lower()
    compact = re.sub(r"[^a-z0-9]", "", normalized)

    duration_parts = set(_DURATION_KEY_PARTS)
    duration_parts.update(re.sub(r"[^a-z0-9]", "", part) for part in _DURATION_KEY_PARTS)
    if any(part and (part in normalized or part in compact) for part in duration_parts):
        return False

    temporal_parts = set(_TEMPORAL_KEY_PARTS)
    temporal_parts.update(re.sub(r"[^a-z0-9]", "", part) for part in _TEMPORAL_KEY_PARTS)
    return any(part and (part in normalized or part in compact) for part in temporal_parts)


def _format_local_datetime(dt: datetime, user_tz: timezone) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    local_dt = dt.astimezone(user_tz)
    timespec = "milliseconds" if local_dt.microsecond else "seconds"
    return local_dt.isoformat(timespec=timespec)


def _convert_temporal_value(value: Any, user_tz: timezone) -> Any:
    if isinstance(value, datetime):
        return _format_local_datetime(value, user_tz)

    if not isinstance(value, str):
        return value

    text = value.strip()
    if not text:
        return value

    # Only convert date-time strings, not date-only values.
    if not re.search(r"\d{4}-\d{2}-\d{2}[T\s]\d{2}:\d{2}", text):
        return value

    try:
        parsed = dtparser.isoparse(text)
    except Exception:
        try:
            parsed = dtparser.parse(text)
        except Exception:
            return value

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return _format_local_datetime(parsed, user_tz)


def convert_query_response_times_for_user(value: Any, user_time_zone: Optional[str]) -> Any:
    """
    Return a copy of a Mongo query response with UTC date-time fields converted
    to the user's timezone for human-readable text generation.
    """
    user_tz = _parse_user_utc_offset(user_time_zone)
    if user_tz is None:
        return value

    def convert(node: Any, key: Any = None) -> Any:
        if isinstance(node, list):
            return [convert(item, key=None) for item in node]

        if isinstance(node, dict):
            return {k: convert(v, key=k) for k, v in node.items()}

        if isinstance(node, datetime):
            return _convert_temporal_value(node, user_tz)

        if _is_temporal_key(key):
            return _convert_temporal_value(node, user_tz)

        return node

    return convert(value)

