"""
LLM Agent for Fleet Analytics Chatbot
Handles OpenAI API interactions
"""

import json
from typing import List, Dict, Optional
from openai import OpenAI
from config import settings
from prompts import get_system_prompt
from models import LLMResponse


class LLMAgent:
    """Handles interactions with OpenAI LLM"""
    
    def __init__(self):
        """Initialize OpenAI client"""
        self.client = OpenAI(api_key=settings.OPENAI_API_KEY)
        self.model = "gpt-4o-mini"  # Using cost-effective model
    
    def process_user_input(
        self, 
        user_input: str, 
        conversation_history: Optional[List[Dict]] = None
    ) -> LLMResponse:
        """
        Process user input and classify report request
        
        Args:
            user_input: User's message
            conversation_history: Previous conversation messages
            
        Returns:
            LLMResponse with classified report type and prerequisites
        """
        try:
            # Get current date for context
            from datetime import datetime
            current_date = datetime.now().strftime("%Y-%m-%d")
            current_datetime_full = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            
            # Add current date context to system prompt
            system_prompt_with_date = f"""{get_system_prompt()}

## Current Date/Time Information:
- Current Date: {current_date}
- Current Date/Time: {current_datetime_full}
- Use this information to resolve relative dates like "today", "yesterday", "last week", etc.
- When user says "today", use: {current_date}
- Format dates as: YYYY-MM-DD or YYYY-MM-DDTHH:mm:ss.SSSZ for API compatibility
"""
            
            # Build messages for API call
            messages = [
                {"role": "system", "content": system_prompt_with_date}
            ]
            
            # Add conversation history if available
            if conversation_history:
                messages.extend(conversation_history)
            
            # Add current user input
            messages.append({"role": "user", "content": user_input})
            
            # Call OpenAI API
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=0.3,  # Low temperature for more consistent responses
                response_format={"type": "json_object"}  # Enforce JSON output
            )
            
            # Extract response content
            response_content = response.choices[0].message.content
            
            # Parse JSON response
            response_data = json.loads(response_content)
            
            # Validate and create LLMResponse
            llm_response = LLMResponse(**response_data)
            
            return llm_response
            
        except json.JSONDecodeError as e:
            # If JSON parsing fails, return invalid response
            print(f"JSON parsing error: {e}")
            return LLMResponse(
                type="invalid",
                message="Failed to parse LLM response. Please try again."
            )
        
        except Exception as e:
            # Handle any other errors
            print(f"LLM processing error: {e}")
            return LLMResponse(
                type="invalid",
                message=f"An error occurred while processing your request: {str(e)}"
            )
    
    def format_response_for_history(self, llm_response: LLMResponse) -> str:
        """
        Convert LLMResponse to string for conversation history
        
        Args:
            llm_response: LLM response object
            
        Returns:
            JSON string representation
        """
        return llm_response.model_dump_json()


# Global LLM agent instance
llm_agent = LLMAgent()
