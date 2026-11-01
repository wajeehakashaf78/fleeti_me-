"""
FleetiHistorySaver - MongoDB-based conversation history management
Saves and loads conversation history from MongoDB collection FleetiMessages
"""

import os
import json
import logging
from typing import Dict, Any, Optional
from datetime import datetime, timezone
from dotenv import load_dotenv
from pymongo import MongoClient
from bson import ObjectId

# Load environment variables
load_dotenv()
logger = logging.getLogger(__name__)


class FleetiHistorySaver:
    """
    Manages conversation history in MongoDB.
    One document per session, with messages array.
    """
    
    def __init__(
        self,
        session_id: str = "default_session",
        sub_tenant_id: str = "",
        mongo_db: Optional[str] = None,
    ):
        """
        Initialize the history saver.
        
        Args:
            session_id: Session ID (hardcoded for now, will be dynamic later)
            sub_tenant_id: Sub-tenant ID to associate with this session
        """
        mongo_uri = os.getenv("MONGO_URI")
        resolved_mongo_db = mongo_db or os.getenv("MONGO_DB")
        
        if not mongo_uri or not resolved_mongo_db:
            raise RuntimeError("MONGO_URI must be set and mongo_db must be provided (or MONGO_DB set in .env)")
        
        self.client = MongoClient(mongo_uri)
        self.db = self.client[resolved_mongo_db]
        self.db_name = resolved_mongo_db
        self.session_id = session_id
        self.sub_tenant_id = sub_tenant_id
        self.collection_name = "FleetiMessages"
        
        # Ensure collection exists
        self._ensure_collection_exists()
    
    def _ensure_collection_exists(self):
        """Create collection if it doesn't exist."""
        if self.collection_name not in self.db.list_collection_names():
            self.db.create_collection(self.collection_name)
            logger.debug("Created collection: %s", self.collection_name)

    def _compact_assistant_for_history(self, assistant_value: Any) -> str:
        """
        Keep report responses compact when sending history to LLMs.
        Full response remains in Mongo; only history context is trimmed.
        """
        if isinstance(assistant_value, dict) and "type" in assistant_value and "api_response" in assistant_value:
            return json.dumps(
                {
                    "type": assistant_value.get("type"),
                    "api_response": "valid_json_response"
                },
                separators=(",", ":")
            )
        if isinstance(assistant_value, str):
            return assistant_value
        try:
            return json.dumps(assistant_value, default=str)
        except Exception:
            return str(assistant_value)
    
    def build_carryover_note(
        self,
        session_doc: Optional[Dict[str, Any]],
        turns: int = 3,
        max_answer_chars: int = 600,
        max_query_chars: int = 400,
    ) -> Optional[str]:
        """
        Short recap of the last `turns` exchanges, used to start a NEW OpenAI conversation
        (10-turn reset, or a conversation lost on OpenAI's side) without forgetting what the
        user was talking about. Answers and queries are cut to keep the note small.
        """
        exchanges = [m for m in (session_doc or {}).get("messages", []) if (m.get("user_input") or "").strip()]
        if not exchanges or turns <= 0:
            return None

        def cut(text: str, limit: int) -> str:
            text = " ".join(str(text).split())
            return text if len(text) <= limit else text[: limit - 3] + "..."

        lines = []
        for msg in exchanges[-turns:]:
            if msg.get("type") == "general":
                answer = msg.get("llm_response", "")
            else:
                answer = self._compact_assistant_for_history(msg.get("human_response", ""))
            lines.append(f"User: {cut(msg['user_input'], max_answer_chars)}")
            if msg.get("query"):
                lines.append(f"Query used: {cut(msg['query'], max_query_chars)}")
            if answer:
                lines.append(f"Assistant: {cut(answer, max_answer_chars)}")
        return (
            "Recap of the most recent exchanges earlier in this chat (oldest first). Use it to "
            "resolve follow-up questions such as 'and yesterday?' or 'that vehicle'; fetch fresh "
            "data with the tools instead of reusing these numbers.\n" + "\n".join(lines)
        )

    def get_conversation_id(self, session_doc: Optional[Dict[str, Any]] = None) -> Optional[str]:
        """Return the stored OpenAI conversation id for this session, if any."""
        doc = session_doc if session_doc is not None else self.get_session_document()
        return (doc or {}).get("openai_conversation_id")

    def set_conversation_id(self, conversation_id: str) -> None:
        """Persist the OpenAI conversation id and reset the turn counter (new conversation)."""
        self.db[self.collection_name].update_one(
            {"sessionId": self.session_id},
            {
                "$set": {"openai_conversation_id": conversation_id, "conversation_turn_count": 0},
                "$setOnInsert": {
                    "sessionId": self.session_id,
                    "sub_tenant_id": self.sub_tenant_id,
                    "created_at": datetime.now(timezone.utc),
                },
            },
            upsert=True,
        )

    def set_conversation_turn_count(self, count: int) -> None:
        """Persist how many turns have run against the current OpenAI conversation."""
        self.db[self.collection_name].update_one(
            {"sessionId": self.session_id},
            {"$set": {"conversation_turn_count": int(count)}},
        )

    def save_general_message(self, user_input: str, llm_response: str) -> Dict[str, Any]:
        """Save a general-conversation turn (trimmed: user input + final response)."""
        message = {
            "type": "general",
            "user_input": user_input,
            "llm_response": llm_response,
            "timestamp": datetime.now(timezone.utc),
        }
        self._append_message(message)
        return message

    def save_fleet_message(self, user_input: str, query: str, human_response: Any) -> Dict[str, Any]:
        """Save a fleet turn (trimmed: user input + generated query + final response)."""
        message = {
            "type": "fleet",
            "user_input": user_input,
            "query": query,
            "human_response": human_response,
            "timestamp": datetime.now(timezone.utc),
        }
        self._append_message(message)
        return message

    def save_static_message(self, message: str, conversation_id: Optional[str] = None) -> str:
        """
        Create a new session document with a static assistant message.
        Returns the MongoDB document ID as the session ID.
        """
        new_id = ObjectId()
        doc = {
            "_id": new_id,
            "sessionId": str(new_id),
            "sub_tenant_id": self.sub_tenant_id,
            "created_at": datetime.now(timezone.utc),
            "messages": [
                {
                    "assistant_static_input": message,
                    "timestamp": datetime.now(timezone.utc)
                }
            ]
        }
        if conversation_id:
            doc["openai_conversation_id"] = conversation_id
        self.db[self.collection_name].insert_one(doc)
        logger.debug("Created new session document for sessionId: %s with sub_tenant_id: %s", str(new_id), self.sub_tenant_id)
        return str(new_id)
    
    def _append_message(self, message: Dict[str, Any]):
        """
        Append a message to the session document in MongoDB.
        Creates document if it doesn't exist, appends to messages array if it does.
        Sets sub_tenant_id when creating a new session document.
        
        Args:
            message: Message dictionary to append
        """
        # Try to update existing document
        result = self.db[self.collection_name].update_one(
            {"sessionId": self.session_id},
            {
                "$push": {"messages": message},
                "$setOnInsert": {
                    "sessionId": self.session_id,
                    "sub_tenant_id": self.sub_tenant_id,
                    "created_at": datetime.now(timezone.utc)
                }
            },
            upsert=True
        )
        
        if result.upserted_id:
            logger.debug("Created new session document for sessionId: %s with sub_tenant_id: %s", self.session_id, self.sub_tenant_id)
        else:
            logger.info("Appended message to existing session: %s", self.session_id)
    
    def get_session_document(self) -> Optional[Dict[str, Any]]:
        """
        Get the full session document from MongoDB.
        
        Returns:
            Session document or None if not found
        """
        return self.db[self.collection_name].find_one({"sessionId": self.session_id})
