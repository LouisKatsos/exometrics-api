from pydantic import BaseModel, EmailStr
from typing import Optional
from datetime import datetime


class UserCreate(BaseModel):
    display_name: str
    diabetes_type: Optional[str] = None
    diagnosis_year: Optional[int] = None


class UserUpdate(BaseModel):
    display_name: Optional[str] = None
    diabetes_type: Optional[str] = None
    diagnosis_year: Optional[int] = None
    clinician_id: Optional[str] = None
    preferences: Optional[dict] = None


class UserResponse(BaseModel):
    id: str
    firebase_uid: str
    email: str
    display_name: str
    diabetes_type: Optional[str] = None
    diagnosis_year: Optional[int] = None
    created_at: datetime
    updated_at: datetime
