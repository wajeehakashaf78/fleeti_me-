"""
Data models for Fleet Analytics Chatbot
Defines Pydantic models for request/response validation
"""

from pydantic import BaseModel, Field
from typing import Optional, List


class ChatRequest(BaseModel):
    """Request model for chat endpoint"""
    sub_tenant_id: str = Field(..., description="Sub-tenant identifier")
    session_id: str = Field(..., description="Session identifier")
    mongo_db: str = Field(..., description="MongoDB database name")
    user_input: str = Field(..., description="User's message input")


class PreRequisites(BaseModel):
    """Prerequisites for a report request"""
    asset_plate_numbers: Optional[List[str]] = Field(None, alias="asset_plate_number(s)")
    group_names: Optional[List[str]] = Field(None, alias="group_name(s)")
    driver_names: Optional[List[str]] = Field(None, alias="driver_name(s)")
    date_range: Optional[str] = Field(None, description="Format: start_date,end_date")
    geofence_names: Optional[List[str]] = Field(None, alias="geofence_name(s)")
    # Duty Hour report only. duty_type: "on" (default) or "off"; the duty window
    # times default to 10:00 -> 19:00 local. The server applies the off-duty swap
    # and the local->UTC conversion (never the agent).
    duty_type: Optional[str] = Field(None, description="DutyHour only: 'on' (default) or 'off'")
    duty_start_time: Optional[str] = Field(None, description="DutyHour only: window start time, 24h HH:MM (default 10:00)")
    duty_end_time: Optional[str] = Field(None, description="DutyHour only: window end time, 24h HH:MM (default 19:00)")

    class Config:
        populate_by_name = True


class LLMResponse(BaseModel):
    """Response from LLM agent"""
    type: str = Field(..., description="Report type or 'invalid'")
    pre_req: Optional[PreRequisites] = Field(None, description="Report prerequisites")
    message: str = Field(default="", description="Message to user about missing prerequisites")
