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
    
    # External API Configuration
    ACCESS_TOKEN: str
    
    # MongoDB Configuration
    MONGO_URI: str
    
    # History Management
    HISTORY_TIMEOUT_SECONDS: int = 60  # 1 minute default
    
    # API Configuration
    BASE_API_URL: str = "https://qa.dev-iot.tracking.me/api/admin/reports"
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = True


# Global settings instance
settings = Settings()
