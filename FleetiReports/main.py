"""
Main FastAPI Application for Fleet Analytics Chatbot
Orchestrates the entire workflow
"""

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import asyncio
from typing import Dict, Any

from .models import ChatRequest, ChatResponse, LLMResponse
from .config import settings
from .history_manager import history_manager
from .llm_agent import llm_agent
from .mongo_handler import mongo_handler
from .api_handler import api_handler


# Background task for cleaning up expired sessions
async def cleanup_task():
    """Periodically cleanup expired conversation histories"""
    while True:
        await asyncio.sleep(30)  # Run every 30 seconds
        removed = history_manager.cleanup_expired()
        if removed > 0:
            print(f"Cleaned up {removed} expired sessions")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager for startup/shutdown events"""
    # Startup
    task = asyncio.create_task(cleanup_task())
    print("Fleet Analytics Chatbot started!")
    print(f"History timeout: {settings.HISTORY_TIMEOUT_SECONDS} seconds")
    
    yield
    
    # Shutdown
    task.cancel()
    mongo_handler.close()
    print("Fleet Analytics Chatbot shut down!")


# Create FastAPI app
app = FastAPI(
    title="Fleet Analytics Chatbot",
    description="AI-powered chatbot for fleet analytics reports",
    version="1.0.0",
    lifespan=lifespan
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure this based on your needs
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def parse_date_range(date_range_str: str) -> tuple[str, str]:
    """
    Parse date range string into start and end dates
    
    Args:
        date_range_str: Date range in format "start_date,end_date"
        
    Returns:
        Tuple of (start_date, end_date)
    """
    if "," in date_range_str:
        parts = date_range_str.split(",", 1)
        return parts[0].strip(), parts[1].strip()
    else:
        # Single date - use as both start and end
        return date_range_str.strip(), date_range_str.strip()


async def process_report_request(
    llm_response: LLMResponse,
    db_name: str
) -> Dict[str, Any]:
    """
    Process valid report request
    
    Args:
        llm_response: LLM response with report type and prerequisites
        db_name: MongoDB database name
        
    Returns:
        Dictionary containing query results and API response
    """
    result = {
        "mongodb_query_result": None,
        "api_response": None
    }
    
    report_type = llm_response.type
    pre_req = llm_response.pre_req
    
    if not pre_req:
        return result
    
    # Extract asset IDs if needed
    asset_ids = None
    if pre_req.asset_plate_numbers:
        query_result = mongo_handler.get_asset_ids_by_plate_numbers(
            db_name, 
            pre_req.asset_plate_numbers
        )
        result["mongodb_query_result"] = query_result
        if query_result["success"] and query_result["asset_ids"]:
            asset_ids = ",".join(query_result["asset_ids"])
    
    elif pre_req.group_names:
        query_result = mongo_handler.get_asset_ids_by_group_names(
            db_name, 
            pre_req.group_names
        )
        result["mongodb_query_result"] = query_result
        if query_result["success"] and query_result["asset_ids"]:
            asset_ids = ",".join(query_result["asset_ids"])
    
    # Extract driver IDs if needed
    driver_ids = None
    if pre_req.driver_names:
        query_result = mongo_handler.get_driver_ids_by_names(
            db_name, 
            pre_req.driver_names
        )
        result["mongodb_query_result"] = query_result
        if query_result["success"] and query_result["driver_ids"]:
            driver_ids = ",".join(query_result["driver_ids"])
    
    # Parse dates if provided
    start_date = None
    end_date = None
    if pre_req.date_range:
        start_date, end_date = parse_date_range(pre_req.date_range)
    
    # Call appropriate API based on report type
    if report_type == "Trip":
        if asset_ids and start_date and end_date:
            api_response = await api_handler.fetch_trip_report(asset_ids, start_date, end_date)
            result["api_response"] = api_response
    
    elif report_type == "FleetSummary":
        if asset_ids:
            api_response = await api_handler.fetch_fleet_summary(asset_ids)
            result["api_response"] = api_response
    
    elif report_type == "FleetPerformanceSummary":
        if asset_ids and start_date and end_date:
            api_response = await api_handler.fetch_fleet_performance_summary(
                asset_ids, start_date, end_date
            )
            result["api_response"] = api_response
    
    elif report_type == "SIM":
        if asset_ids and start_date and end_date:
            api_response = await api_handler.fetch_sim_report(asset_ids, start_date, end_date)
            result["api_response"] = api_response
    
    elif report_type == "Utilization":
        if start_date and end_date:
            api_response = await api_handler.fetch_utilization_report(start_date, end_date)
            result["api_response"] = api_response
    
    elif report_type == "DrivingBehaviour":
        if driver_ids and start_date and end_date:
            api_response = await api_handler.fetch_generic_report(
                report_type, driver_ids=driver_ids, start_date=start_date, end_date=end_date
            )
            result["api_response"] = api_response
    
    else:
        # Generic reports using fetch-dates endpoint
        if asset_ids and start_date and end_date:
            api_response = await api_handler.fetch_generic_report(
                report_type, asset_ids=asset_ids, start_date=start_date, end_date=end_date
            )
            result["api_response"] = api_response
    
    return result


@app.post("/chat", response_model=ChatResponse)
async def chat_endpoint(request: ChatRequest, background_tasks: BackgroundTasks):
    """
    Main chat endpoint for processing user requests
    
    Args:
        request: Chat request with session info and user input
        background_tasks: FastAPI background tasks
        
    Returns:
        ChatResponse with LLM response and API results
    """
    try:
        # Step 1: Retrieve conversation history
        conversation_history = history_manager.get_history(
            request.sub_tenant_id, 
            request.session_id
        )
        
        print(f"\n=== Processing Request ===")
        print(f"Session: {request.sub_tenant_id}/{request.session_id}")
        print(f"User Input: {request.user_input}")
        print(f"History Length: {len(conversation_history)} messages")
        
        # Step 2: Add user message to history
        history_manager.add_message(
            request.sub_tenant_id,
            request.session_id,
            "user",
            request.user_input
        )
        
        # Step 3: Call LLM agent
        llm_response = llm_agent.process_user_input(
            request.user_input, 
            conversation_history
        )
        
        print(f"LLM Response Type: {llm_response.type}")
        print(f"LLM Message: {llm_response.message}")
        
        # Step 4: Check if request is invalid
        if llm_response.type == "invalid":
            # Clear history for invalid requests
            history_manager.clear_history(
                request.sub_tenant_id,
                request.session_id
            )
            print("Invalid request - history cleared")
            
            return ChatResponse(
                status="success",
                llm_response=llm_response,
                mongodb_query_result=None,
                api_response=None
            )
        
        # Step 5: Add assistant response to history
        history_manager.add_message(
            request.sub_tenant_id,
            request.session_id,
            "assistant",
            llm_agent.format_response_for_history(llm_response)
        )
        
        # Step 6: Check if prerequisites are complete
        if llm_response.message:
            # Prerequisites are missing
            print("Asking user for missing prerequisites")
            return ChatResponse(
                status="success",
                llm_response=llm_response,
                mongodb_query_result=None,
                api_response=None
            )
        
        # Step 7: Process report request
        print(f"Processing report: {llm_response.type}")
        processing_result = await process_report_request(
            llm_response,
            request.mongo_db
        )
        
        print(f"MongoDB Query Success: {processing_result['mongodb_query_result']['success'] if processing_result['mongodb_query_result'] else 'N/A'}")
        print(f"API Call Success: {processing_result['api_response']['success'] if processing_result['api_response'] else 'N/A'}")
        
        return ChatResponse(
            status="success",
            llm_response=llm_response,
            mongodb_query_result=processing_result["mongodb_query_result"],
            api_response=processing_result["api_response"]
        )
        
    except Exception as e:
        print(f"Error processing request: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "message": "Fleet Analytics Chatbot API",
        "version": "1.0.0",
        "endpoints": {
            "chat": "/chat",
            "docs": "/docs",
            "health": "/health"
        }
    }


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "active_sessions": history_manager.get_session_count()
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
