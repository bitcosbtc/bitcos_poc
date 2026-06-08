from pydantic_settings import BaseSettings
from functools import lru_cache
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]
# backend/app/config.py
# parents[0] -> app
# parents[1] -> backend
# parents[2] -> trading-platform (root)

class Settings(BaseSettings):
    DATABASE_URL: str
    SECRET_KEY: str
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    ENCRYPTION_KEY: str
    
    class Config:
        # env_file = ".env"
        env_file = BASE_DIR / ".env"
        env_file_encoding = "utf-8"
        extra="allow"

@lru_cache()
def get_settings():
    return Settings()

settings = get_settings()