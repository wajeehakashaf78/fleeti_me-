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

# Get Rasa URL from environment variable
RASA_URL = os.getenv("RASA_URL", "http://localhost:5005")

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
# Rasa Integration Function
# ================================
def call_rasa_api(user_message: str, session_id: str) -> dict:
    """
    Call Rasa HTTP API to process user message.
    
    Args:
        user_message: The user's message to send to Rasa
        session_id: Session ID to use as sender_id for Rasa
        
    Returns:
        Dictionary with:
        - success: bool indicating if call was successful
        - response_text: Combined text from all Rasa responses
        - intent: Detected intent name (if available)
        - error: Error message if call failed
    """
    rasa_webhook_url = f"{RASA_URL}/webhooks/rest/webhook"
    
    payload = {
        "sender": session_id,
        "message": user_message
    }
    
    try:
        response = requests.post(rasa_webhook_url, json=payload, timeout=30)
        response.raise_for_status()
        
        # Rasa returns array of message objects: [{"text": "response 1"}, {"text": "response 2"}]
        rasa_messages = response.json()
        
        # Combine all text responses into a single string
        response_texts = []
        for msg in rasa_messages:
            if isinstance(msg, dict) and "text" in msg:
                response_texts.append(msg["text"])
        
        combined_response = "\n".join(response_texts) if response_texts else ""
        
        # Try to get intent from tracker
        intent = None
        try:
            tracker_url = f"{RASA_URL}/conversations/{session_id}/tracker"
            tracker_response = requests.get(tracker_url, timeout=10)
            if tracker_response.status_code == 200:
                tracker_data = tracker_response.json()
                # Get the latest intent from events
                events = tracker_data.get("events", [])
                for event in reversed(events):  # Check from most recent
                    if event.get("event") == "user" and "parse_data" in event:
                        intent_data = event.get("parse_data", {}).get("intent", {})
                        if intent_data and "name" in intent_data:
                            intent = intent_data["name"]
                            break
        except Exception:
            # If tracker call fails, continue without intent
            pass
        
        return {
            "success": True,
            "response_text": combined_response,
            "intent": intent,
            "error": None
        }
        
    except requests.exceptions.RequestException as e:
        return {
            "success": False,
            "response_text": "",
            "intent": None,
            "error": str(e)
        }
    except Exception as e:
        return {
            "success": False,
            "response_text": "",
            "intent": None,
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
        history_saver = FleetiHistorySaver(session_id=request.session_id, sub_tenant_id=request.sub_tenant_id)
        
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
            # Fleet query - First check with Rasa
            rasa_response = call_rasa_api(refined_message, request.session_id)
            
            if not rasa_response["success"]:
                # Rasa API failed - return static error message
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
            
            rasa_response_text = rasa_response["response_text"].lower() if rasa_response["response_text"] else ""
            rasa_intent = rasa_response.get("intent")
            
            # Check if we should ignore Rasa response and use RAG pipeline
            # Scenario B: If response contains "mongo agent" (case insensitive) or intent is request_fleet_info
            should_use_rag = False
            
            # Check for "mongo agent" in response text (case insensitive)
            if "mongo" in rasa_response_text or "mongoagent" in rasa_response_text:
                should_use_rag = True
            
            # Check if intent is request_fleet_info
            if rasa_intent == "request_fleet_info":
                should_use_rag = True
            
            if should_use_rag:
                # Scenario B: Ignore Rasa, use existing RAG pipeline
                
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
                full_prompt = prompt_blueprint.replace("{schemas}", schemas).replace("{refined_message}", refined_message)
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
                # Scenario A or C: Use Rasa response
                rasa_final_response = rasa_response["response_text"]
                
                # Save Rasa response as fleet message
                # Scenario A (complete report) or Scenario C (asking for more info)
                history_saver.save_fleet_message(
                    user_input=request.user_input,
                    refined_message=refined_message,
                    selected_collections=[],  # No collections for Rasa reports
                    query="",  # No query for Rasa reports
                    query_response=[],  # No query response for Rasa reports
                    human_response=rasa_final_response
                )
                
                # Update classifier history
                if classifier.conversation_history:
                    classifier.conversation_history[-1]["assistant"] = rasa_final_response
                
                return ChatResponse(
                    human_response=rasa_final_response,
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


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "api:app",
        host="0.0.0.0",
        port=8000,
        reload=True
    )
