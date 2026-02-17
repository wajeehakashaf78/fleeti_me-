"""
FastAPI Application for FLEETI - Fleet Management Chatbot System
Converts the CLI-based main.py to a REST API with dynamic parameters
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import os
import requests
import json
import ast
import re
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

# Load environment variables
load_dotenv()

# Get FleetiReports URL from environment variable
FLEETI_REPORTS_URL = os.getenv("FLEETI_REPORTS_URL", "http://localhost:8000")

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
# FleetiReports Integration Function
# ================================
def call_fleeti_reports_api(user_message: str, session_id: str, sub_tenant_id: str, mongo_db: str) -> dict:
    """
    Call FleetiReports HTTP API to process user message.
    
    Args:
        user_message: The user's message to send to FleetiReports
        session_id: Session ID for conversation tracking
        sub_tenant_id: Sub-tenant identifier
        mongo_db: MongoDB database name
        
    Returns:
        Dictionary with:
        - success: bool indicating if call was successful
        - status: status from FleetiReports response
        - llm_response: LLM response object containing type, pre_req, message
        - mongodb_query_result: MongoDB query result (if any)
        - api_response: API response data (if any)
        - error: Error message if call failed
    """
    fleeti_reports_url = f"{FLEETI_REPORTS_URL}/chat"
    
    payload = {
        "sub_tenant_id": sub_tenant_id,
        "session_id": session_id,
        "mongo_db": mongo_db,
        "user_input": user_message
    }
    
    try:
        response = requests.post(fleeti_reports_url, json=payload, timeout=60)
        response.raise_for_status()
        
        response_data = response.json()
        
        return {
            "success": True,
            "status": response_data.get("status"),
            "llm_response": response_data.get("llm_response"),
            "mongodb_query_result": response_data.get("mongodb_query_result"),
            "api_response": response_data.get("api_response"),
            "error": response_data.get("error")
        }
        
    except requests.exceptions.RequestException as e:
        return {
            "success": False,
            "status": "error",
            "llm_response": None,
            "mongodb_query_result": None,
            "api_response": None,
            "error": str(e)
        }
    except Exception as e:
        return {
            "success": False,
            "status": "error",
            "llm_response": None,
            "mongodb_query_result": None,
            "api_response": None,
            "error": str(e)
        }

# Pydantic models for request/response
class ChatRequest(BaseModel):
    sub_tenant_id: str = Field(..., description="Sub-tenant ID for data isolation")
    session_id: str = Field(..., description="Session ID for conversation history")
    mongo_db: str = Field(..., description="MongoDB database name to query")
    user_input: str = Field(..., description="User's message/question")

class ChatResponse(BaseModel):
    human_response: str = Field(..., description="Natural language response")
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
async def chat(request: ChatRequest):
    """
    Main chat endpoint - processes user input and returns AI response
    
    Args:
        request: ChatRequest containing sub_tenant_id, session_id, mongo_db, user_input
        
    Returns:
        ChatResponse with human_response and error flag
    """
    try:
        # Initialize history saver with dynamic session_id and sub_tenant_id
        history_saver = FleetiHistorySaver(
            session_id=request.session_id,
            sub_tenant_id=request.sub_tenant_id,
            mongo_db=request.mongo_db,
        )
        
        # Load existing conversation history
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
            # Fleet query - First check with FleetiReports
            fleeti_response = call_fleeti_reports_api(
                refined_message, 
                request.session_id, 
                request.sub_tenant_id, 
                request.mongo_db
            )
            
            if not fleeti_response["success"]:
                # FleetiReports API failed - return static error message
                error_response = "I ran into a problem."
                
                # Save error as fleet message
                history_saver.save_fleet_message(
                    user_input=request.user_input,
                    refined_message=refined_message,
                    selected_collections=[],
                    query="",
                    query_response=[],
                    human_response=error_response
                )
                
                return ChatResponse(
                    human_response=error_response,
                    error=True
                )
            
            # Extract llm_response from FleetiReports response
            llm_response_data = fleeti_response.get("llm_response", {})
            response_type = llm_response_data.get("type", "invalid") if llm_response_data else "invalid"
            response_message = llm_response_data.get("message", "") if llm_response_data else ""
            api_response_data = fleeti_response.get("api_response")
            
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
                        (r'("(?:[^"]*\.)?sub_tenant_id"\s*:\s*)"sub_tenant_id"', r'\1"' + request.sub_tenant_id + '"'),
                        # Match keys with double quotes, values with single quotes
                        (r'("(?:[^"]*\.)?sub_tenant_id"\s*:\s*)\'sub_tenant_id\'', r'\1"' + request.sub_tenant_id + '"'),
                        # Match keys with single quotes, values with double quotes
                        (r'(\'(?:[^\']*\.)?sub_tenant_id\'\s*:\s*)"sub_tenant_id"', r'\1"' + request.sub_tenant_id + '"'),
                        # Match keys with single quotes, values with single quotes
                        (r'(\'(?:[^\']*\.)?sub_tenant_id\'\s*:\s*)\'sub_tenant_id\'', r'\1"' + request.sub_tenant_id + '"'),
                    ]
                    
                    for pattern, replacement in patterns:
                        mongoagent_response = re.sub(pattern, replacement, mongoagent_response)
                    
                    # Step 3: Execute query with dynamic mongo_db
                    # Create a new query runner instance with the specified database
                    query_runner = LlmMongoRunner()
                    
                    # Temporarily switch to the requested database
                    original_db = query_runner.db
                    query_runner.db = query_runner.client[request.mongo_db]
                    
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
                    
                    finally:
                        # Restore original database
                        query_runner.db = original_db
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
                    # Message is empty - check api_response data
                    # If api_response.data.data is empty, tell user we couldn't find anything
                    api_data = None
                    if api_response_data and isinstance(api_response_data, dict):
                        inner_data = api_response_data.get("data")
                        if inner_data and isinstance(inner_data, dict):
                            api_data = inner_data.get("data")
                    
                    if not api_data or (isinstance(api_data, list) and len(api_data) == 0):
                        # No data found - return user-friendly message
                        final_response = "I couldn't find any data matching your request."
                    else:
                        # Has data - use api_response + type as final response (raw JSON)
                        final_response_data = {
                            "type": response_type,
                            "api_response": api_response_data
                        }
                        final_response = json.dumps(final_response_data, indent=2, default=str)
                    
                    # Save FleetiReports response as fleet message
                    history_saver.save_fleet_message(
                        user_input=request.user_input,
                        refined_message=refined_message,
                        selected_collections=[],
                        query="",
                        query_response=api_response_data if api_response_data else [],
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
async def get_conversations(sub_tenant_id: str, mongo_db: str):
    """
    Get list of all conversation sessions for a sub-tenant
    
    Args:
        sub_tenant_id: Sub-tenant identifier
        mongo_db: MongoDB database name
        
    Returns:
        List of conversation sessions with metadata
    """
    try:
        from pymongo import MongoClient
        import os
        from dotenv import load_dotenv
        
        load_dotenv()
        mongo_uri = os.getenv("MONGO_URI")
        if not mongo_uri:
            return {"error": "MONGO_URI not configured", "conversations": []}
        
        client = MongoClient(mongo_uri)
        db = client[mongo_db]
        collection = db["FleetiMessages"]
        
        # Find all sessions for this sub-tenant
        sessions = list(collection.find(
            {"sub_tenant_id": sub_tenant_id},
            {"sessionId": 1, "created_at": 1, "messages": {"$slice": 1}}  # Get first message for preview
        ).sort("created_at", -1))
        
        conversations = []
        for session in sessions:
            first_message = session.get("messages", [{}])[0] if session.get("messages") else {}
            preview = first_message.get("user_input", first_message.get("refined_message", ""))
            
            conversations.append({
                "session_id": session.get("sessionId"),
                "created_at": session.get("created_at").isoformat() if session.get("created_at") else None,
                "preview": preview[:50] + "..." if len(preview) > 50 else preview,
                "message_count": len(session.get("messages", []))
            })
        
        return {"conversations": conversations, "error": None}
    except Exception as e:
        return {"error": str(e), "conversations": []}


@app.get("/conversation/{session_id}")
async def get_conversation(session_id: str, sub_tenant_id: str, mongo_db: str):
    """
    Get full conversation history for a specific session
    
    Args:
        session_id: Session identifier
        sub_tenant_id: Sub-tenant identifier
        mongo_db: MongoDB database name
        
    Returns:
        List of messages in the conversation
    """
    try:
        from pymongo import MongoClient
        import os
        from dotenv import load_dotenv
        
        load_dotenv()
        mongo_uri = os.getenv("MONGO_URI")
        if not mongo_uri:
            return {"error": "MONGO_URI not configured", "messages": []}
        
        client = MongoClient(mongo_uri)
        db = client[mongo_db]
        collection = db["FleetiMessages"]
        
        session_doc = collection.find_one({
            "sessionId": session_id,
            "sub_tenant_id": sub_tenant_id
        })
        
        if not session_doc:
            return {"messages": [], "error": None}
        
        messages = []
        for msg in session_doc.get("messages", []):
            if msg.get("type") == "general":
                messages.append({
                    "role": "user",
                    "content": msg.get("user_input", ""),
                    "timestamp": msg.get("timestamp").isoformat() if msg.get("timestamp") else None
                })
                messages.append({
                    "role": "assistant",
                    "content": msg.get("llm_response", ""),
                    "timestamp": msg.get("timestamp").isoformat() if msg.get("timestamp") else None
                })
            elif msg.get("type") == "fleet":
                messages.append({
                    "role": "user",
                    "content": msg.get("user_input", ""),
                    "timestamp": msg.get("timestamp").isoformat() if msg.get("timestamp") else None
                })
                messages.append({
                    "role": "assistant",
                    "content": msg.get("human_response", ""),
                    "timestamp": msg.get("timestamp").isoformat() if msg.get("timestamp") else None
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
