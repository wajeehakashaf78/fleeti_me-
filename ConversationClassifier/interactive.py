"""
Interactive script for testing the Conversation Classifier.
"""

from conversation_classifier import ConversationClassifier


def main():
    """Interactive conversation classifier."""
    print("=" * 60)
    print("Conversation Classifier - Interactive Mode")
    print("=" * 60)
    print("\nInitializing OpenAI client...")
    print("Using OPENAI_API_KEY and model from OPENAI_MODEL (default gpt-5-mini).\n")
    
    # Initialize classifier
    classifier = ConversationClassifier()
    if getattr(classifier, 'client', None):
        print(f"OpenAI Model: {classifier.model_name}")
    else:
        print("Warning: OpenAI client not initialized. Falling back to heuristic classification.")
    
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
            
            if not user_message:
                continue
            
            # Handle special commands
            if user_message.lower() in ['quit', 'exit', 'q']:
                print("\nGoodbye!")
                break
            elif user_message.lower() == 'reset':
                classifier.reset_history()
                print("Conversation history cleared.\n")
                continue
            elif user_message.lower() == 'history':
                history = classifier.format_conversation_history()
                if history:
                    print(f"\nConversation History:\n{history}\n")
                else:
                    print("\nNo conversation history yet.\n")
                continue
            
            # Process message
            print("\nProcessing...")
            refined_message, classification, llm_response = classifier.process_message(user_message)
            
            # Display results
            print(f"\nRefined message: {refined_message}")
            print(f"Classification: {classification}")
            if llm_response:
                print(f"Response: {llm_response}")
            
            # Display current history
            history = classifier.format_conversation_history()
            if history:
                print(f"\nConversation History:\n{history}")
            
            print("\n" + "-" * 60 + "\n")
            
        except KeyboardInterrupt:
            print("\n\nGoodbye!")
            break
        except Exception as e:
            print(f"\nError: {e}\n")


if __name__ == "__main__":
    main()

