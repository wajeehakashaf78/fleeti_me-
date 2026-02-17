"""
API Handler for Fleet Analytics Chatbot
Handles external API calls to fetch reports
"""

from typing import Dict, Any, Optional
from datetime import datetime
import httpx
from .config import settings


class APIHandler:
    """Handles external API calls"""
    
    def __init__(
        self,
        base_url: Optional[str] = None,
        access_token: Optional[str] = None,
        timeout: float = 30.0
    ):
        """Initialize API handler"""
        self.base_url = base_url or settings.BASE_API_URL
        self.access_token = (access_token or settings.ACCESS_TOKEN or "").strip()
        if self.access_token.lower().startswith("bearer "):
            self.access_token = self.access_token.split(" ", 1)[1].strip()
        self.timeout = timeout  # seconds timeout
    
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
        payload: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Call report API endpoint
        
        Args:
            endpoint: API endpoint path (e.g., '/fetch-dates', '/fleet-summary')
            payload: Request payload
            
        Returns:
            API response data
        """
        try:
            url = f"{self.base_url}{endpoint}"
            
            print(f"\n--- External API Call ---")
            print(f"URL: {url}")
            print(f"Method: POST")
            print(f"Headers: Authorization: Bearer {self.access_token[:20]}...")
            print(f"Payload: {payload}")
            
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    url,
                    json=payload,
                    headers=self._get_headers()
                )
                
                response.raise_for_status()
                
                response_data = response.json()
                
                print(f"\n--- API Response ---")
                print(f"Status Code: {response.status_code}")
                print(f"Response Data: {response_data}")
                
                return {
                    "success": True,
                    "status_code": response.status_code,
                    "data": response_data
                }
                
        except httpx.HTTPStatusError as e:
            print(f"\n--- API Error ---")
            print(f"HTTP Status Error: {e.response.status_code}")
            print(f"Response: {e.response.text}")
            return {
                "success": False,
                "error": f"HTTP error: {e.response.status_code}",
                "details": str(e)
            }
        except httpx.RequestError as e:
            print(f"\n--- API Error ---")
            print(f"Request Error: {str(e)}")
            return {
                "success": False,
                "error": "Request error",
                "details": str(e)
            }
        except Exception as e:
            print(f"\n--- API Error ---")
            print(f"Unexpected Error: {str(e)}")
            return {
                "success": False,
                "error": "Unexpected error",
                "details": str(e)
            }
    
    async def fetch_trip_report(
        self, 
        asset_ids: str, 
        start_date: str, 
        end_date: str
    ) -> Dict[str, Any]:
        """Fetch Trip/Fleet Statistics Report"""
        payload = {
            "StartDate": start_date,
            "EndDate": end_date,
            "AssetIds": asset_ids,
            "Type": "Trip"
        }
        return await self.call_report_api("/fetch-dates", payload)
    
    async def fetch_fleet_summary(self, asset_ids: str) -> Dict[str, Any]:
        """Fetch Fleet Summary Report"""
        payload = {"AssetIds": asset_ids}
        return await self.call_report_api("/fleet-summary", payload)
    
    async def fetch_fleet_performance_summary(
        self, 
        asset_ids: str, 
        start_date: str, 
        end_date: str
    ) -> Dict[str, Any]:
        """Fetch Fleet Performance Summary Report"""
        payload = {
            "StartDate": start_date,
            "EndDate": end_date,
            "AssetIds": asset_ids
        }
        return await self.call_report_api("/fleet-performance-summary", payload)
    
    async def fetch_sim_report(
        self, 
        asset_ids: str, 
        start_date: str, 
        end_date: str
    ) -> Dict[str, Any]:
        """Fetch SIM Report"""
        payload = {
            "StartDate": start_date,
            "EndDate": end_date,
            "AssetIds": asset_ids
        }
        return await self.call_report_api("/sim", payload)
    
    async def fetch_utilization_report(
        self, 
        start_date: str, 
        end_date: str
    ) -> Dict[str, Any]:
        """Fetch Utilization/Work Hour Report"""
        payload = {
            "StartDate": start_date,
            "EndDate": end_date
        }
        return await self.call_report_api("/utilization", payload)
    
    async def fetch_generic_report(
        self, 
        report_type: str,
        asset_ids: Optional[str] = None,
        driver_ids: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None
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
            payload["DriverIds"] = driver_ids
        if start_date:
            payload["StartDate"] = start_date
        if end_date:
            payload["EndDate"] = end_date
        
        return await self.call_report_api("/fetch-dates", payload)


# Global API handler instance
api_handler = APIHandler()
