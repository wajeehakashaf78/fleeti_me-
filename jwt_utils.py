import base64
import json
from typing import Any, Dict
from urllib.parse import urlparse


def _b64url_decode(data: str) -> bytes:
    """Decode base64url string with padding."""
    padded = data + "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(padded.encode("utf-8"))


def decode_jwt_no_verify(token: str) -> Dict[str, Any]:
    """
    Decode JWT without verifying signature.
    Accepts raw token or 'Bearer <token>' format.
    """
    if not token:
        return {}
    token = token.strip()
    if token.lower().startswith("bearer "):
        token = token.split(" ", 1)[1].strip()
    parts = token.split(".")
    if len(parts) < 2:
        return {}
    payload_b64 = parts[1]
    try:
        payload_bytes = _b64url_decode(payload_b64)
        return json.loads(payload_bytes.decode("utf-8"))
    except Exception:
        return {}


def extract_db_from_url(url: str) -> str | None:
    """
    Extract db name from a URL or hostname: text before the first dot.
    e.g. "https://ihcc.tracking.me" or "ihcc.tracking.me" -> "ihcc"
    """
    if not url:
        return None
    try:
        hostname = urlparse(url).hostname if "://" in url else url
        part = (hostname or "").split(".")[0]
        return part if part else None
    except Exception:
        return None


def extract_db_and_sub_tenant(payload: Dict[str, Any]) -> tuple[str | None, str | None]:
    """
    Extract db name and sub_tenant_id from decoded JWT payload.
    db_name is derived from SubTenantId (text before first dot).
    """
    sub_tenant_id = payload.get("SubTenantId") or payload.get("sub_tenant_id")
    db_name = extract_db_from_url(sub_tenant_id) if sub_tenant_id else None
    return db_name, sub_tenant_id
