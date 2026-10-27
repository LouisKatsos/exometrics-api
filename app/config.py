import json
import os
from typing import Annotated, List, Optional

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    """All settings come from environment variables (or a local .env file)."""

    model_config = SettingsConfigDict(env_file='.env', extra='ignore')

    # Database
    mongo_uri: str = 'mongodb://localhost:27017'
    db_name: str = 'exometrics'
    mongo_server_selection_timeout_ms: int = 5000
    # None = decide from the URI (mongodb+srv:// or tls=true/ssl=true turn TLS on).
    mongo_tls: Optional[bool] = None

    # Firebase Admin. FIREBASE_CREDENTIALS_JSON (the service account file's
    # contents) wins over FIREBASE_CREDENTIALS_PATH when both are set.
    firebase_credentials_path: str = 'firebase-service-account.json'
    firebase_credentials_json: Optional[str] = None
    check_revoked_tokens: bool = False

    # Runtime. Render sets RENDER=true in every service, so a deploy there is
    # treated as production (docs off, HSTS on) unless ENVIRONMENT says otherwise.
    environment: str = Field(default_factory=lambda: 'production' if os.getenv('RENDER') else 'development')
    enable_docs: Optional[bool] = None
    log_level: str = 'INFO'

    # Browser origins allowed to call the API. The Android app doesn't use
    # CORS, and researchers read the data in MongoDB Atlas, so no origin is
    # allowed by default. Add exact origins for a browser client, e.g.
    # CORS_ORIGINS=https://dashboard.example.org. Accepts a JSON list or a
    # comma-separated string.
    cors_origins: Annotated[List[str], NoDecode] = []

    # Abuse limits
    max_body_bytes: int = 1_048_576
    # Per Firebase user. Old app builds upload a backlog one request per line,
    # as fast as the network allows (roughly 5-10 per second), so the limit
    # stays above that.
    rate_limit_per_minute: int = 1200
    # Per client IP, all requests: a coarse flood guard, set high because
    # several study phones can share one network address.
    ip_rate_limit_per_minute: int = 6000
    max_batch_size: int = 500

    @field_validator('cors_origins', mode='before')
    @classmethod
    def _parse_origins(cls, value):
        if isinstance(value, str):
            text = value.strip()
            if text.startswith('['):
                return json.loads(text)
            return [part.strip() for part in text.split(',') if part.strip()]
        return value

    @field_validator('environment', mode='before')
    @classmethod
    def _normalise_environment(cls, value):
        return str(value).strip().lower() if value is not None else 'development'

    @property
    def is_production(self) -> bool:
        return self.environment == 'production'

    @property
    def docs_enabled(self) -> bool:
        if self.enable_docs is not None:
            return self.enable_docs
        return not self.is_production


settings = Settings()
