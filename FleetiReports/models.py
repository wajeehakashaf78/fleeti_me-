"""
Data models for Fleet Analytics Chatbot
Defines Pydantic models for request/response validation
"""

from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any


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
    
    class Config:
        populate_by_name = True


class LLMResponse(BaseModel):
    """Response from LLM agent"""
    type: str = Field(..., description="Report type or 'invalid'")
    pre_req: Optional[PreRequisites] = Field(None, description="Report prerequisites")
    message: str = Field(default="", description="Message to user about missing prerequisites")


class AssetInfo(BaseModel):
    """Asset information from MongoDB"""
    asset_id: str = Field(..., alias="_id")
    plate_number: Optional[str] = None
    
    class Config:
        populate_by_name = True


class DriverInfo(BaseModel):
    """Driver information from MongoDB"""
    driver_id: str
    driver_name: str
    assignment_id: Optional[str] = None


class APIPayload(BaseModel):
    """Generic API payload model"""
    StartDate: Optional[str] = None
    EndDate: Optional[str] = None
    AssetIds: Optional[str] = None
    DriverIds: Optional[str] = None
    Type: Optional[str] = None


class ChatResponse(BaseModel):
    """Response model for chat endpoint"""
    status: str = Field(..., description="success or error")
    llm_response: Optional[LLMResponse] = None
    mongodb_query_result: Optional[Dict[str, Any]] = None
    api_response: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
