"""
Conversation Classifier using Meta-Llama-3-8B-Instruct
Classifies user messages as "general conversation" or "fleet" (database query)
and refines user questions based on conversation history.
"""

import os
from typing import List, Tuple, Dict
from dotenv import load_dotenv
try:
    from openai import OpenAI  # type: ignore
except Exception:
    OpenAI = None


class ConversationClassifier:
    def __init__(self, model_name: str = "gpt-4o-mini"):
        """
        Initialize the conversation classifier using OpenAI Chat Completions.
        
        Args:
            model_name: OpenAI model name (can be overridden by OPENAI_MODEL env var)
        """
        # Load env and set up OpenAI client
        load_dotenv()
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key or OpenAI is None:
            print("WARNING: OpenAI not available or OPENAI_API_KEY missing. Classification will not run.")
            self.client = None
        else:
            try:
                self.client = OpenAI(api_key=api_key)
            except Exception as e:
                print(f"Failed to initialize OpenAI client: {e}")
                self.client = None
        
        # Allow overriding model via env
        self.model_name = os.getenv("OPENAI_MODEL") or model_name
        
        # # Announce OpenAI usage (do not print the actual key)
        # if self.client:
        #     print(f"OpenAI client initialized. Using model: {self.model_name}")
        #     print("OPENAI_API_KEY detected and will be used for classification.")
        
        self.conversation_history: List[Dict[str, str]] = []
    
    def format_conversation_history(self) -> str:
        """
        Format conversation history for the prompt.
        Assistant responses use actual response if available, otherwise "LLM RESPONSE".
        
        Returns:
            Formatted conversation history string
        """
        if not self.conversation_history:
            return ""
        
        formatted = []
        for entry in self.conversation_history:
            assistant_response = entry.get('assistant', 'LLM RESPONSE')
            formatted.append(f"user: {entry['user']}, assistant: \"{assistant_response}\"")
        
        return "; ".join(formatted)
    
    def create_prompt(self, user_message: str, conversation_history: str) -> str:
        """
        Create the prompt for the LLM to classify and refine the user message.
        
        Args:
            user_message: Current user message
            conversation_history: Formatted conversation history
            
        Returns:
            Complete prompt string
        """
        
        prompt = f"""You are a conversation classifier and question refiner for a fleet management assistant.

You will be given:
- Previous conversation turns (user + assistant)
- The current user message

Your job is to:
A) classify the message as "fleet" or "general conversation"
B) produce a refined user message that is complete and ready for a read-only query layer, using conversation history when appropriate
C) produce a response only when classification is "general conversation"

========================
CONTEXT YOU MAY USE
========================
Previous conversation (chronological; latest is most recent):
{conversation_history if conversation_history else "N/A"}

Current user message:
{user_message}

========================
DEFINITIONS
========================
"Fleet" messages include: vehicle location, trip reports, route history, sensors, alerts, idling, speed, ignition, drivers, devices, odometer, geofences, fuel, maintenance, utilization, or any analytics/summary derived from fleet data.

"General conversation" includes: greetings, chit-chat, random topics, gibberish, unclear requests, or anything unrelated to fleet data.

SPECIAL OVERRIDE (CRITICAL):
If the user asks for:
- internal database IDs / UIDs / _id / primary keys of any entity
OR
- any write operation (CREATE, UPDATE, DELETE, INSERT, MODIFY, REMOVE, CHANGE, EDIT)
THEN classification MUST be "general conversation" even if fleet-related.

========================
REFINEMENT GOAL
========================
Produce a refined version of the current user message that:
- preserves the user’s intent
- is ready to be sent to a READ-ONLY database/query layer
- is as complete as possible by carrying forward relevant context from the conversation history WHEN it is safe and clearly intended

You are allowed (and expected) to add missing context ONLY when ALL conditions below hold:
1) The current message contains an explicit reference like:
   - "same", "same parameters", "same dates", "same report", "as well", "also", "do that for X too", "check X as well", "with the same filters", "repeat for X"
   OR the current message is clearly a follow-up (e.g., "what about ABC?" right after a specific report request).
2) The missing context exists explicitly in the conversation history.
3) The carry-forward is unambiguous (the most recent relevant request of that type is clear).
If any of these are not satisfied, DO NOT guess—leave the message as-is.

========================
WHAT COUNTS AS CONTEXT / PARAMETERS TO CARRY FORWARD
========================
If the follow-up implies “same as before”, try to reuse, in this priority order:
1) Report/intent type: trip report, location, route playback, idling report, speed violations, alerts summary, fuel report, etc.
2) Entity/target: vehicle identifier (plate number, vehicle name), driver name, device IMEI (but do NOT invent identifiers)
3) Time range: explicit dates/times, relative times (today/yesterday/last week), and any timezone assumptions already present
4) Filters: status, ignition on/off, min speed, geofence, group, driver, etc.
5) Output expectation: summary vs detailed list, format hints (CSV/export) ONLY if previously stated

When carrying forward relative dates like "today", keep them as the user phrased them (e.g., "till today") and DO NOT convert to absolute dates.

========================
PRONOUN / REFERENCE RESOLUTION
========================
- If the message refers to a previously mentioned vehicle with pronouns ("it", "its", "that one", "this vehicle", "they"), replace with the most recent unambiguous vehicle identifier from history.
- If multiple candidates exist, do NOT guess; keep the pronoun.

========================
TYPOS / IDENTIFIERS
========================
- Fix obvious spelling/grammar only if it improves clarity.
- Never autocorrect identifiers (plate numbers, names, codes, IMEIs, etc.).

========================
EXAMPLE (GENERIC PATTERN)
========================
Example conversation:
user: "Give me a trip report for vehicle XYZ from 12 Jan till today."
assistant: "Done / Not found / Here are results..."
user: "Check for vehicle ABC as well with the same parameters."

Expected refined message:
"Give me a trip report for vehicle ABC from 12 Jan till today."

Notes:
- Carry forward report type (trip report) + time range (12 Jan till today).
- Replace only the vehicle identifier.

Another example:
user: "Where is vehicle KSA 123 right now?"
assistant: "..."
user: "and what about KSA 999?"
Refined:
"Where is vehicle KSA 999 right now?"

Gibberish example:
user: "asdfghjkl"
Refined must be identical and classification must be general conversation.

========================
TASKS
========================
1) CLASSIFICATION: Output exactly one label:
- "fleet" or "general conversation" (apply SPECIAL OVERRIDE)

2) REFINED MESSAGE:
- If fleet: produce the most context-complete refined query you can, using the rules above.
- If general conversation: return refined message identical to the user's message unless you are correcting an obvious typo that does not alter identifiers.

3) RESPONSE:
- If classification is "general conversation":
  * If user requested IDs or write ops into the database: say this assistant supports read-only fleet queries only.
  * Else if message is gibberish/unclear: say you’re not sure and that you can help with fleet-related questions.
  * Else: friendly appropriate response.
- If classification is "fleet": output "N/A" (exactly).

========================
STRICT OUTPUT FORMAT
========================
Return exactly three lines, no extra text:
refined message: <text>
classification: <general conversation|fleet>
response: <text or N/A>"""

        
        return prompt
    
    def parse_response(self, response: str) -> Tuple[str, str, str]:
        """
        Parse the LLM response to extract refined message, classification, and response.
        
        Args:
            response: Raw LLM response text
            
        Returns:
            Tuple of (refined_message, classification, llm_response)
        """
        refined_message = ""
        classification = ""
        llm_response = ""
        
        lines = response.strip().split('\n')
        for line in lines:
            line = line.strip()
            if line.startswith("refined message:"):
                refined_message = line.replace("refined message:", "").strip()
            elif line.startswith("classification:"):
                classification = line.replace("classification:", "").strip().lower()
            elif line.startswith("response:"):
                llm_response = line.replace("response:", "").strip()
                # Handle N/A case
                if llm_response.upper() == "N/A":
                    llm_response = ""
        
        # Fallback parsing if format is slightly different
        if not refined_message or not classification:
            # Try to extract from the response more flexibly
            if "refined message" in response.lower():
                parts = response.split("refined message", 1)
                if len(parts) > 1:
                    refined_part = parts[1].split("classification")[0].strip()
                    refined_message = refined_part.replace(":", "").strip()
            
            if "classification" in response.lower():
                parts = response.split("classification", 1)
                if len(parts) > 1:
                    classification_part = parts[1].split("response")[0].strip()
                    classification = classification_part.replace(":", "").strip().lower()
            
            if "response" in response.lower() and not llm_response:
                parts = response.split("response", 1)
                if len(parts) > 1:
                    llm_response = parts[1].strip().replace(":", "").strip()
                    if llm_response.upper() == "N/A":
                        llm_response = ""
        
        # Default values if parsing fails
        if not refined_message:
            refined_message = response.strip()
        if not classification:
            classification = "general conversation"
        
        # If classification is general conversation and no response provided, generate default
        if classification == "general conversation" and not llm_response:
            llm_response = "Hello, I am your fleet assistant. How can I help you today?"
        
        return refined_message, classification, llm_response
    
    def process_message(self, user_message: str) -> Tuple[str, str, str]:
        """
        Process a user message: classify it and refine it based on conversation history.
        
        Args:
            user_message: The user's input message
            
        Returns:
            Tuple of (refined_message, classification, llm_response)
        """
        if not self.client:
            # Fallback: minimal non-LLM behavior
            refined_fallback = user_message.strip()
            classification_fallback = "fleet" if any(k in refined_fallback.lower() for k in ["vehicle", "plate", "alert", "driver", "device"]) else "general conversation"
            response_fallback = "Hello, I am your fleet assistant. How can I help you today?" if classification_fallback == "general conversation" else ""
            return refined_fallback, classification_fallback, response_fallback
        
        # Format conversation history
        conversation_history = self.format_conversation_history()
        
        # Create prompt
        prompt = self.create_prompt(user_message, conversation_history)
        
        # Build messages for OpenAI
        messages = [
            {"role": "system", "content": "You are a helpful assistant that classifies messages and refines questions based on context."},
            {"role": "user", "content": prompt}
        ]
        
        # Call OpenAI Chat Completions
        resp = self.client.chat.completions.create(
            model=self.model_name,
            messages=messages,
            temperature=0.3,
            top_p=0.9,
            max_tokens=300
        )
        response = (resp.choices[0].message.content or "").strip() if getattr(resp, "choices", None) else ""
        
        # Parse response
        refined_message, classification, llm_response = self.parse_response(response)
        
        # Update conversation history
        # For fleet queries, use "LLM RESPONSE", for general conversation use the actual response
        assistant_response = llm_response if classification == "general conversation" and llm_response else "LLM RESPONSE"
        self.conversation_history.append({
            "user": refined_message,
            "assistant": assistant_response
        })
        
        return refined_message, classification, llm_response
    
    def reset_history(self):
        """Reset the conversation history."""
        self.conversation_history = []
    
    def get_history(self) -> List[Dict[str, str]]:
        """Get the current conversation history."""
        return self.conversation_history.copy()


def main():
    """Example usage of the ConversationClassifier."""
    # Initialize classifier
    classifier = ConversationClassifier()
    
    print("\n" + "="*60)
    print("Conversation Classifier - Example Usage")
    print("="*60 + "\n")
    
    # Example 1: Simple greeting
    print("Example 1:")
    user_msg1 = "hi"
    refined1, classification1, response1 = classifier.process_message(user_msg1)
    print(f"User: {user_msg1}")
    print(f"Refined message: {refined1}")
    print(f"Classification: {classification1}")
    print(f"Response: {response1}")
    print(f"History: {classifier.format_conversation_history()}\n")
    
    # Example 2: Fleet query
    print("Example 2:")
    user_msg2 = "what is the location of the vehicle with the plate number 123 ABC?"
    refined2, classification2, response2 = classifier.process_message(user_msg2)
    print(f"User: {user_msg2}")
    print(f"Refined message: {refined2}")
    print(f"Classification: {classification2}")
    print(f"Response: {response2 if response2 else 'N/A'}")
    print(f"History: {classifier.format_conversation_history()}\n")
    
    # Example 3: Follow-up with missing context
    print("Example 3:")
    user_msg3 = "what about 345 DEF"
    refined3, classification3, response3 = classifier.process_message(user_msg3)
    print(f"User: {user_msg3}")
    print(f"Refined message: {refined3}")
    print(f"Classification: {classification3}")
    print(f"Response: {response3 if response3 else 'N/A'}")
    print(f"History: {classifier.format_conversation_history()}\n")
    
    # Example 4: Nonsensical message
    print("Example 4:")
    user_msg4 = "asdfghjkl random gibberish"
    refined4, classification4, response4 = classifier.process_message(user_msg4)
    print(f"User: {user_msg4}")
    print(f"Refined message: {refined4}")
    print(f"Classification: {classification4}")
    print(f"Response: {response4}")
    print(f"History: {classifier.format_conversation_history()}\n")


if __name__ == "__main__":
    main()
