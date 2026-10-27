import json
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator

from app.sanitize import check_safe_keys

MAX_PREFERENCE_KEYS = 50
MAX_PREFERENCES_BYTES = 10_000


# diabetes_type / diagnosis_year / clinician_id came with the project template.
# The app doesn't use them; they stay so existing clients and data keep working.
class UserCreate(BaseModel):
    display_name: str = Field(min_length=1, max_length=100)
    diabetes_type: Optional[str] = Field(default=None, max_length=50)
    diagnosis_year: Optional[int] = Field(default=None, ge=1900, le=2100)


class UserUpdate(BaseModel):
    display_name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    diabetes_type: Optional[str] = Field(default=None, max_length=50)
    diagnosis_year: Optional[int] = Field(default=None, ge=1900, le=2100)
    clinician_id: Optional[str] = Field(default=None, max_length=100)
    preferences: Optional[dict] = None

    @field_validator('preferences')
    @classmethod
    def _limit_preferences(cls, value):
        if value is None:
            return value
        if len(value) > MAX_PREFERENCE_KEYS:
            raise ValueError(f'at most {MAX_PREFERENCE_KEYS} preference keys')
        if len(json.dumps(value, default=str)) > MAX_PREFERENCES_BYTES:
            raise ValueError(f'preferences must be under {MAX_PREFERENCES_BYTES} bytes')
        return check_safe_keys(value)


class UserResponse(BaseModel):
    id: str
    firebase_uid: str
    email: str
    display_name: str
    diabetes_type: Optional[str] = None
    diagnosis_year: Optional[int] = None
    created_at: datetime
    updated_at: datetime
