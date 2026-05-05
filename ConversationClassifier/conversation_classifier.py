"""
Conversation Classifier using Meta-Llama-3-8B-Instruct
Classifies user messages as "general conversation", "fleet", or "report"
and refines user questions based on conversation history.
"""

import os
import logging
import re
from typing import List, Tuple, Dict
from dotenv import load_dotenv
try:
    from openai import OpenAI  # type: ignore
except Exception:
    OpenAI = None

logger = logging.getLogger(__name__)


_REPORT_INTENT_RE = re.compile(
    r"\b("
    r"report|statistics|fleet\s+statistics|fleet\s+summary|performance\s+summary|"
    r"trip\s+report|sim\s+report|fuel\s+trip\s+consumption|odometer\s+report|"
    r"utilization\s+report|work\s+hour\s+report|stop\s+time\s+report|idle\s+time\s+report|"
    r"geofence\s+report|raw\s+data\s+report|track\s+data\s+report|all\s+parameters|"
    r"over\s*speeding\s+report|driving\s+behaviou?r\s+report|temperature\s+.*report|"
    r"humidity\s+.*report|weight\s+sensor\s+report|commands?\s+history\s+report|"
    r"events\s+report|wasl\s+report"
    r")\b",
    flags=re.IGNORECASE,
)

_DATE_OR_TIME_RE = re.compile(
    r"\b("
    r"\d{4}-\d{1,2}-\d{1,2}|\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?|"
    r"jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|"
    r"jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?|"
    r"today|yesterday|tomorrow|last\s+\w+|this\s+\w+|previous\s+\w+|"
    r"from|between|since|until|till|date\s+range|time\s+range|"
    r"\d{1,2}\s*(?:am|pm)|\d{1,2}:\d{2}"
    r")\b",
    flags=re.IGNORECASE,
)

_FOLLOW_UP_CONTEXT_RE = re.compile(
    r"\b(same|same parameters|same dates|same report|as well|also|with the same filters|repeat|what about)\b",
    flags=re.IGNORECASE,
)

_INVENTED_DATE_RANGE_RE = re.compile(
    r"\s*(?:[.;,]\s*)?"
    r"(?:Time range|Date range)\s*:\s*"
    r"(?:latest available data|latest available|not specified|none|no date range provided|no time range provided)"
    r"\s*(?:\([^)]*\))?\s*[.;]?",
    flags=re.IGNORECASE,
)


def _looks_like_report_request(*texts: str) -> bool:
    combined = " ".join(text for text in texts if text)
    return bool(_REPORT_INTENT_RE.search(combined))


def _sanitize_refined_message(
    refined_message: str,
    user_message: str,
    conversation_history: str = "",
) -> str:
    """
    Remove model-invented default date/time clauses unless the user explicitly
    provided date context or safely asked to carry it forward from history.
    """
    has_user_time_context = bool(_DATE_OR_TIME_RE.search(user_message or ""))
    can_carry_history_time = bool(
        _FOLLOW_UP_CONTEXT_RE.search(user_message or "")
        and _DATE_OR_TIME_RE.search(conversation_history or "")
    )
    if has_user_time_context or can_carry_history_time:
        return refined_message

    cleaned = _INVENTED_DATE_RANGE_RE.sub("", refined_message).strip()
    cleaned = re.sub(r"\s{2,}", " ", cleaned)
    cleaned = re.sub(r"\s+([.;,])", r"\1", cleaned)
    return cleaned.strip(" ;,") or refined_message


class ConversationClassifier:
    def __init__(self, model_name: str = "gpt-5-mini"):
        """
        Initialize the conversation classifier using OpenAI Chat Completions.
        
        Args:
            model_name: OpenAI model name (can be overridden by OPENAI_MODEL env var)
        """
        # Load env and set up OpenAI client
        load_dotenv()
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key or OpenAI is None:
            logger.debug("OpenAI not available or OPENAI_API_KEY missing. Classification will not run.")
            self.client = None
        else:
            try:
                self.client = OpenAI(api_key=api_key)
            except Exception as e:
                logger.debug("Failed to initialize OpenAI client: %s", e)
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
A) classify the message as exactly one of: "report", "fleet", or "general conversation"
B) produce a refined user message that is complete and ready for the next read-only layer, using conversation history when appropriate
C) produce a response only when classification is "general conversation"

========================
CONTEXT YOU MAY USE
========================
Previous conversation (chronological; latest is most recent):
{conversation_history if conversation_history else "N/A"}

Current user message:
{user_message}

========================
CLASSIFICATION DECISION ORDER
========================
Follow this order exactly:

1) GENERAL CONVERSATION OVERRIDE:
If the user asks for internal database IDs / UIDs / _id / primary keys, or asks for any write operation (create, update, delete, insert, modify, remove, change, edit), classify as "general conversation" and respond that the assistant supports read-only fleet queries only.

2) REPORT:
If the user is asking for any report, classify as "report".
This includes any request that uses the word "report", or report-like product names such as fleet statistics, fleet summary, fleet performance summary, SIM, fuel trip consumption, odometer, utilization, work hour, stop time, idle time, geofence, raw data, track data, all parameters, over speeding, driving behaviour/behavior, temperature, humidity, weight sensor, commands history, events, or WASL, etc.
Examples that MUST be "report":
- "give me fleet statistics report vehicle with the plate number LEB 8172"
- "fleet summary for LEB 8172"
- "show trip report for vehicle 123 ABC"
- "generate odometer report for yesterday"

3) FLEET:
If the user asks for stored fleet data but is not asking for a report, classify as "fleet".
Examples: latest location, current speed, ignition status, driver of a vehicle, device installed, alerts/events data lookup, trip details, route/history playback, fuel/maintenance/utilization values, etc.

4) GENERAL CONVERSATION:
If none of the above apply, classify as "general conversation".

========================
CORE INTENT
========================
This assistant supports READ-ONLY queries against a fleet management database.

It handles:
- Telemetry data (location, trips, routes, speed, idling, ignition, fuel, sensors, alerts)
- Fleet asset metadata (vehicles, drivers, devices, assignments, groups)
- Reports and summaries derived from stored fleet data

It does NOT handle:
- Conceptual explanations about fleet tracking as an industry
- General knowledge about tracking technologies
- Business strategy discussions
- Opinions, advice, or unrelated topics
- Any write or modification operations

========================
DEFINITIONS
========================
"Fleet" messages are ONLY those that clearly request retrieval, lookup, or summarization of data that would exist inside a fleet management database, but are NOT asking for a report.

This includes:
- Vehicle status or location
- Trip/history/route playback
- Idling/speed/alert data lookups
- Fuel/maintenance/utilization data
- Driver–vehicle assignments
- Device/IMEI lookups
- Any analytics or summary derived from stored fleet records

"Report" messages are fleet-related requests where the user's intent is to get, fetch, show, download, summarize, or view a report. If the refined question's intent is a report or links to a fleet-related report, classify it as "report".

Report classification has priority over general conversation and fleet. If the user says "report" or names a report-like output such as "fleet statistics", "fleet summary", "trip report", "odometer report", "utilization report", "idle time report", "geofence report", "raw data report", "track data report", "over speeding report", "driving behaviour report", "events report", "SIM report", "WASL report", or asks to generate/show/get/give any report for a vehicle/driver/group/date range, classification MUST be "report".


"General conversation" includes:
- Greetings or chit-chat
- Conceptual or educational questions about fleet tracking
- Product capability questions not tied to specific stored data
- Business discussions
- Hypothetical scenarios
- Unclear/gibberish input
- Anything unrelated to stored fleet database records

If a message mentions the word "fleet" but does NOT request specific stored data and is NOT a report request, it is "general conversation".

========================
SPECIAL OVERRIDE (CRITICAL)
========================
If the user asks for:
- Internal database IDs / UIDs / _id / primary keys
OR
- Any write operation (CREATE, UPDATE, DELETE, INSERT, MODIFY, REMOVE, CHANGE, EDIT)

THEN classification MUST be "general conversation"
even if the topic is fleet-related.

In such cases, the assistant must respond that it supports read-only fleet queries only.

========================
REFINEMENT GOAL
========================
Produce a refined version of the current user message that:
- Preserves the user’s intent
- Is ready to be sent to a READ-ONLY database/query layer
- Is as complete as possible by carrying forward relevant context from the conversation history WHEN it is safe and clearly intended
- Do NOT replace 'Fleet summary report' request with 'Fleet Performance Summary' report in your refinement and vice versa. These are two completly different report types.
- Do NOT add a time range, date range, "latest available data", "no date range provided", or any default period unless the user explicitly gave it or intends to reuse it from history.

You are allowed (and expected) to add missing context ONLY when ALL conditions below hold:

1) The current message contains an explicit reference like:
   - "same", "same parameters", "same dates", "same report", "as well", "also",
     "do that for X too", "check X as well", "with the same filters", "repeat for X"
   OR the current message is clearly a follow-up (e.g., "what about ABC?")

2) The missing context exists explicitly in the conversation history.

3) The carry-forward is unambiguous.

4) In case the user does not mention a year with the date and there are no dates in the provided context, consider the year to be 2026 in the refined user question. 

If any of these are not satisfied, DO NOT guess.

========================
CONTEXT PRIORITY WHEN CARRYING FORWARD
========================
If the follow-up implies "same as before", reuse in this order:

1) Report/intent type (trip report, location, idling report, alerts summary, etc.)
2) Target entity (vehicle name/plate, driver name, device IMEI)
3) Time range (keep relative phrasing like "today", "till today")
4) Filters (status, ignition, speed threshold, geofence, etc.)
5) Output expectation (summary vs detailed)

Never invent identifiers.

========================
PRONOUN RESOLUTION
========================
- Replace pronouns like "it", "its", "that vehicle" with the most recent unambiguous entity.
- If multiple candidates exist, do NOT guess.

========================
TYPOS / IDENTIFIERS
========================
- Fix obvious grammar only if it improves clarity.
- Never autocorrect identifiers (plate numbers, names, codes, IMEIs).

========================
LANGUAGE POLICY
========================
- Refined message must be in English.
- If the current user message is in Arabic, translate it to English for the refined message while preserving identifiers exactly (plate numbers, names, codes, IMEIs, etc.).
- If the current user message is not Arabic, still keep refined message in English.
- For the assistant RESPONSE when classification is "general conversation":
  - If current user message is Arabic, respond in Arabic.
  - Otherwise respond in English.

========================
TASKS
========================
1) CLASSIFICATION:
Output exactly one label, following the classification decision order above:
- "report"
- "fleet"
- "general conversation"

2) REFINED MESSAGE:
- If fleet or report: produce the most context-complete refined query possible.
- If general conversation: produce an English refined message that preserves the user intent.

3) RESPONSE:
- If classification is "general conversation":
    * If requesting IDs or write operations → say you support read-only fleet queries only.
    * If unclear/gibberish → say you’re not sure and can help with fleet data questions.
    * Otherwise → respond appropriately and helpfully.
- If classification is "fleet" or "report": output "N/A"

========================
STRICT OUTPUT FORMAT
========================
Return exactly three lines, no extra text:

refined message: <text>
classification: <general conversation|fleet|report>
response: <text or N/A>
"""

        
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

        if _looks_like_report_request(refined_message, response):
            classification = "report"
            llm_response = ""
        
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
            lowered_fallback = refined_fallback.lower()
            if _looks_like_report_request(lowered_fallback):
                classification_fallback = "report"
            elif any(k in lowered_fallback for k in ["vehicle", "plate", "alert", "driver", "device"]):
                classification_fallback = "fleet"
            else:
                classification_fallback = "general conversation"
            # print()
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
            reasoning_effort="low",
            max_completion_tokens=300
        )
        response = (resp.choices[0].message.content or "").strip() if getattr(resp, "choices", None) else ""
        
        # Parse response
        refined_message, classification, llm_response = self.parse_response(response)
        refined_message = _sanitize_refined_message(
            refined_message,
            user_message,
            conversation_history,
        )

        if _looks_like_report_request(user_message, refined_message):
            classification = "report"
            llm_response = ""
        
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
