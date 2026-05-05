import os
import re
import json
import logging
from datetime import datetime, timezone, timedelta
from typing import Any, Optional

from dotenv import load_dotenv
from dateutil import parser as dtparser
from openai import OpenAI

# Load API key from .env
load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
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


def _choice_text(response: Any) -> str:
    if not getattr(response, "choices", None):
        return ""
    message = getattr(response.choices[0], "message", None)
    return (getattr(message, "content", None) or "").strip()


def _response_debug_summary(response: Any) -> str:
    if not getattr(response, "choices", None):
        return "choices=0"
    finish_reason = getattr(response.choices[0], "finish_reason", None)
    usage = getattr(response, "usage", None)
    return f"finish_reason={finish_reason}, usage={usage}"


def _fallback_human_response(db_response: str) -> str:
    """
    Last-resort formatter so the API never returns a blank fleet response.
    It is intentionally simple and only used when the LLM returns empty text.
    """
    try:
        payload = json.loads(db_response)
    except Exception:
        return "I found data for your request, but I could not format it clearly right now."

    rows = payload if isinstance(payload, list) else [payload]
    rows = [row for row in rows if isinstance(row, dict)]
    if not rows:
        return "I couldn't find any data matching your request."

    row = rows[0]
    plate = row.get("plate_number") or row.get("plateNumber") or row.get("vehicle") or "the vehicle"
    lat = row.get("latitude")
    lon = row.get("longitude")
    timestamp = row.get("timestamp") or row.get("created_at") or row.get("createdAt")
    speed = row.get("speed")
    ignition = row.get("ignition_status") or row.get("ignitionStatus")

    parts = [f"I found the latest data for {plate}."]
    if lat is not None and lon is not None:
        parts.append(f"Location: latitude {lat}, longitude {lon}.")
        parts.append(f"Google Maps: https://www.google.com/maps/search/?api=1&query={lat},{lon}")
    if timestamp is not None:
        parts.append(f"Time: {timestamp}.")
    if speed is not None:
        parts.append(f"Speed: {speed} km/h.")
    if ignition is not None:
        parts.append(f"Ignition: {ignition}.")

    return " ".join(parts)


def generate_llm_response(user_input: str, refined_input: str, db_response: str) -> str:
    """
    Generate a natural language answer for the user based on their question,
    a refined version of it, and a database query response.

    Args:
        user_input: Original user question as asked.
        refined_input: Contextually complete version of the user question.
        db_response: Raw data or output returned by the database query.

    Returns:
        str: A human-readable, natural language response.
    """
    prompt = f"""
You are a helpful AI assistant in a fleet management system.
You will receive:
1. The user's original question
2. A refined version of the same question (context-complete)
3. The database's response to that refined question

Your task:
- Write a clear, friendly, human-readable answer.
- Use the database response to directly answer the user's intent.
- If the database response is empty or irrelevant, respond naturally that no relevant data was found.
- Do not expose SQL queries, JSON data, or raw field names.
- If numbers, dates, or vehicle identifiers appear in the database response, present them clearly.
- Keep it short (2-5 sentences) and conversational.
- If there are coordinates in the database response, make a google maps link for the location. Google maps link should be clickable on the FE by the customer. For example: [Google Maps](https://www.google.com/maps?q=21.5854966,39.209455).
- Do not make up random reasons for errors, if the reason is obvious in the data provided to you. Just tell the user that you ran into a problem and starting a new conversation might help.
- Your task is to just translate the database query results based on the user question, do not add any extra fallbacks in the response.
- IMPORTANT LANGUAGE RULE:
  - If the user's original question is in Arabic, the final answer must be in Arabic.
  - Otherwise, answer in English.
  - Keep names, plate numbers, and identifiers unchanged.
- IMPORTANT DISTANCE RULE:
  - All distance-related fields in the database are stored in METERS.
  - Convert all distance values before answering:
    - to the user's requested distance unit when explicitly mentioned in the question, OR
    - to kilometers (km) when no distance unit is requested.
  - Common conversion factors from meters:
    - km = meters / 1000
    - mi = meters / 1609
    - ft = meters * 3.28
    - m = meters (no conversion)
  - Apply this to every distance-like field/value in the provided data.
  - Do NOT convert speed units, it is already stored in kmph.

Input details:
User question: "{user_input}"
Refined question: "{refined_input}"
Database response: {db_response}

Now write your final answer to the user in the required language.
"""

    messages = [
        {"role": "system", "content": "You are a helpful assistant that explains database results in the user's language and does not expose any database IDs in its response."},
        {"role": "user", "content": prompt}
    ]

    model_name = os.getenv("OPENAI_MODEL", "gpt-5-mini")
    for token_budget in (1200, 2400):
        response = client.chat.completions.create(
            model=model_name,
            messages=messages,
            reasoning_effort="low",
            max_completion_tokens=token_budget,
        )
        content = _choice_text(response)
        if content:
            return content
        logger.debug(
            "[HumanResponseLLM] Empty response from %s; %s; max_completion_tokens=%s",
            model_name,
            _response_debug_summary(response),
            token_budget,
        )

    return _fallback_human_response(db_response)


if __name__ == "__main__":
    # Example usage
    user_input = input("Enter user question: ")
    refined_input = input("Enter refined question: ")
    db_response = input("Enter database response: ")

    print("\n--- LLM Response ---")
    print(generate_llm_response(user_input, refined_input, db_response))
