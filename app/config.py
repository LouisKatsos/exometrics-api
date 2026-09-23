from pydantic_settings import BaseSettings
from typing import List, Optional


class Settings(BaseSettings):
    mongo_uri: str = 'mongodb://localhost:27017'
    db_name: str = 'exometrics'
    firebase_credentials_path: str = 'firebase-service-account.json'
    firebase_credentials_json: Optional[str] = None
    cors_origins: List[str] = ['*']

    class Config:
        env_file = '.env'


settings = Settings()
