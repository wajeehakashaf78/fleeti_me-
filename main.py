# ORCHISTRATOR
import time
import requests
import os
import json
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Get FleetiReports URL and MongoDB database from environment
FLEETI_REPORTS_URL = os.getenv("FLEETI_REPORTS_URL", "http://localhost:8000")
MONGO_DB = os.getenv("MONGO_DB", "qa")

from ConversationClassifier.conversation_classifier import ConversationClassifier
# Initialize classifier
if ConversationClassifier:
    classifier = ConversationClassifier()
    if getattr(classifier, 'client', None):
        print(f"OpenAI Model: {classifier.model_name}")
    else:
        print("Warning: OpenAI client not initialized. Falling back to heuristic classification.")
else:
    print("Warning: ConversationClassifier not initialized.")

# Initialize FleetiHistorySaver
from FleetiHistorySaver.history_saver import FleetiHistorySaver
# Hardcoded session ID for now
SESSION_ID = "default_session_001"

# HARD CODED SUB-TENANT ID FOR NOW
SUB_TENANT_ID = ""

# Initialize history saver with session_id and sub_tenant_id
history_saver = FleetiHistorySaver(session_id=SESSION_ID, sub_tenant_id=SUB_TENANT_ID)

# Load existing conversation history from MongoDB and populate classifier
existing_history = history_saver.load_session_history()
if existing_history:
    classifier.conversation_history = existing_history
    print(f"Loaded {len(existing_history)} messages from session: {SESSION_ID}")
else:
    print(f"No existing history found for session: {SESSION_ID}")

# Initialize RAG Pipeline
from FleetDbSummarizer.rag_pipeline import RAGPipeline
if RAGPipeline:
    pipeline = RAGPipeline()
else:
    raise Exception("RAGPipeline not initialized. ")

# Initialize FleetiMongoagent
from FleetiMongoagent.prompt_blueprint import PROMPT as prompt_blueprint
from FleetiMongoagent.run_all_models import orchistrator_main as mongoagent_orchistrator_main

# Initialize FleetiQueryRunner
from FleetiQueryRunner.execute import LlmMongoRunner
if LlmMongoRunner:
    query_runner = LlmMongoRunner()
else:
    raise Exception("LlmMongoRunner not initialized. ")

# FleetiResponse
from FleetiResponse.respond import generate_llm_response as generate_human_response

# ================================
# Classifier Function
# ================================
def main_classifier(user_message, start_time):
    """Interactive conversation classifier."""
    if not user_message:
        return None, None, None

    # Handle special commands
    if user_message.lower() in ['quit', 'exit', 'q']:
        print("\nGoodbye!")
        return "QUIT", None, None
    elif user_message.lower() == 'reset':
        classifier.reset_history()
        history_saver.clear_session()  # Also clear MongoDB history
        print("Conversation history cleared.\n")
        return "RESET", None, None
    elif user_message.lower() == 'history':
        history = classifier.format_conversation_history()
        if history:
            print(f"\nConversation History:\n{history}\n")
        else:
            print("\nNo conversation history yet.\n")
        return "HISTORY", None, None

    # Process message
    print("\nProcessing...")
    refined_message, classification, llm_response = classifier.process_message(user_message)
    
    # Show elapsed time
    elapsed = time.time() - start_time
    print(f"⏱️  Classifier completed in {elapsed:.2f}s")

    return refined_message, classification, llm_response


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


# ================================
# RAG Pipeline Function
# ================================
def main_rag_pipeline(refined_message, start_time, rebuild=False):
    """Main RAG Pipeline function."""
    rag_start = time.time()
    
    # Run RAG pipeline
    result = pipeline.query(refined_message, use_llm=True)

    # Extract schemas for mongoagent
    schemas = "\n\n".join(
        collection_info.get("schema", "")
        for collection_info in result['collection_json'].get("collection_data", {}).values()
    )
    
    # Show elapsed time for RAG
    rag_elapsed = time.time() - rag_start
    total_elapsed = time.time() - start_time
    print(f"⏱️  RAG Pipeline completed in {rag_elapsed:.2f}s (Total: {total_elapsed:.2f}s)")

    return result  # Return full result instead of just schemas


# ================================
# Main Function
# ================================
def main():
    import sys
    # Check if indexes should be rebuilt
    rebuild = '--rebuild' in sys.argv
    
    print("=" * 60)
    print("Conversation Classifier - Interactive Mode")
    print("=" * 60)
    print("\nInitializing OpenAI client...")
    print("Using OPENAI_API_KEY and model from OPENAI_MODEL (default gpt-4o-mini).\n")

    
    print("\n" + "=" * 60)
    print("Ready! Type your messages below.")
    print("Type 'reset' to clear conversation history")
    print("Type 'history' to view conversation history")
    print("Type 'quit' or 'exit' to exit")
    print("=" * 60 + "\n")
    
    while True:
        try:
            # Get user input
            user_message = input("You: ").strip()
            
            # Start timer
            start_time = time.time()
            print(f"\n⏱️  Timer started at 0:00")
            
            refined_message, classification, llm_response = main_classifier(user_message, start_time)
            print(refined_message)
            # Handle special commands
            if refined_message == "QUIT":
                break
            elif refined_message == "RESET" or refined_message == "HISTORY":
                continue
            elif refined_message is None or classification is None:
                continue
            
            if llm_response:
                # General conversation response
                print(f"\nResponse: {llm_response}")
                
                # Show total time for general conversation
                total_elapsed = time.time() - start_time
                print(f"⏱️  Total time: {total_elapsed:.2f}s\n")

                # Save general conversation to MongoDB
                history_saver.save_general_message(
                    user_input=user_message,
                    refined_message=refined_message,
                    llm_response=llm_response
                )
            else:
                # Fleet query - First check with FleetiReports
                fleeti_start = time.time()
                fleeti_response = call_fleeti_reports_api(
                    refined_message, 
                    SESSION_ID, 
                    SUB_TENANT_ID, 
                    MONGO_DB
                )
                fleeti_elapsed = time.time() - fleeti_start
                total_elapsed = time.time() - start_time
                
                if not fleeti_response["success"]:
                    # FleetiReports API failed - return static error message
                    error_response = "I ran into a problem."
                    print(f"\nResponse: {error_response}")
                    print(f"⏱️  FleetiReports API call failed in {fleeti_elapsed:.2f}s (Total: {total_elapsed:.2f}s)\n")
                    
                    # Save error as fleet message
                    history_saver.save_fleet_message(
                        user_input=user_message,
                        refined_message=refined_message,
                        selected_collections=[],
                        query="",
                        query_response=[],
                        human_response=error_response
                    )
                    continue
                
                # Extract llm_response from FleetiReports response
                llm_response_data = fleeti_response.get("llm_response", {})
                response_type = llm_response_data.get("type", "invalid") if llm_response_data else "invalid"
                response_message = llm_response_data.get("message", "") if llm_response_data else ""
                api_response_data = fleeti_response.get("api_response")
                
                print(f"⏱️  FleetiReports completed in {fleeti_elapsed:.2f}s (Total: {total_elapsed:.2f}s)")
                print(f"Response Type: {response_type}")
                
                # Check if type is "invalid" - route to FleetDbSummarizer (RAG pipeline)
                if response_type.lower() == "invalid":
                    print(f"Type is 'invalid' - Routing to FleetDbSummarizer (RAG pipeline)...\n")
                    
                    # Use existing RAG pipeline
                    rag_result = main_rag_pipeline(refined_message, start_time, rebuild)
                    
                    # Extract schemas from result
                    schemas = "\n\n".join(
                        collection_info.get("schema", "")
                        for collection_info in rag_result.get('collection_json', {}).get("collection_data", {}).values()
                    )
                    
                    # Get selected collections (subcollections) from RAG pipeline result
                    import ast
                    selected_collections = []
                    
                    # Extract subcollections from collection_json.collection_data
                    collection_json = rag_result.get('collection_json', {})
                    collection_data = collection_json.get('collection_data', {})
                    
                    if collection_data:
                        # Collect all selected_sub_collections from all parent collections
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
                            import re
                            list_match = re.search(r'\[(.*?)\]', str(collections_output))
                            if list_match:
                                list_content = list_match.group(1)
                                selected_collections = [c.strip().strip("'\"") for c in list_content.split(',') if c.strip()]
                            else:
                                selected_collections = []

                    # Use string replacement instead of format() to avoid issues with curly braces in schemas
                    # (schemas may contain MongoDB operators like {"$regex": ...} which break format())
                    full_prompt = prompt_blueprint.replace("{schemas}", schemas).replace("{refined_message}", refined_message)
                    
                    mongoagent_start = time.time()
                    mongoagent_response = mongoagent_orchistrator_main(full_prompt)
                    mongoagent_elapsed = time.time() - mongoagent_start
                    total_elapsed = time.time() - start_time
                    print(f"⏱️  Query generation completed in {mongoagent_elapsed:.2f}s (Total: {total_elapsed:.2f}s)")

                    if not mongoagent_response:
                        print("\nError: No query generated by Mongoagent.")
                        continue

                    # Replace placeholder "sub_tenant_id": "sub_tenant_id" with actual SUB_TENANT_ID value
                    # Handle multiple occurrences in the query with various quote styles and nested paths
                    import re
                    # Pattern to match any key ending with sub_tenant_id (including nested paths like "alert_rule.sub_tenant_id")
                    # followed by colon and the placeholder value "sub_tenant_id"
                    # Replace the value with actual SUB_TENANT_ID (always use double quotes)
                    patterns = [
                        # Match keys with double quotes, values with double quotes (handles nested paths)
                        (r'("(?:[^"]*\.)?sub_tenant_id"\s*:\s*)"sub_tenant_id"', r'\1"' + SUB_TENANT_ID + '"'),
                        # Match keys with double quotes, values with single quotes
                        (r'("(?:[^"]*\.)?sub_tenant_id"\s*:\s*)\'sub_tenant_id\'', r'\1"' + SUB_TENANT_ID + '"'),
                        # Match keys with single quotes, values with double quotes
                        (r'(\'(?:[^\']*\.)?sub_tenant_id\'\s*:\s*)"sub_tenant_id"', r'\1"' + SUB_TENANT_ID + '"'),
                        # Match keys with single quotes, values with single quotes
                        (r'(\'(?:[^\']*\.)?sub_tenant_id\'\s*:\s*)\'sub_tenant_id\'', r'\1"' + SUB_TENANT_ID + '"'),
                    ]
                    
                    for pattern, replacement in patterns:
                        mongoagent_response = re.sub(pattern, replacement, mongoagent_response)

                    try:
                        query_start = time.time()
                        results = query_runner.run(mongoagent_response, limit=10)
                        query_elapsed = time.time() - query_start
                        total_elapsed = time.time() - start_time
                        print(f"⏱️  Query execution completed in {query_elapsed:.2f}s (Total: {total_elapsed:.2f}s)")

                        # Convert results list to string for the response generator
                        results_str = json.dumps(results, indent=2, default=str) if results else "[]"
                        
                        response_start = time.time()
                        human_response = generate_human_response(user_message, refined_message, results_str)
                        response_elapsed = time.time() - response_start
                        final_elapsed = time.time() - start_time
                        
                        print(f"\nResponse: {human_response}")
                        print(f"⏱️  Response generation completed in {response_elapsed:.2f}s (Total: {final_elapsed:.2f}s)\n")
                        
                        # Save fleet conversation to MongoDB
                        history_saver.save_fleet_message(
                            user_input=user_message,
                            refined_message=refined_message,
                            selected_collections=selected_collections,
                            query=mongoagent_response,
                            query_response=results,
                            human_response=human_response
                        )
                        
                        # Update the last history entry with the actual human response instead of "LLM RESPONSE"
                        # (The question was already added to history in process_message)
                        if classifier.conversation_history:
                            classifier.conversation_history[-1]["assistant"] = human_response
                        
                    except Exception as query_error:
                        print(f"\nError executing query: {query_error}")
                        import traceback
                        traceback.print_exc()
                else:
                    # Type is NOT "invalid" - use FleetiReports response
                    
                    # Check if message field is not empty - this IS the final response
                    if response_message and response_message.strip():
                        final_response = response_message
                        print(f"\nResponse: {final_response}")
                        print(f"⏱️  FleetiReports processing completed in {fleeti_elapsed:.2f}s (Total: {total_elapsed:.2f}s)\n")
                        
                        # Save FleetiReports response as fleet message
                        history_saver.save_fleet_message(
                            user_input=user_message,
                            refined_message=refined_message,
                            selected_collections=[],
                            query="",
                            query_response=[],
                            human_response=final_response
                        )
                        
                        # Update classifier history
                        if classifier.conversation_history:
                            classifier.conversation_history[-1]["assistant"] = final_response
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
                        
                        print(f"\nResponse:\n{final_response}")
                        print(f"⏱️  FleetiReports processing completed in {fleeti_elapsed:.2f}s (Total: {total_elapsed:.2f}s)\n")
                        
                        # Save FleetiReports response as fleet message
                        history_saver.save_fleet_message(
                            user_input=user_message,
                            refined_message=refined_message,
                            selected_collections=[],
                            query="",
                            query_response=api_response_data if api_response_data else [],
                            human_response=final_response
                        )
                continue
        except KeyboardInterrupt:
            print("\n\nGoodbye!")
            break
        except Exception as e:
            print(f"\nError: {e}\n")


if __name__ == "__main__":
    main()