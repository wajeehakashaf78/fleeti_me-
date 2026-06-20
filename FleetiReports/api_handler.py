"""
API Handler for Fleet Analytics Chatbot
Handles external API calls to fetch reports
"""

from typing import Dict, Any, Optional
from datetime import datetime
import logging
import httpx
from .config import settings

logger = logging.getLogger(__name__)


def print(*args: Any, **kwargs: Any) -> None:
    logger.debug(" ".join(str(arg) for arg in args))


class APIHandler:
    """Handles external API calls"""
    
    def __init__(
        self,
        base_url: Optional[str] = None,
        access_token: Optional[str] = None,
        timeout: float = 30.0,
        verify_ssl: Optional[bool] = None,
        ca_bundle: Optional[str] = None
    ):
        """Initialize API handler"""
        self.base_url = base_url or settings.BASE_API_URL
        self.access_token = (access_token or settings.ACCESS_TOKEN or "").strip()
        if self.access_token.lower().startswith("bearer "):
            self.access_token = self.access_token.split(" ", 1)[1].strip()
        self.timeout = timeout  # seconds timeout
        self.verify_ssl = settings.REPORTS_API_VERIFY_SSL if verify_ssl is None else bool(verify_ssl)
        self.ca_bundle = (ca_bundle or settings.REPORTS_API_CA_BUNDLE or "").strip() or None
        # `verify` accepts bool or path to CA bundle.
        self.http_verify = self.ca_bundle if self.ca_bundle else self.verify_ssl
        self.default_page = 1
        self.default_size = 10

    def _add_pagination(self, payload: Dict[str, Any], page: int = 1, size: int = 10) -> Dict[str, Any]:
        payload["page"] = page
        payload["size"] = size
        return payload
    
    def _get_headers(self) -> Dict[str, str]:
        """Get headers for API requests"""
        return {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json"
        }
    
    def _format_date_to_iso(self, date_str: str) -> str:
        """
        Convert date string to ISO 8601 format
        
        Args:
            date_str: Date string in various formats
            
        Returns:
            ISO 8601 formatted date string
        """
        # For now, return as-is. In production, you'd parse and convert
        # This is a placeholder for date formatting logic
        try:
            # Try to parse common date formats
            # Add your date parsing logic here based on expected formats
            return date_str
        except Exception:
            return date_str
    
    async def call_report_api(
        self, 
        endpoint: str, 
        payload: Dict[str, Any],
        report_type: Optional[str] = None,
        request_only_log: bool = False
    ) -> Dict[str, Any]:
        """
        Call report API endpoint
        
        Args:
            endpoint: API endpoint path (e.g., '/fetch-dates', '/fleet-summary')
            payload: Request payload
            
        Returns:
            API response data
        """
        report_label = report_type or payload.get("Type") or endpoint
        try:
            url = f"{self.base_url}{endpoint}"

            logger.info("📡 report API request | %s | POST %s | payload=%s",
                        report_label, url, str(payload)[:1000])

            async with httpx.AsyncClient(timeout=self.timeout, verify=self.http_verify) as client:
                response = await client.post(
                    url,
                    json=payload,
                    headers=self._get_headers()
                )

                response.raise_for_status()

                response_data = response.json()

                logger.info("📡 report API response | %s | HTTP %s | success",
                            report_label, response.status_code)

                return {
                    "success": True,
                    "status_code": response.status_code,
                    "data": response_data
                }

        except httpx.HTTPStatusError as e:
            logger.warning("📡 report API error | %s | HTTP %s | %s",
                           report_label, e.response.status_code, str(e)[:300])
            return {
                "success": False,
                "error": f"HTTP error: {e.response.status_code}",
                "details": str(e)
            }
        except httpx.RequestError as e:
            logger.warning("📡 report API error | %s | request error | %s", report_label, str(e)[:300])
            return {
                "success": False,
                "error": "Request error",
                "details": str(e)
            }
        except Exception as e:
            logger.warning("📡 report API error | %s | unexpected | %s", report_label, str(e)[:300])
            return {
                "success": False,
                "error": "Unexpected error",
                "details": str(e)
            }
    
    async def fetch_trip_report(
        self,
        asset_ids: str,
        start_date: str,
        end_date: str,
        time_zone: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Fetch Trip/Fleet Statistics Report"""
        payload: Dict[str, Any] = {
            "StartDate": start_date,
            "EndDate": end_date,
            "AssetIds": asset_ids,
            "Type": "Trip",
        }
        if time_zone:
            payload["TimeZone"] = time_zone
        return await self.call_report_api("/fetch-dates", payload)
    
    async def fetch_fleet_summary(self, asset_ids: str, page: int = 1, size: int = 10) -> Dict[str, Any]:
        """Fetch Fleet Summary Report"""
        payload = self._add_pagination({"AssetIds": asset_ids}, page=page, size=size)
        return await self.call_report_api(
            "/fleet-summary",
            payload,
            report_type="FleetSummary",
            request_only_log=True
        )
    
    async def fetch_fleet_performance_summary(
        self, 
        asset_ids: str, 
        start_date: str, 
        end_date: str,
        page: int = 1,
        size: int = 10
    ) -> Dict[str, Any]:
        """Fetch Fleet Performance Summary Report"""
        payload = self._add_pagination({
            "StartDate": start_date,
            "EndDate": end_date,
            "AssetIds": asset_ids
        }, page=page, size=size)
        return await self.call_report_api(
            "/fleet-performance",
            payload,
            report_type="FleetPerformanceSummary",
            request_only_log=True
        )
    
    async def fetch_sim_report(
        self, 
        asset_ids: str, 
        start_date: str, 
        end_date: str,
        page: int = 1,
        size: int = 10
    ) -> Dict[str, Any]:
        """Fetch SIM Report"""
        payload = self._add_pagination({
            "startDate": start_date,
            "endDate": end_date,
            "assetId": asset_ids
        }, page=page, size=size)
        return await self.call_report_api(
            "/sim",
            payload,
            report_type="SIM",
            request_only_log=True
        )
    
    async def fetch_utilization_report(
        self, 
        start_date: str, 
        end_date: str,
        page: int = 1,
        size: int = 10
    ) -> Dict[str, Any]:
        """Fetch Utilization/Work Hour Report"""
        payload = self._add_pagination({
            "StartDate": start_date,
            "EndDate": end_date
        }, page=page, size=size)
        return await self.call_report_api(
            "/utilization",
            payload,
            report_type="Utilization",
            request_only_log=True
        )
    
    async def fetch_generic_report(
        self,
        report_type: str,
        asset_ids: Optional[str] = None,
        driver_ids: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        time_zone: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Fetch generic report using fetch-dates endpoint
        
        Args:
            report_type: Type of report (e.g., 'FuelConsumption', 'Odometer')
            asset_ids: Comma-separated asset IDs
            driver_ids: Comma-separated driver IDs
            start_date: Start date in ISO format
            end_date: End date in ISO format
            
        Returns:
            API response
        """
        payload = {"Type": report_type}
        
        if asset_ids:
            payload["AssetIds"] = asset_ids
        if driver_ids:
            # Backend expects driver identifiers in AssetIds for driving behavior reports.
            if report_type in ("DrivingBehaviour", "DriverBehaviour", "DriverBehavior"):
                payload["AssetIds"] = driver_ids
                payload.pop("DriverIds", None)
            else:
                payload["DriverIds"] = driver_ids
        if start_date:
            payload["StartDate"] = start_date
        if end_date:
            payload["EndDate"] = end_date
        if time_zone:
            payload["TimeZone"] = time_zone

        return await self.call_report_api("/fetch-dates", payload)


# Global API handler instance
api_handler = APIHandler()
