from pydantic_settings import BaseSettings
from functools import lru_cache
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]
# backend/app/config.py
# parents[0] -> app
# parents[1] -> backend
# parents[2] -> trading-platform (root)

from typing import Optional

class Settings(BaseSettings):
    DATABASE_URL: str
    SECRET_KEY: str
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    ENCRYPTION_KEY: str
    
    # AI & Notification Bot Config
    GEMINI_API_KEY: Optional[str] = None
    GEMINI_MODEL: str = "gemini-1.5-flash"
    DEEPSEEK_API_KEY: Optional[str] = None
    DEEPSEEK_MODEL: str = "deepseek-chat"
    AI_ENGINE_FALLBACK: bool = True
    OPENAI_API_KEY: Optional[str] = None
    EMAIL_HOST: Optional[str] = "smtp-mail.outlook.com"
    EMAIL_PORT: int = 587
    EMAIL_HOST_USER: Optional[str] = "ankitkalinga03@outlook.com"
    EMAIL_HOST_PASSWORD: Optional[str] = "gcokmcbconuskhah"
    EMAIL_USE_TLS: bool = True
    ALERT_RECIPIENT_EMAIL: Optional[str] = "ankitkalinga03@outlook.com"
    TELEGRAM_BOT_TOKEN: Optional[str] = None
    TELEGRAM_CHAT_ID: Optional[str] = None
    
    class Config:
        # Check both app directory .env and root .env
        env_file = (Path(__file__).resolve().parent.parent / ".env", BASE_DIR / ".env")
        env_file_encoding = "utf-8"
        extra = "allow"

@lru_cache()
def get_settings():
    return Settings()

settings = get_settings()