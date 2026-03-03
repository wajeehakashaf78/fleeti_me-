import os
from dotenv import load_dotenv
from openai import OpenAI

# Load API key from .env
load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

def generate_llm_response(user_input: str, refined_input: str, db_response: str) -> str:
    """
    Generate a natural language answer for the user based on their question,
    a refined version of it, and a database query response.
    
    Args:
        user_input: Original user question as asked.
        refined_input: Contextually complete version of the user question.
        db_response: Raw data or output returned by the database query.
        
    Returns:
        str: A human-readable, natural language response.
    """

    prompt = f"""
You are a helpful AI assistant in a fleet management system.
You will receive:
1. The user's original question
2. A refined version of the same question (context-complete)
3. The database's response to that refined question

Your task:
- Write a clear, friendly, human-readable answer in fluent English.
- Use the database response to directly answer the user's intent.
- If the database response is empty or irrelevant, respond naturally that no relevant data was found.
- Do not expose SQL queries, JSON data, or raw field names.
- If numbers, dates, or vehicle identifiers appear in the database response, present them clearly.
- Keep it short (2–5 sentences) and conversational.
- If there are coordinates in the database response, make a google maps link for the location.
- Do not make up random reasons for errors, if the reason is obvious in the data provided to you. Just tell the user that you ran into a problem and starting a new conversation might help.

Input details:
User question: "{user_input}"
Refined question: "{refined_input}"
Database response: {db_response}

Now write your final answer to the user in natural English.
"""

    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": "You are a helpful assistant that explains database results in natural English."},
            {"role": "user", "content": prompt}
        ],
        temperature=0.4,
        max_tokens=400,
    )

    return response.choices[0].message.content.strip()

if __name__ == "__main__":
    # Example usage
    user_input = input("Enter user question: ")
    refined_input = input("Enter refined question: ")
    db_response = input("Enter database response: ")
    
    print("\n--- LLM Response ---")
    print(generate_llm_response(user_input, refined_input, db_response))
