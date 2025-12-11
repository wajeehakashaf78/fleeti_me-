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
        if conversation_history:
            history_context = f"Previous conversation: {conversation_history}\n\n"
        else:
            history_context = ""
        
        prompt = f"""You are a conversation classifier and question refiner for a fleet management assistant.

{history_context}Current user message: {user_message}

Your tasks:
1. CLASSIFICATION: Determine if the message is "general conversation" or "fleet" (a query about fleet database)
   - "fleet": Questions about vehicles, locations, alerts, sensors, fleet data, etc.
   - "general conversation": Greetings, casual chat, random inputs, gibberish, questions unrelated to fleet data

2. REFINED MESSAGE: Produce a refined version of the user's message that is ready to be sent to a database/query layer
   - Correct obvious spelling mistakes and minor grammar issues if it improves clarity, while preserving the user's intent and meaning
   - Resolve pronouns and references using the conversation history when unambiguous
     * If the message refers to a previously mentioned vehicle with words like "it", "its", "that one", "this", or "they", replace the reference with the most recent explicit vehicle identifier/name from the history (e.g., plate "123 ABC" or vehicle name)
     * If there is no clear, unambiguous reference in history, do NOT guess; keep the pronoun as-is
   - ONLY fill in missing context when:
     * The message is clearly incomplete (e.g., "what about 345 DEF" after asking about vehicle location, etc.)
     * The missing context is explicitly available in the conversation history
     * You can complete the thought without inventing new information
   - If no refinement is necessary (no typos to correct, no pronouns to resolve, no context to add), return the refined message IDENTICAL to the user's message, character-for-character (do not change casing, punctuation, or spacing)
   - DO NOT convert user questions into assistant responses

3. RESPONSE: Generate an appropriate response
   - If classification is "general conversation": Provide a friendly, contextually appropriate response as a fleet assistant
   - If classification is "fleet": Leave empty
   - If the message is nonsensical or doesn't make sense (with or without history): Respond with "I do not understand..."

CRITICAL RULES:
- Preserve the user's intent; do not rewrite into an answer
- Correct spelling errors; make only minimal grammar fixes needed for clarity
- Resolve pronouns to the most recent unambiguous referenced vehicle from history; otherwise leave them unchanged
- Only fill missing context when it's clearly incomplete AND context exists in history.
- Do not make up information not in the conversation history or user's message

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

