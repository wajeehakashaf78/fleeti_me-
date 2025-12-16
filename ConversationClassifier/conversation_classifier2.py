"""
Conversation Classifier using Meta-Llama-3-8B-Instruct
Classifies user messages as "general conversation" or "fleet" (database query)
and refines user questions based on conversation history.
"""

import os
from typing import List, Tuple, Dict
from datetime import datetime
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
        Most recent entries are labeled to make it clear which is newest.
        
        Returns:
            Formatted conversation history string
        """
        if not self.conversation_history:
            return ""
        
        formatted = []
        total_entries = len(self.conversation_history)
        for idx, entry in enumerate(self.conversation_history):
            assistant_response = entry.get('assistant', 'LLM RESPONSE')
            # Label the most recent entry (last in list) as "MOST RECENT"
            if idx == total_entries - 1:
                label = "MOST RECENT"
            else:
                entry_num = idx + 1
                label = f"Entry {entry_num}"
            formatted.append(f"[{label}] user: {entry['user']}, assistant: \"{assistant_response}\"")
        
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
        if conversation_history:
            history_context = f"Previous conversation: {conversation_history}\n\n"
        else:
            history_context = ""
        
        # Get current year, month, and date for date refinement
        from datetime import timedelta
        now = datetime.now()
        current_year = now.year
        current_month = now.month
        current_month_name = now.strftime("%B").lower()  # e.g., "december"
        current_date = now.strftime("%Y-%m-%d")  # e.g., "2025-12-12"
        current_day = now.day  # e.g., 12
        
        # Calculate week dates
        days_since_monday = now.weekday()  # Monday = 0, Sunday = 6
        this_week_monday = now - timedelta(days=days_since_monday)
        this_week_sunday = this_week_monday + timedelta(days=6)
        last_week_sunday = this_week_monday - timedelta(days=1)
        last_week_monday = last_week_sunday - timedelta(days=6)
        
        # Calculate last Monday, Friday, Sunday
        days_ago = (now.weekday() - 0) % 7  # Monday = 0
        if days_ago == 0:
            days_ago = 7  # If today is Monday, get last Monday
        last_monday = now - timedelta(days=days_ago)
        
        days_ago = (now.weekday() - 4) % 7  # Friday = 4
        if days_ago == 0:
            days_ago = 7  # If today is Friday, get last Friday
        last_friday = now - timedelta(days=days_ago)
        
        days_ago = (now.weekday() - 6) % 7  # Sunday = 6
        if days_ago == 0:
            days_ago = 7  # If today is Sunday, get last Sunday
        last_sunday = now - timedelta(days=days_ago)
        
        # Calculate last month
        if current_month == 1:
            last_month = 12
            last_month_year = current_year - 1
        else:
            last_month = current_month - 1
            last_month_year = current_year
        last_month_name = datetime(last_month_year, last_month, 1).strftime("%B").lower()
        
        # Calculate last 3 months and 6 months
        three_months_ago = (now - timedelta(days=90)).strftime("%Y-%m-%d")
        six_months_ago = (now - timedelta(days=180)).strftime("%Y-%m-%d")
        
        # Format week dates as strings
        this_week_monday_str = this_week_monday.strftime("%Y-%m-%d")
        this_week_sunday_str = this_week_sunday.strftime("%Y-%m-%d")
        last_week_monday_str = last_week_monday.strftime("%Y-%m-%d")
        last_week_sunday_str = last_week_sunday.strftime("%Y-%m-%d")
        last_monday_str = last_monday.strftime("%Y-%m-%d")
        last_friday_str = last_friday.strftime("%Y-%m-%d")
        last_sunday_str = last_sunday.strftime("%Y-%m-%d")
        
        # Calculate quarters (always available)
        first_quarter_start = f"{current_year}-01-01"
        first_quarter_end = f"{current_year}-03-31"
        second_quarter_start = f"{current_year}-04-01"
        second_quarter_end = f"{current_year}-06-30"
        third_quarter_start = f"{current_year}-07-01"
        third_quarter_end = f"{current_year}-09-30"
        fourth_quarter_start = f"{current_year}-10-01"
        fourth_quarter_end = f"{current_year}-12-31"
        
        prompt = f"""You are a conversation classifier and question refiner for a fleet management assistant that uses Rasa for fleet-related queries.

{history_context}Current user message: {user_message}

CRITICAL PRIORITY RULES FOR VEHICLES AND REPORT TYPES:
1. VEHICLE/PLATE NUMBER PRIORITY (HIGHEST TO LOWEST):
   - FIRST PRIORITY: If the user explicitly mentions a vehicle/plate number in the CURRENT message, ALWAYS use that vehicle. IGNORE vehicles from history.
   - SECOND PRIORITY: If the current message does NOT mention a vehicle, then use the vehicle from the MOST RECENT (LAST) history entry.
   - NEVER use vehicles from older history entries if a more recent one exists (unless current message has a new vehicle).

2. REPORT TYPE PRIORITY (HIGHEST TO LOWEST):
   - FIRST PRIORITY: If the user explicitly mentions a report type in the CURRENT message, use that report type.
   - SECOND PRIORITY: If the current message does NOT mention a report type, use the report type from the MOST RECENT (LAST) history entry that contains "report".

3. EXAMPLES:
   - History: "odometer report for vehicle 390" → User: "i want this report for 3688 fhd" → Refined: "odometer report for vehicle 3688 fhd" (use "3688 fhd" from current message, "odometer report" from history)
   - History: "odometer report for vehicle 390" → User: "for 3688 fhd" → Refined: "odometer report for vehicle 3688 fhd" (use "3688 fhd" from current message, "odometer report" from history)
   - History: "odometer report for vehicle 390" → User: "sep" → Refined: "odometer report for vehicle 390 for september {current_year}" (no vehicle in current message, use "390" from history)

CRITICAL: The plate numbers and vehicle identifiers in the examples below (like "3688 FHD", "390", "488") are ONLY for illustration purposes. NEVER use these example plate numbers in your refined message. ONLY use plate numbers that are:
1. Explicitly mentioned in the user's current message, OR
2. Found in the actual conversation history (if provided above)

If no vehicle/plate number is mentioned in the user's message AND there is no conversation history, do NOT add any vehicle/plate number to the refined message.

Example: If history contains:
- Entry 1 (oldest): "idle time report for vehicle 390"
- Entry 2 (middle): "stop time report for vehicle 488"  
- Entry 3 (most recent): "odometer report for vehicle 3688 FHD"
- Current message: "sep"

You MUST use "odometer report" and "3688 FHD" from Entry 3 (most recent), NOT "idle time report" or "stop time report" from older entries.

If the user previously mentioned a report type (like "stop time report", "trips statistics report", "odometer report") or a vehicle/plate number, and the current message is clearly a continuation (e.g., "sep", "dec", "1 may to 20 may"), include the missing report type and vehicle from the MOST RECENT conversation entry ONLY.

RASA FLEET SYSTEM KNOWLEDGE:
The system handles two types of fleet queries (both classified as "fleet"):
1. REPORT REQUESTS: Requests for specific fleet reports (see report types below)
2. TEXTUAL FLEET QUERIES: Questions about vehicles, drivers, locations, etc. (e.g., "what is the location of vehicle 390?", "driver name of 3688 fhd")

AVAILABLE REPORT TYPES (use these exact names when completing context):
- "trips statistics report" (also called "trips report", "trip report", "fleet statistics report")
- "idle time report" (also called "idle report", "idling report")
- "stop time report" (also called "stop report", "stoppage report")
- "odometer report" (also called "mileage report", "distance report")
- "fuel trip consumption report" (also called "fuel consumption report", "fuel report")
- "fleet summary report" (also called "fleet overview", "summary report")
- "fleet performance summary report" (also called "fleet performance report", "performance report")
- "utilization report" (also called "work hour report", "usage report")
- "raw data report" (also called "raw report")
- "track data report" (also called "tracking report", "all parameters report", "gps data report")
- "over speeding report" (also called "speed report", "speed violation report")
- "driver behavior report" (also called "driver behaviour report", "behavior report", "driver performance report")
- "temperature & humidity report" (also called "temperature report", "humidity report", "climate report", "temp report")
- "weight sensor report" (also called "weight report", "load sensor report")
- "commands history report" (also called "commands report", "command history", "history report")
- "events report" (also called "event report", "activity report")

When refining messages:
- CRITICAL: Only normalize/add "report" if the user explicitly mentions "report" in their message. If the user asks a question without "report" (e.g., "max speed of vehicle 390", "location of 3688 fhd"), keep it as a question - do NOT add "report"
- If user says "trips report", "trip report", or "trips" (with "report" or in context of report) → use "trips statistics report" in refined message
- If user says "stop report" or "stoppage" (with "report") → use "stop time report" in refined message
- If user says "idle report" or "idling" (with "report") → use "idle time report" in refined message
- If user says "fuel report" or "consumption" (with "report") → use "fuel trip consumption report" in refined message
- If user says "driver report" or "behavior report" (with "report") → use "driver behavior report" in refined message
- If user asks a question WITHOUT "report" (e.g., "max speed of vehicle 390", "what is location of 3688 fhd", "driver name of 390"), keep it as a question - do NOT add "report" or convert to report format
- Preserve other report type names as the user said them, but normalize to the standard names above when completing context from history (only if history contains "report")

Your tasks:
1. CLASSIFICATION: Determine if the message is "general conversation" or "fleet"
   - "fleet": ANY query related to fleet management, including:
     * Report requests (e.g., "trips report for vehicle 390", "stop time report", "driver behavior report for fahadullah")
     * Textual fleet queries (e.g., "what is the location of vehicle 390?", "driver name of 3688 fhd", "show me speed of 390")
     * Questions about vehicles, drivers, locations, sensors, alerts, fleet data, etc.
   - "general conversation": Greetings, casual chat, random inputs, gibberish, questions completely unrelated to fleet data

2. REFINED MESSAGE: Produce a refined version of the user's message that is ready to be sent to a database/query layer
   - CRITICAL: DO NOT add the word "report" to the message unless the user explicitly mentions "report" in their message. If the user asks a question like "max speed of vehicle 390" or "location of 3688 fhd", keep it as a question - do NOT convert it to "max speed report" or "location report"
   - Distinguish between:
     * REPORT REQUESTS: User explicitly mentions "report" (e.g., "trips report", "stop report", "I want a report")
     * TEXTUAL FLEET QUERIES: User asks a question without "report" (e.g., "what is max speed of vehicle 390?", "location of 3688 fhd", "driver name of 390")
   - Preserve the user's original intent: if they ask a question, keep it as a question; if they request a report, keep it as a report request
   - Correct obvious spelling mistakes and minor grammar issues if it improves clarity, while preserving the user's intent and meaning
   - Resolve pronouns and references using the conversation history when unambiguous
     * If the message refers to a previously mentioned vehicle with words like "it", "its", "that one", "this", "they", "the same vehicle", "that vehicle", replace the reference with the most recent explicit vehicle identifier/name from the history (e.g., plate "123 ABC" or vehicle name)
     * If there is no clear, unambiguous reference in history, do NOT guess; keep the pronoun as-is
   - RECOGNIZE CONTINUATION PHRASES: When the user uses phrases like "now for", "for the date range", "for vehicle", "for the same vehicle", "for that vehicle", "now", "also", "and", etc., OR when the user provides only a date/month (like "sep", "dec", "1 may"), they are likely continuing a previous request. Check the conversation history from MOST RECENT to OLDEST:
     * IMPORTANT: Only extract report type from history if the MOST RECENT entry contains the word "report" - if the most recent entry is a textual fleet query (question without "report"), do NOT add "report" to the current message
     * Find the MOST RECENT (LAST) entry that contains a report type (must have "report" in it) - use ONLY that one, ignore older entries
     * Find the MOST RECENT (LAST) entry that contains a vehicle/plate number - use ONLY that one, ignore older entries
     * Normalize the report type to standard Rasa report type names from the list above (only if report type exists in history)
     * Complete the current message by including these from the MOST RECENT history entry if they're missing
     * If the most recent entry is a textual fleet query (e.g., "max speed of vehicle 390"), and current message is just a date/month, do NOT add "report" - keep it as a textual query
   - DATE/TIME REFINEMENT (IMPORTANT):
     * RELATIVE TIME EXPRESSIONS: Preserve relative time expressions as-is (do NOT convert them):
       - "last year" → keep as "last year" (do NOT convert to "year {current_year-1}" or "for the year {current_year-1}")
       - "this year" → expand to "this year {current_year}" (add the year number for clarity)
       - "current year" → expand to "current year {current_year}" (add the year number for clarity)
       - "the current year" → expand to "the current year {current_year}" (add the year number for clarity)
       - "this whole year" → expand to "this whole year {current_year}" (add the year number for clarity)
       - "last month" → expand to "last month {last_month_name} {last_month_year}" (add the month name and year)
       - "this month" → expand to "this month {current_month_name} {current_year}" (add the month name and year number for clarity)
       - "current month" → expand to "current month {current_month_name} {current_year}" (add the month name and year number for clarity)
       - "the current month" → expand to "the current month {current_month_name} {current_year}" (add the month name and year number for clarity)
       - "last week" → expand to "last week {last_week_monday_str} to {last_week_sunday_str}" (add the date range)
       - "past week" → expand to "past week {last_week_monday_str} to {last_week_sunday_str}" (same as last week)
       - "previous week" → expand to "previous week {last_week_monday_str} to {last_week_sunday_str}" (same as last week)
       - "this week" → expand to "this week {this_week_monday_str} to {this_week_sunday_str}" (add the date range)
       - "last Monday" → expand to "last Monday {last_monday_str}" (add the actual date)
       - "last Friday" → expand to "last Friday {last_friday_str}" (add the actual date)
       - "last Sunday" → expand to "last Sunday {last_sunday_str}" (add the actual date)
       - "last 3 months" → expand to "last 3 months from {three_months_ago} to {current_date}" (add the date range)
       - "last 6 months" → expand to "last 6 months from {six_months_ago} to {current_date}" (add the date range)
       - "first quarter" → expand to "first quarter {first_quarter_start} to {first_quarter_end}" (add the date range)
       - "second quarter" → expand to "second quarter {second_quarter_start} to {second_quarter_end}" (add the date range)
       - "third quarter" → expand to "third quarter {third_quarter_start} to {third_quarter_end}" (add the date range)
       - "fourth quarter" → expand to "fourth quarter {fourth_quarter_start} to {fourth_quarter_end}" (add the date range)
       - "yesterday" → keep as "yesterday"
       - "today" → expand to "today {current_date}" (add the actual date for clarity, e.g., "today 2025-12-12")
       - "current day" → expand to "current day {current_date}" (add the actual date for clarity)
       - "this day" → expand to "this day {current_date}" (add the actual date for clarity)
       - "last N days/months/weeks" → keep as-is (for other N values not explicitly listed above)
     * YEAR EXPRESSIONS: When user says "this year", "current year", "the current year", "this whole year" in the context of a date range query, expand to include the year number ({current_year}) for clarity
       - Examples: "for this year" → "for this year {current_year}", "for the current year" → "for the current year {current_year}"
       - This helps downstream systems correctly interpret the year
     * MONTH EXPRESSIONS: When user says "this month", "current month", "the current month", "last month" in the context of a date range query, expand to include the month name and year number for clarity
       - Examples: "for this month" → "for this month {current_month_name} {current_year}", "for last month" → "for last month {last_month_name} {last_month_year}"
       - This helps downstream systems correctly interpret the month and year
     * WEEK EXPRESSIONS: When user says "this week", "last week", "past week", "previous week" in the context of a date range query, expand to include the date range for clarity
       - Examples: "for this week" → "for this week {this_week_monday_str} to {this_week_sunday_str}", "for last week" → "for last week {last_week_monday_str} to {last_week_sunday_str}"
       - This helps downstream systems correctly interpret the week range
     * DAY OF WEEK EXPRESSIONS: When user says "last Monday", "last Friday", "last Sunday" (or any day), expand to include the actual date
       - Examples: "for last Monday" → "for last Monday {last_monday_str}", "events for last Friday" → "events for last Friday {last_friday_str}"
       - This helps downstream systems correctly interpret the specific day
     * DAY EXPRESSIONS: When user says "today", "current day", "this day" in the context of a date range query, expand to include the actual date ({current_date}) for clarity
       - Examples: "for today" → "for today {current_date}", "events for today" → "events for today {current_date}"
       - This helps downstream systems correctly interpret the specific day
     * QUARTER EXPRESSIONS: When user says "first quarter", "second quarter", "third quarter", "fourth quarter" in the context of a date range query, expand to include the date range
       - Examples: "for first quarter" → "for first quarter {first_quarter_start} to {first_quarter_end}", "for second quarter" → "for second quarter {second_quarter_start} to {second_quarter_end}"
       - This helps downstream systems correctly interpret the quarter range
     * MONTH RANGE EXPRESSIONS: When user says "last 3 months", "last 6 months" in the context of a date range query, expand to include the date range
       - Examples: "for last 3 months" → "for last 3 months from {three_months_ago} to {current_date}", "for last 6 months" → "for last 6 months from {six_months_ago} to {current_date}"
       - This helps downstream systems correctly interpret the month range
     * MONTH NAMES: If the message contains a month name or abbreviation (e.g., "sept", "september", "jan", "january", "feb", "february", etc.) WITHOUT a year, automatically add the current year ({current_year})
       - Examples: "sept" → "september {current_year}", "jan 2024" → keep as "january 2024" (year already present)
       - This ensures date parsing works correctly in downstream systems
     * DO NOT convert relative time expressions to absolute dates - preserve them exactly as the user said them, EXCEPT for year, month, and day expressions which should be expanded with the year number, month name, and date
   - CONTEXT COMPLETION (IMPORTANT): Fill in missing context from conversation history when the message is clearly incomplete:
     * CRITICAL VEHICLE PRIORITY: If the user explicitly mentions a vehicle/plate number in the CURRENT message (e.g., "for 3688 fhd", "vehicle 390", "3688 fhd"), ALWAYS use that vehicle from the current message. DO NOT use vehicles from history when the current message has a vehicle.
     * CRITICAL: Always use the MOST RECENT (LAST) entry in history that contains the information you need. Scan from newest to oldest, use the FIRST match you find, ignore older matches.
     * CRITICAL: NEVER use vehicle/plate numbers from the examples in this prompt (like "3688 FHD", "390"). ONLY use vehicles from the actual conversation history provided above OR from the current message. If there is no conversation history and no vehicle in current message, do NOT add a vehicle to the refined message.
     * CRITICAL: Only add "report" or report type if the MOST RECENT history entry contains the word "report". If the most recent entry is a textual fleet query (question without "report"), do NOT add "report" to the current message.
     * If the user explicitly mentions a vehicle in the current message (e.g., "for 3688 fhd", "vehicle 390"), use that vehicle and get the report type from the MOST RECENT history entry if the current message doesn't mention a report type
     * If the user previously asked for a report (the MOST RECENT entry contains "report" - normalize report type names to standard Rasa names) and now provides only a date range, month, or vehicle, include the normalized report type from the MOST RECENT history entry
     * If the user previously asked a textual fleet query (the MOST RECENT entry does NOT contain "report") and now provides only a date range or vehicle, keep it as a textual query - do NOT add "report"
     * If the user previously mentioned a vehicle/plate number and now provides only a date range or report type (WITHOUT a new vehicle), include the vehicle from the MOST RECENT history entry
     * If the user says things like "now for the date range X to Y", "for vehicle ABC", or just a month name (like "sep", "dec") after a previous report request (history contains "report"), complete the context by including the missing report type (normalized) or vehicle from the MOST RECENT relevant conversation entry
     * If the user says things like "now for the date range X to Y", "for vehicle ABC", or just a month name after a previous textual fleet query (history does NOT contain "report"), complete the context but keep it as a textual query - do NOT add "report"
     * Examples (assuming these are the MOST RECENT entries in history):
       - History (most recent): "stop report of 3688 fhd" → User: "1 may to 20 may" → Refined: "stop time report of 3688 fhd for 1 may {current_year} to 20 may {current_year}"
       - History (most recent): "stop report of 3688 fhd" → User: "now for the date range 1 may to 20 may" → Refined: "stop time report of 3688 fhd for 1 may {current_year} to 20 may {current_year}"
       - History (most recent): "trips report" → User: "for vehicle 390" → Refined: "trips statistics report for vehicle 390"
       - History (most recent): "location of 3688 fhd" → User: "what about 390" → Refined: "location of 390"
       - History (most recent): "stop report of 3688 fhd" → User: "20 sep to 30 sep" → Refined: "stop time report of 3688 fhd for 20 september {current_year} to 30 september {current_year}"
       - History (most recent): "driver behavior report" → User: "fahadullah" → Refined: "driver behavior report for fahadullah"
       - History (most recent): "driver behavior report for fahadullah" → User: "dec" → Refined: "driver behavior report for fahadullah for december {current_year}"
       - History (most recent): "odometer report for vehicle 3688 FHD" → User: "sep" → Refined: "odometer report for vehicle 3688 FHD for september {current_year}"
       - History (most recent): "odometer report for vehicle 390" → User: "i want this report for 3688 fhd" → Refined: "odometer report for vehicle 3688 fhd" (CRITICAL: Use "3688 fhd" from current message, NOT "390" from history)
       - History (most recent): "odometer report for vehicle 390" → User: "for 3688 fhd" → Refined: "odometer report for vehicle 3688 fhd" (CRITICAL: Use "3688 fhd" from current message, NOT "390" from history)
       - History (most recent): "max speed of vehicle 3688 FHD" → User: "sep" → Refined: "max speed of vehicle 3688 FHD for september {current_year}" (NOTE: No "report" added because history doesn't contain "report")
       - History (most recent): "what is location of vehicle 390" → User: "yesterday" → Refined: "what is location of vehicle 390 for yesterday" (NOTE: No "report" added)
       - IMPORTANT: If history has multiple entries like "idle report for 390" (old) and "odometer report for 3688 FHD" (recent), and user says "sep", use "odometer report" and "3688 FHD" from the MOST RECENT entry, NOT "idle report" from older entries
       - IMPORTANT: If history has "max speed of vehicle 390" (most recent, no "report") and user says "sep", do NOT add "report" - keep it as "max speed of vehicle 390 for september {current_year}"
       - CRITICAL: When user explicitly mentions a NEW vehicle in current message (e.g., "for 3688 fhd", "vehicle 390"), ALWAYS use that vehicle from current message, even if history has a different vehicle
     * Only complete context when it's clearly a continuation of a previous request and the missing information is unambiguously available in the MOST RECENT history entry
     * Do NOT complete context if the user's message is complete and self-contained
     * When normalizing report types, use the standard Rasa report type names from the list above
   - If no refinement is necessary (no typos to correct, no pronouns to resolve, no context to add, no dates to expand), return the refined message IDENTICAL to the user's message, character-for-character (do not change casing, punctuation, or spacing)
   - DO NOT convert user questions into assistant responses

3. RESPONSE: Generate an appropriate response
   - If classification is "general conversation": Provide a friendly, contextually appropriate response as a fleet assistant
   - If classification is "fleet": Leave empty
   - If the message is nonsensical or doesn't make sense (with or without history): Respond with something like I'm not sure how to help with that. I can help you with your own fleet related questions.

CRITICAL RULES:
- Preserve the user's intent; do not rewrite into an answer
- Correct spelling errors; make only minimal grammar fixes needed for clarity
- Resolve pronouns to the most recent unambiguous referenced vehicle from history; otherwise leave them unchanged
- ABSOLUTELY CRITICAL: NEVER use plate numbers or vehicle identifiers from the examples in this prompt (like "3688 FHD", "390", "488"). These are ONLY examples for illustration. ONLY use plate numbers from:
  * The user's current message, OR
  * The actual conversation history provided above
  * If neither contains a vehicle/plate number, do NOT add one - keep the refined message without a vehicle identifier
- CRITICAL: When user provides incomplete information (e.g., only a date range, month name like "sep", or vehicle), complete the context from conversation history:
  * VEHICLE PRIORITY: If the user explicitly mentions a vehicle/plate number in the CURRENT message (e.g., "for 3688 fhd", "vehicle 390", "3688 fhd"), ALWAYS use that vehicle from the current message. DO NOT use vehicles from history when current message has a vehicle.
  * ALWAYS use the MOST RECENT (LAST) entry in history that contains the information you need
  * Scan history from newest to oldest, use the FIRST match, ignore older matches
  * CRITICAL: Check if the MOST RECENT entry contains the word "report":
    - If YES (it's a report request): Include the normalized report type from that MOST RECENT entry when completing context
    - If NO (it's a textual fleet query): Do NOT add "report" - keep it as a textual query when completing context
  * If user explicitly mentions a vehicle in current message (e.g., "i want this report for 3688 fhd", "for 3688 fhd"), use that vehicle and get report type from MOST RECENT history entry if current message doesn't mention report type
  * If user previously asked for a report type (MOST RECENT entry contains "report") and now provides only a date/vehicle, include the normalized report type from that MOST RECENT entry (use standard Rasa report type names)
  * If user previously asked a textual fleet query (MOST RECENT entry does NOT contain "report") and now provides only a date/vehicle, complete the context but keep it as a textual query - do NOT add "report"
  * If user previously mentioned a vehicle (in the MOST RECENT entry) and now provides only a date/report WITHOUT a new vehicle, include the vehicle from that MOST RECENT entry
  * If user previously mentioned a driver name (in the MOST RECENT entry, for driver behavior reports) and now provides only a date, include the driver name from that MOST RECENT entry
  * This is especially important for phrases like "now for the date range X to Y", "for vehicle ABC", or just month names like "sep", "dec" - these are continuations of previous requests
  * DO NOT use older history entries if a more recent one exists with the same type of information
  * DO NOT add "report" to queries that don't contain "report" in the user's message or in the most recent history entry
  * CRITICAL EXAMPLE: History: "odometer report for vehicle 390" → User: "i want this report for 3688 fhd" → MUST use "3688 fhd" from current message, NOT "390" from history
- When normalizing report types in context completion, use the standard Rasa report type names (e.g., "stop report" → "stop time report", "trips report" → "trips statistics report")
- Only fill missing context when it's clearly incomplete AND context exists in history
- Do not make up information not in the conversation history or user's message
- CRITICAL: NEVER convert relative time expressions (like "last year", "this month", "yesterday") to absolute dates - preserve them exactly as the user said them. The downstream Rasa system can handle these expressions correctly.
- Remember: Both report requests AND textual fleet queries are classified as "fleet" - Rasa will handle the distinction internally
- EXCEPTION: For year expressions ("this year", "current year", "the current year", "this whole year"), expand them to include the year number ({current_year}) for clarity (e.g., "this year" → "this year {current_year}", "the current year" → "the current year {current_year}")
- EXCEPTION: For month expressions ("this month", "current month", "the current month"), expand them to include the month name and year number ({current_month_name} {current_year}) for clarity (e.g., "this month" → "this month {current_month_name} {current_year}", "the current month" → "the current month {current_month_name} {current_year}")
- EXCEPTION: For day expressions ("today", "current day", "this day"), expand them to include the actual date ({current_date}) for clarity (e.g., "today" → "today {current_date}", "for today" → "for today {current_date}")

Strict output format (exactly three lines, no extra text, no notes, no explanations):
refined message: [final context completed refined message]
classification: [general conversation or fleet]
response: [response text or N/A]"""
        
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
            fleet_keywords = [
                "vehicle", "plate", "alert", "driver", "device", "fleet", "report",
                "trip", "idle", "stop", "odometer", "fuel", "utilization", "speed",
                "location", "gps", "sensor", "temperature", "humidity", "weight",
                "command", "event", "behavior", "behaviour", "performance"
            ]
            classification_fallback = "fleet" if any(k in refined_fallback.lower() for k in fleet_keywords) else "general conversation"
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

