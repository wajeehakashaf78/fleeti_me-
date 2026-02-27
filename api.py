"""
FastAPI Application for FLEETI - Fleet Management Chatbot System
Converts the CLI-based main.py to a REST API with dynamic parameters
"""

from fastapi import FastAPI, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import os
import json
import ast
import re
from typing import Optional, Dict, Any, List
from datetime import datetime
from dotenv import load_dotenv

# Import all the components from main.py
from ConversationClassifier.conversation_classifier import ConversationClassifier
from FleetiHistorySaver.history_saver import FleetiHistorySaver
from FleetDbSummarizer.rag_pipeline import RAGPipeline
from FleetiMongoagent.prompt_blueprint import PROMPT as prompt_blueprint
from FleetiMongoagent.run_all_models import orchistrator_main as mongoagent_orchistrator_main
from FleetiQueryRunner.execute import LlmMongoRunner
from FleetiResponse.respond import generate_llm_response as generate_human_response
from jwt_utils import decode_jwt_no_verify, extract_db_and_sub_tenant

# FleetiReports modules (integrated)
from FleetiReports.llm_agent import llm_agent
from FleetiReports.mongo_handler import mongo_handler
from FleetiReports.api_handler import APIHandler
from FleetiReports.models import LLMResponse

# Load environment variables
load_dotenv()

# Initialize FastAPI app
app = FastAPI(
    title="FLEETI API",
    description="Fleet Management Chatbot API",
    version="1.0.0"
)

# Enable CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allows all origins
    allow_credentials=True,
    allow_methods=["*"],  # Allows all methods
    allow_headers=["*"],  # Allows all headers
)

# Initialize global components that don't depend on dynamic parameters
classifier = ConversationClassifier()
pipeline = RAGPipeline()


# ================================
# FleetiReports Integration Helpers
# ================================
def _build_reports_base_url(base_url: str) -> str:
    return base_url.rstrip("/") + "/api/admin/reports"


def _build_reports_conversation_history(session_doc: Optional[Dict[str, Any]]) -> List[Dict[str, str]]:
    """
    Build conversation history for FleetiReports LLM from Mongo session doc.
    Excludes any messages that do not have a 'type' field (static initial message).
    """
    if not session_doc:
        return []
    history: List[Dict[str, str]] = []
    for msg in session_doc.get("messages", []):
        msg_type = msg.get("type")
        if msg_type == "general":
            user_content = msg.get("user_input", "")
            assistant_content = msg.get("llm_response", "")
            if not isinstance(assistant_content, str):
                assistant_content = json.dumps(assistant_content, default=str)
            history.append({"role": "user", "content": user_content})
            history.append({"role": "assistant", "content": assistant_content})
        elif msg_type == "fleet":
            user_content = msg.get("user_input", "")
            assistant_content = msg.get("human_response", "")
            if not isinstance(assistant_content, str):
                assistant_content = json.dumps(assistant_content, default=str)
            history.append({"role": "user", "content": user_content})
            history.append({"role": "assistant", "content": assistant_content})
    return history


def _parse_date_range(date_range_str: str) -> tuple[str, str]:
    if "," in date_range_str:
        parts = date_range_str.split(",", 1)
        return parts[0].strip(), parts[1].strip()
    return date_range_str.strip(), date_range_str.strip()


async def _process_report_request(
    llm_response: LLMResponse,
    db_name: str,
    api_handler: APIHandler
) -> Dict[str, Any]:
    result: Dict[str, Any] = {"mongodb_query_result": None, "api_response": None}
    report_type = llm_response.type
    pre_req = llm_response.pre_req
    if not pre_req:
        return result

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

    driver_ids = None
    if pre_req.driver_names:
        query_result = mongo_handler.get_driver_ids_by_names(
            db_name,
            pre_req.driver_names
        )
        result["mongodb_query_result"] = query_result
        if query_result["success"] and query_result["driver_ids"]:
            driver_ids = ",".join(query_result["driver_ids"])

    start_date = None
    end_date = None
    if pre_req.date_range:
        start_date, end_date = _parse_date_range(pre_req.date_range)

    if report_type == "Trip":
        if asset_ids and start_date and end_date:
            result["api_response"] = await api_handler.fetch_trip_report(asset_ids, start_date, end_date)
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
    elif report_type in ("DriverBehaviour", "DrivingBehaviour", "DriverBehavior"):
        if driver_ids and start_date and end_date:
            result["api_response"] = await api_handler.fetch_generic_report(
                report_type, driver_ids=driver_ids, start_date=start_date, end_date=end_date
            )
    else:
        if asset_ids and start_date and end_date:
            result["api_response"] = await api_handler.fetch_generic_report(
                report_type, asset_ids=asset_ids, start_date=start_date, end_date=end_date
            )

    return result

# Pydantic models for request/response
class ChatRequest(BaseModel):
    base_url: str = Field(..., description="Base URL from FE (e.g., https://qa.dev-iot.tracking.me/)")
    assistant_static_input: Optional[str] = Field(None, description="Initial static assistant message")
    user_input: Optional[str] = Field(None, description="User's message/question")
    session_id: Optional[str] = Field(None, description="Session ID (MongoDB document ID)")

class ChatResponse(BaseModel):
    human_response: Optional[Any] = Field(default=None, description="Natural language response or structured data")
    session_id: Optional[str] = Field(default=None, description="Session ID (MongoDB document ID)")
    error: bool = Field(default=False, description="Whether an error occurred")


@app.get("/")
async def root():
    """Health check endpoint"""
    return {
        "status": "ok",
        "message": "FLEETI API is running",
        "version": "1.0.0"
    }


@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest, authorization: Optional[str] = Header(default=None)):
    """
    Main chat endpoint - processes user input and returns AI response
    
    Args:
        request: ChatRequest containing sub_tenant_id, session_id, mongo_db, user_input
        
    Returns:
        ChatResponse with human_response and error flag
    """
    try:
        if not authorization:
            return ChatResponse(
                human_response="Missing Authorization header.",
                error=True
            )

        token_payload = decode_jwt_no_verify(authorization)
        mongo_db, sub_tenant_id = extract_db_and_sub_tenant(token_payload)

        if not mongo_db or not sub_tenant_id:
            return ChatResponse(
                human_response="Invalid token: missing database or sub-tenant information.",
                error=True
            )

        # Scenario 1: Create session with static assistant message
        if request.assistant_static_input is not None:
            history_saver = FleetiHistorySaver(
                session_id="static_session",
                sub_tenant_id=sub_tenant_id,
                mongo_db=mongo_db,
            )
            session_id = history_saver.save_static_message(request.assistant_static_input)
            return ChatResponse(
                human_response=None,
                session_id=session_id,
                error=False
            )

        # Scenario 2: Normal chat flow
        if not request.user_input or not request.session_id:
            return ChatResponse(
                human_response="Missing user_input or session_id.",
                error=True
            )

        # Initialize history saver with dynamic session_id and sub_tenant_id
        history_saver = FleetiHistorySaver(
            session_id=request.session_id,
            sub_tenant_id=sub_tenant_id,
            mongo_db=mongo_db,
        )

        # Load existing conversation history (excludes static message)
        existing_history = history_saver.load_session_history()
        if existing_history:
            classifier.conversation_history = existing_history

        # Process message through classifier
        refined_message, classification, llm_response = classifier.process_message(request.user_input)
        
        # Handle classification result
        # Note: classification can be "general conversation" or "fleet"
        if classification == "general conversation":
            # General conversation - return LLM response directly
            # The classifier should always provide a response for general conversation
            # (it defaults to a greeting if none is provided)
            if llm_response:
                # Save general message to history
                history_saver.save_general_message(
                    user_input=request.user_input,
                    refined_message=refined_message,
                    llm_response=llm_response
                )
                
                return ChatResponse(
                    human_response=llm_response,
                    error=False
                )
            else:
                # Fallback: if somehow no response was generated, use default
                default_response = "Helloooo, I am your fleet assistant. How can I help you today?"
                history_saver.save_general_message(
                    user_input=request.user_input,
                    refined_message=refined_message,
                    llm_response=default_response
                )
                
                return ChatResponse(
                    human_response=default_response,
                    error=False
                )
        
        elif classification == "fleet":
            # Fleet query - First check with FleetiReports (integrated)
            base_api_url = _build_reports_base_url(request.base_url)
            reports_api_handler = APIHandler(base_url=base_api_url, access_token=authorization)

            session_doc = history_saver.get_session_document()
            reports_history = _build_reports_conversation_history(session_doc)
            report_llm_response = llm_agent.process_user_input(refined_message, reports_history)

            response_type = report_llm_response.type if report_llm_response else "invalid"
            response_message = report_llm_response.message if report_llm_response else ""
            api_response_data = None
            
            # Check if type is "invalid" - route to FleetDbSummarizer (RAG pipeline)
            if response_type.lower() == "invalid":

                # Check if message field is not empty - then, this IS the final response
                if response_message and response_message.strip():
                    final_response = response_message
                    
                    # Save FleetiReports response as fleet message
                    history_saver.save_fleet_message(
                        user_input=request.user_input,
                        refined_message=refined_message,
                        selected_collections=[],
                        query="",
                        query_response=[],
                        human_response=final_response
                    )
                    
                    # Update classifier history
                    if classifier.conversation_history:
                        classifier.conversation_history[-1]["assistant"] = final_response
                    
                    return ChatResponse(
                        human_response=final_response,
                        error=False
                    )
                else:
                    # Message is empty - use existing RAG pipeline
                
                    # Step 1: RAG Pipeline - get relevant schemas
                    rag_result = pipeline.query(refined_message, use_llm=True)
                    
                    # Extract schemas
                    schemas = "\n\n".join(
                        collection_info.get("schema", "")
                        for collection_info in rag_result.get('collection_json', {}).get("collection_data", {}).values()
                    )
                    
                    # Get selected collections
                    collection_json = rag_result.get('collection_json', {})
                    collection_data = collection_json.get('collection_data', {})
                    
                    selected_collections = []
                    if collection_data:
                        for parent_collection, data in collection_data.items():
                            sub_collections = data.get('selected_sub_collections', [])
                            selected_collections.extend(sub_collections)
                    else:
                        # Fallback: parse from collections string
                        collections_output = rag_result.get('collections', '[]')
                        try:
                            selected_collections = ast.literal_eval(str(collections_output))
                            if not isinstance(selected_collections, list):
                                selected_collections = []
                        except Exception as e:
                            # Try regex fallback
                            list_match = re.search(r'\[(.*?)\]', str(collections_output))
                            if list_match:
                                list_content = list_match.group(1)
                                selected_collections = [c.strip().strip("'\"") for c in list_content.split(',') if c.strip()]
                            else:
                                selected_collections = []
                    
                    # Step 2: Generate MongoDB query via FleetiMongoagent
                    full_prompt = prompt_blueprint.replace("{current_date}", datetime.now().strftime("%Y-%m-%d")).replace("{schemas}", schemas).replace("{refined_message}", refined_message)
                    mongoagent_response = mongoagent_orchistrator_main(full_prompt)
                    
                    if not mongoagent_response:
                        return ChatResponse(
                            human_response="I couldn't generate a database query for your question. Please try rephrasing.",
                            error=True
                        )
                    
                    # Replace placeholder sub_tenant_id with actual value
                    # Handle multiple occurrences in the query with various quote styles and nested paths
                    # Pattern to match any key ending with sub_tenant_id (including nested paths like "alert_rule.sub_tenant_id")
                    # followed by colon and the placeholder value "sub_tenant_id"
                    # Replace the value with actual sub_tenant_id (always use double quotes)
                    patterns = [
                        # Match keys with double quotes, values with double quotes (handles nested paths)
                        (r'("(?:[^"]*\.)?sub_tenant_id"\s*:\s*)"sub_tenant_id"', r'\1"' + sub_tenant_id + '"'),
                        # Match keys with double quotes, values with single quotes
                        (r'("(?:[^"]*\.)?sub_tenant_id"\s*:\s*)\'sub_tenant_id\'', r'\1"' + sub_tenant_id + '"'),
                        # Match keys with single quotes, values with double quotes
                        (r'(\'(?:[^\']*\.)?sub_tenant_id\'\s*:\s*)"sub_tenant_id"', r'\1"' + sub_tenant_id + '"'),
                        # Match keys with single quotes, values with single quotes
                        (r'(\'(?:[^\']*\.)?sub_tenant_id\'\s*:\s*)\'sub_tenant_id\'', r'\1"' + sub_tenant_id + '"'),
                    ]
                    
                    for pattern, replacement in patterns:
                        mongoagent_response = re.sub(pattern, replacement, mongoagent_response)
                    
                    # Step 3: Execute query with dynamic mongo_db from JWT
                    query_runner = LlmMongoRunner(mongo_db=mongo_db)
                    
                    try:
                        results = query_runner.run(mongoagent_response, limit=10)
                        
                        # Convert results to string
                        results_str = json.dumps(results, indent=2, default=str) if results else "[]"
                        
                        # Step 4: Generate human-friendly response
                        human_response = generate_human_response(request.user_input, refined_message, results_str)
                        
                        # Save fleet message to history
                        history_saver.save_fleet_message(
                            user_input=request.user_input,
                            refined_message=refined_message,
                            selected_collections=selected_collections,
                            query=mongoagent_response,
                            query_response=results,
                            human_response=human_response
                        )
                        
                        # Update classifier history with actual response
                        if classifier.conversation_history:
                            classifier.conversation_history[-1]["assistant"] = human_response
                        
                        return ChatResponse(
                            human_response=human_response,
                            error=False
                        )
                    
                    except Exception as query_error:
                        return ChatResponse(
                            human_response=f"I encountered an error while querying the database: {str(query_error)}",
                            error=True
                        )
            else:
                # Type is NOT "invalid" - use FleetiReports response

                # Check if message field is not empty - this IS the final response
                if response_message and response_message.strip():
                    final_response = response_message

                    # Save FleetiReports response as fleet message
                    history_saver.save_fleet_message(
                        user_input=request.user_input,
                        refined_message=refined_message,
                        selected_collections=[],
                        query="",
                        query_response=[],
                        human_response=final_response
                    )

                    # Update classifier history
                    if classifier.conversation_history:
                        classifier.conversation_history[-1]["assistant"] = final_response

                    return ChatResponse(
                        human_response=final_response,
                        error=False
                    )
                else:
                    # Message is empty - process report request
                    processing_result = await _process_report_request(
                        report_llm_response,
                        mongo_db,
                        reports_api_handler
                    )
                    api_response_data = processing_result.get("api_response")

                    # If report API returns empty result set, return text response instead of JSON
                    api_data_wrapper = api_response_data.get("data") if isinstance(api_response_data, dict) else None
                    nested_data = api_data_wrapper.get("data") if isinstance(api_data_wrapper, dict) else None
                    # Support these empty-data shapes:
                    # 1) api_response.data.items == []
                    # 2) api_response.data.data.items == []
                    # 3) api_response.data.data == []
                    is_empty_report_data = False
                    if isinstance(api_data_wrapper, dict) and isinstance(api_data_wrapper.get("items"), list):
                        is_empty_report_data = len(api_data_wrapper.get("items")) == 0
                    elif isinstance(nested_data, dict) and isinstance(nested_data.get("items"), list):
                        is_empty_report_data = len(nested_data.get("items")) == 0
                    elif isinstance(nested_data, list):
                        is_empty_report_data = len(nested_data) == 0

                    if is_empty_report_data:
                        report_results_str = json.dumps(api_response_data, indent=2, default=str) if api_response_data else "{}"
                        final_response = generate_human_response(
                            request.user_input,
                            refined_message,
                            report_results_str
                        )
                    else:
                        # Default report behavior: return structured response
                        final_response = {
                            "type": response_type,
                            "api_response": api_response_data
                        }

                    # Save FleetiReports response as fleet message
                    history_saver.save_fleet_message(
                        user_input=request.user_input,
                        refined_message=refined_message,
                        selected_collections=[],
                        query="",
                        query_response=[],
                        human_response=final_response
                    )

                    return ChatResponse(
                        human_response=final_response,
                        error=False
                    )
        
        else:
            # Unknown classification
            return ChatResponse(
                human_response="I couldn't understand your message. Please try again.",
                error=True
            )
    
    except Exception as e:
        # Catch-all error handler
        return ChatResponse(
            human_response=f"An unexpected error occurred: {str(e)}",
            error=True
        )


@app.get("/conversations")
async def get_conversations(authorization: Optional[str] = Header(default=None)):
    """
    Get list of all conversation sessions for the sub-tenant in the JWT.
    Returns session _id, last message content, and last message timestamp.
    """
    try:
        if not authorization:
            return {"error": "Missing Authorization header", "conversations": []}

        token_payload = decode_jwt_no_verify(authorization)
        mongo_db, sub_tenant_id = extract_db_and_sub_tenant(token_payload)
        if not mongo_db or not sub_tenant_id:
            return {"error": "Invalid token: missing database or sub-tenant information.", "conversations": []}

        from pymongo import MongoClient
        load_dotenv()
        mongo_uri = os.getenv("MONGO_URI")
        if not mongo_uri:
            return {"error": "MONGO_URI not configured", "conversations": []}

        client = MongoClient(mongo_uri)
        db = client[mongo_db]
        collection = db["FleetiMessages"]

        pipeline = [
            {"$match": {"sub_tenant_id": sub_tenant_id}},
            {"$addFields": {"last_message": {"$arrayElemAt": ["$messages", -1]}}},
            {"$addFields": {"last_timestamp": "$last_message.timestamp"}},
            {"$sort": {"last_timestamp": -1}},
            {"$project": {"_id": 1, "last_message": 1, "last_timestamp": 1}}
        ]

        sessions = list(collection.aggregate(pipeline))

        conversations = []
        for session in sessions:
            last_msg = session.get("last_message") or {}
            last_text = (
                last_msg.get("user_input")
                or last_msg.get("human_response")
                or last_msg.get("llm_response")
                or last_msg.get("assistant_static_input")
                or ""
            )
            if not isinstance(last_text, str):
                last_text = json.dumps(last_text, default=str)

            last_ts = session.get("last_timestamp")
            conversations.append({
                "session_id": str(session.get("_id")),
                "last_message": last_text,
                "last_timestamp": last_ts.isoformat() if last_ts else None
            })

        return {"conversations": conversations, "error": None}
    except Exception as e:
        return {"error": str(e), "conversations": []}


class SessionRequest(BaseModel):
    session_id: str = Field(..., description="Session ID (MongoDB document ID)")


@app.post("/session")
async def get_session(request: SessionRequest, authorization: Optional[str] = Header(default=None)):
    """
    Get conversation messages for a specific session.
    Returns user_input and human_response in the same order as stored.
    """
    try:
        if not authorization:
            return {"error": "Missing Authorization header", "messages": []}

        token_payload = decode_jwt_no_verify(authorization)
        mongo_db, sub_tenant_id = extract_db_and_sub_tenant(token_payload)
        if not mongo_db or not sub_tenant_id:
            return {"error": "Invalid token: missing database or sub-tenant information.", "messages": []}

        from pymongo import MongoClient
        load_dotenv()
        mongo_uri = os.getenv("MONGO_URI")
        if not mongo_uri:
            return {"error": "MONGO_URI not configured", "messages": []}

        client = MongoClient(mongo_uri)
        db = client[mongo_db]
        collection = db["FleetiMessages"]

        session_doc = collection.find_one({
            "sessionId": request.session_id,
            "sub_tenant_id": sub_tenant_id
        })

        if not session_doc:
            return {"messages": [], "error": None}

        messages = []
        for msg in session_doc.get("messages", []):
            if "assistant_static_input" in msg:
                messages.append({
                    "user_input": "",
                    "human_response": msg.get("assistant_static_input", "")
                })
                continue
            if "user_input" in msg:
                messages.append({
                    "user_input": msg.get("user_input", ""),
                    "human_response": msg.get("human_response", msg.get("llm_response", ""))
                })

        return {"messages": messages, "error": None}
    except Exception as e:
        return {"error": str(e), "messages": []}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "api:app",
        host="0.0.0.0",
        port=8000,
        reload=True
    )
