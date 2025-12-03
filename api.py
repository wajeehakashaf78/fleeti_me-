"""
FastAPI Application for FLEETI - Fleet Management Chatbot System
Converts the CLI-based main.py to a REST API with dynamic parameters
"""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Optional
import os
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
        # Initialize history saver with dynamic session_id
        history_saver = FleetiHistorySaver(session_id=request.session_id)
        
        # Load existing conversation history
        existing_history = history_saver.load_session_history()
        if existing_history:
            classifier.conversation_history = existing_history
        
        # Process message through classifier
        refined_message, classification, llm_response = classifier.process_message(request.user_input)
        
        # Handle classification result
        if classification == "general":
            # General conversation - return LLM response directly
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
                # No LLM response - treat as error
                return ChatResponse(
                    human_response="I couldn't generate a response. Please try again.",
                    error=True
                )
        
        elif classification == "fleet":
            # Fleet query - run full pipeline
            
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
            
            # Step 2: Generate MongoDB query via FleetiMongoagent
            full_prompt = prompt_blueprint.replace("{schemas}", schemas).replace("{refined_message}", refined_message)
            mongoagent_response = mongoagent_orchistrator_main(full_prompt)
            
            if not mongoagent_response:
                return ChatResponse(
                    human_response="I couldn't generate a database query for your question. Please try rephrasing.",
                    error=True
                )
            
            # Replace placeholder sub_tenant_id with actual value
            import re
            patterns = [
                (r'("sub_tenant_id"\s*:\s*)"sub_tenant_id"', r'\1"' + request.sub_tenant_id + '"'),
                (r'("sub_tenant_id"\s*:\s*)\'sub_tenant_id\'', r'\1"' + request.sub_tenant_id + '"'),
                (r'(\'sub_tenant_id\'\s*:\s*)"sub_tenant_id"', r'\1"' + request.sub_tenant_id + '"'),
                (r'(\'sub_tenant_id\'\s*:\s*)\'sub_tenant_id\'', r'\1"' + request.sub_tenant_id + '"'),
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
                import json
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
