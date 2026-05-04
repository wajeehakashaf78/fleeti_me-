#!/usr/bin/env python3
"""
Script to run Ollama mongoagent:latest model and save results.

This script:
1. Reads the prompt from prompt.py
2. Runs Ollama mongoagent:latest model
3. Saves responses as JSON files with incremental naming (1.json, 2.json, ...)
"""

import json
import sys
import gc
import logging
from pathlib import Path
from typing import Dict, Any
from datetime import datetime
import os

logger = logging.getLogger(__name__)


def print(*args: Any, **kwargs: Any) -> None:
    logger.debug(" ".join(str(arg) for arg in args))

# Optionally load environment variables from a .env file if available
try:
    from dotenv import load_dotenv  # type: ignore
    load_dotenv()
except Exception:
    pass

try:
    from openai import OpenAI
except Exception:
    OpenAI = None

# Import the prompt from prompt.py
try:
    from FleetiMongoagent.prompt import PROMPT
except ImportError:
    print("❌ Error: Could not import PROMPT from prompt.py")
    print("   Please make sure prompt.py exists and contains a PROMPT variable")
    sys.exit(1)

# No additional model imports needed - using Ollama directly


def get_next_file_number(output_dir: str) -> int:
    """
    Get the next file number by checking existing JSON files in the output directory.
    
    Args:
        output_dir: Path to the output directory
        
    Returns:
        Next file number to use (1 if directory is empty)
    """
    output_path = Path(output_dir)
    
    # Create directory if it doesn't exist
    output_path.mkdir(parents=True, exist_ok=True)
    
    # Find all JSON files with numeric names
    json_files = []
    for file in output_path.glob("*.json"):
        try:
            # Extract number from filename (e.g., "1.json" -> 1)
            num = int(file.stem)
            json_files.append(num)
        except ValueError:
            # Skip files that don't match the pattern (e.g., "config.json")
            continue
    
    if not json_files:
        return 1
    
    # Return the maximum number + 1
    return max(json_files) + 1


def run_ollama_model(prompt: str) -> Dict[str, Any]:
    """
    Run the OpenAI model to generate the MongoDB aggregation query.
    
    Args:
        prompt: Full prompt string including schema and question
        
    Returns:
        Dictionary with model name, query, and metadata
    """
    print("🤖 Running OpenAI model (chat.completions)...")

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return {
            "model": "openai",
            "success": False,
            "error": "OPENAI_API_KEY not set in environment",
            "timestamp": datetime.now().isoformat()
        }

    if OpenAI is None:
        return {
            "model": "openai",
            "success": False,
            "error": "openai package not installed. Please install with: pip install openai",
            "timestamp": datetime.now().isoformat()
        }

    try:
        client = OpenAI(api_key=api_key)
        model_name = os.getenv("MONGOAGENT_OPENAI_MODEL", "gpt-5.4-mini")

        resp = client.chat.completions.create(
            model=model_name,
            messages=[
                {"role": "user", "content": prompt}
            ],
            reasoning_effort="low",
            max_completion_tokens=800
        )

        response_text = (resp.choices[0].message.content or "").strip() if resp.choices else ""

        if response_text:
            # Extract the query from the raw response
            extracted_query = extract_query_from_response(response_text)
            return {
                "model": f"openai-{model_name}",
                "success": True,
                "query": extracted_query,
                "raw_response": response_text,
                "timestamp": datetime.now().isoformat()
            }
        else:
            return {
                "model": f"openai-{model_name}",
                "success": False,
                "error": "Empty response from OpenAI",
                "timestamp": datetime.now().isoformat()
            }
    except Exception as e:
        return {
            "model": "openai",
            "success": False,
            "error": str(e),
            "timestamp": datetime.now().isoformat()
        }


def save_results(output_dir: str, results: Dict[str, Any], file_number: int):
    """
    Save results to a JSON file.
    
    Args:
        output_dir: Output directory path
        results: Dictionary containing the model result
        file_number: File number to use for naming
    """
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    
    output_file = output_path / f"{file_number}.json"
    
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    
    print(f"✅ Results saved to: {output_file}")

def extract_query_from_response(raw_response: str) -> str:
    """
    Extract the MongoDB query from the raw response.
    Extracts text from 'db.' to '])' including both markers.
    
    Args:
        raw_response: The full raw response from the model
        
    Returns:
        The extracted query, or the original response if extraction fails
    """
    # Find the first occurrence of 'db.'
    db_start = raw_response.find('db.')
    
    if db_start == -1:
        # If 'db.' not found, return original response
        return raw_response
    
    # Find the last occurrence of '])' after 'db.'
    # Search from the position after 'db.'
    search_start = db_start + 3
    closing_pos = raw_response.rfind('])', search_start)
    
    if closing_pos == -1:
        # If '])' not found, return from 'db.' to end
        return raw_response[db_start:]
    
    # Extract from 'db.' to '])' including both (add 2 to include '])')
    return raw_response[db_start:closing_pos + 2]


def main():
    """Main function to run Ollama model and save results."""
    print("=" * 60)
    print("MongoDB Query Generator - OpenAI Runner")
    print("=" * 60)
    
    # Output directory
    output_dir = "output"
    
    # File output disabled: do not save FleetiMongoagent/output files.
    # file_number = get_next_file_number(output_dir)
    file_number = None
    print("\n📁 Output file saving is disabled.")
    
    # Prepare results dictionary
    results = {
        "file_number": file_number,
        "prompt": PROMPT,
        "timestamp": datetime.now().isoformat(),
        "model": {}
    }
    
    # Run Ollama model
    print("\n" + "=" * 60)
    print("Running Model")
    print("=" * 60)
    
    ollama_result = run_ollama_model(PROMPT)
    results["model"] = ollama_result
    
    if ollama_result["success"]:
        print(f"   ✅ Success: Generated query")
    else:
        print(f"   ❌ Error: {ollama_result.get('error', 'Unknown error')}")
    
    # Clean up
    gc.collect()
    
    # Save results
    print("\n" + "=" * 60)
    print("Saving Results")
    print("=" * 60)
    # File output disabled: do not save FleetiMongoagent/output files.
    # save_results(output_dir, results, file_number)
    
    # Print summary
    print("\n" + "=" * 60)
    print("Summary")
    print("=" * 60)
    if ollama_result.get("success", False):
        print(f"✅ Success: Query generated successfully")
    else:
        print(f"❌ Error: {ollama_result.get('error', 'Unknown error')}")
    print("📄 Output file: disabled")
    print("=" * 60)


def orchistrator_main(full_prompt):
    """Main function to run Ollama model and save results."""
    print("=" * 60)
    print("MongoDB Query Generator - OpenAI Runner")
    print("=" * 60)
    
    # Output directory
    output_dir = "FleetiMongoagent/output"
    
    # File output disabled: do not save FleetiMongoagent/output files.
    # file_number = get_next_file_number(output_dir)
    file_number = None
    print("\n📁 Output file saving is disabled.")
    
    # Prepare results dictionary
    results = {
        "file_number": file_number,
        "prompt": full_prompt,
        "timestamp": datetime.now().isoformat(),
        "model": {}
    }
    
    # Run Ollama model
    print("\n" + "=" * 60)
    print("Running Model")
    print("=" * 60)
    
    ollama_result = run_ollama_model(full_prompt)
    results["model"] = ollama_result
    
    if ollama_result["success"]:
        print(f"   ✅ Success: Generated query")
    else:
        print(f"   ❌ Error: {ollama_result.get('error', 'Unknown error')}")
    
    # Clean up
    # gc.collect()
    
    # Save results
    print("\n" + "=" * 60)
    print("Saving Results")
    print("=" * 60)
    # File output disabled: do not save FleetiMongoagent/output files.
    # save_results(output_dir, results, file_number)
    
    # Print summary
    print("\n" + "=" * 60)
    print("Summary")
    print("=" * 60)
    if ollama_result.get("success", False):
        print(f"✅ Success: Query generated successfully")
    else:
        print(f"❌ Error: {ollama_result.get('error', 'Unknown error')}")
    print("📄 Output file: disabled")
    print("=" * 60)

    return ollama_result.get('query')


if __name__ == "__main__":
    main()

