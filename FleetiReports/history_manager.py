"""
History Manager for Fleet Analytics Chatbot
Manages in-memory conversation history with auto-expiry
"""

import time
from typing import Dict, List, Tuple, Optional
from threading import Lock


class ConversationHistory:
    """Manages conversation history for sessions"""
    
    def __init__(self, timeout_seconds: int = 60):
        """
        Initialize conversation history manager
        
        Args:
            timeout_seconds: Number of seconds before a session expires
        """
        self.timeout_seconds = timeout_seconds
        # Key: (sub_tenant_id, session_id), Value: (messages, last_access_time)
        self._history: Dict[Tuple[str, str], Tuple[List[Dict], float]] = {}
        self._lock = Lock()
    
    def _get_key(self, sub_tenant_id: str, session_id: str) -> Tuple[str, str]:
        """Create a key from sub_tenant_id and session_id"""
        return (sub_tenant_id, session_id)
    
    def add_message(self, sub_tenant_id: str, session_id: str, role: str, content: str) -> None:
        """
        Add a message to conversation history
        
        Args:
            sub_tenant_id: Sub-tenant identifier
            session_id: Session identifier
            role: Message role (user/assistant)
            content: Message content
        """
        key = self._get_key(sub_tenant_id, session_id)
        current_time = time.time()
        
        with self._lock:
            if key in self._history:
                messages, _ = self._history[key]
                messages.append({"role": role, "content": content})
                self._history[key] = (messages, current_time)
            else:
                self._history[key] = ([{"role": role, "content": content}], current_time)
    
    def get_history(self, sub_tenant_id: str, session_id: str) -> List[Dict]:
        """
        Retrieve conversation history for a session
        
        Args:
            sub_tenant_id: Sub-tenant identifier
            session_id: Session identifier
            
        Returns:
            List of messages in the conversation
        """
        key = self._get_key(sub_tenant_id, session_id)
        current_time = time.time()
        
        with self._lock:
            if key not in self._history:
                return []
            
            messages, last_access = self._history[key]
            
            # Check if session has expired
            if current_time - last_access > self.timeout_seconds:
                del self._history[key]
                return []
            
            # Update last access time
            self._history[key] = (messages, current_time)
            return messages.copy()
    
    def clear_history(self, sub_tenant_id: str, session_id: str) -> None:
        """
        Clear conversation history for a session
        
        Args:
            sub_tenant_id: Sub-tenant identifier
            session_id: Session identifier
        """
        key = self._get_key(sub_tenant_id, session_id)
        
        with self._lock:
            if key in self._history:
                del self._history[key]
    
    def cleanup_expired(self) -> int:
        """
        Remove all expired sessions
        
        Returns:
            Number of sessions removed
        """
        current_time = time.time()
        expired_keys = []
        
        with self._lock:
            for key, (_, last_access) in self._history.items():
                if current_time - last_access > self.timeout_seconds:
                    expired_keys.append(key)
            
            for key in expired_keys:
                del self._history[key]
        
        return len(expired_keys)
    
    def get_session_count(self) -> int:
        """Get the number of active sessions"""
        with self._lock:
            return len(self._history)


# Global history manager instance
history_manager = ConversationHistory()
