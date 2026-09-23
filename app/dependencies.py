from fastapi import Depends, HTTPException, Header
import firebase_admin
from firebase_admin import credentials, auth
from app.config import settings
import json

if settings.firebase_credentials_json:
    cred = credentials.Certificate(json.loads(settings.firebase_credentials_json))
else:
    cred = credentials.Certificate(settings.firebase_credentials_path)

firebase_admin.initialize_app(cred)


async def get_current_user(
    authorization: str = Header(...)
) -> dict:
    try:
        token = authorization.replace('Bearer ', '')
        decoded = auth.verify_id_token(token)
        return decoded
    except Exception as e:
        raise HTTPException(status_code=401, detail=f'Invalid token: {type(e).__name__}: {str(e)}')