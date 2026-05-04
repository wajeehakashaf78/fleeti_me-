"""
Configuration module for Fleet Analytics Chatbot
Loads environment variables and provides application settings
"""

from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    """Application settings loaded from environment variables"""
    
    # OpenAI Configuration
    OPENAI_API_KEY: str
    OPENAI_MODEL: str = "gpt-5-mini"
    
    # External API Configuration
    ACCESS_TOKEN: str = ""
    
    # MongoDB Configuration
    MONGO_URI: str
    
    # History Management
    HISTORY_TIMEOUT_SECONDS: int = 60  # 1 minute default
    
    # API Configuration
    BASE_API_URL: str = "https://qa.dev-iot.tracking.me/api/admin/reports"
    REPORTS_API_VERIFY_SSL: bool = True
    REPORTS_API_CA_BUNDLE: Optional[str] = None
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = True
        extra = "allow"


# Global settings instance
settings = Settings()
