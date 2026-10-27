import json
import logging
from typing import Callable, Optional

import firebase_admin
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from firebase_admin import auth, credentials
from starlette.concurrency import run_in_threadpool

from app.config import settings
from app.ratelimit import RateLimiter

logger = logging.getLogger(__name__)

# auto_error=False so a missing header gives our own 401 (not FastAPI's 403/422).
bearer_scheme = HTTPBearer(auto_error=False)
rate_limiter = RateLimiter()


def init_firebase() -> None:
    """Initialises the Firebase Admin SDK once. Called at startup."""
    try:
        firebase_admin.get_app()
        return
    except ValueError:
        pass  # not initialised yet

    try:
        if settings.firebase_credentials_json:
            cred = credentials.Certificate(json.loads(settings.firebase_credentials_json))
        else:
            cred = credentials.Certificate(settings.firebase_credentials_path)
    except Exception as exc:
        raise RuntimeError(
            'Firebase credentials not found or invalid. Set FIREBASE_CREDENTIALS_JSON to the '
            'service account JSON, or FIREBASE_CREDENTIALS_PATH to the file '
            f'(currently {settings.firebase_credentials_path!r}).'
        ) from exc
    firebase_admin.initialize_app(cred)


def _verify_with_firebase(token: str) -> dict:
    return auth.verify_id_token(token, check_revoked=settings.check_revoked_tokens)


# Replaced in tests. Takes the raw token, returns the decoded claims or raises.
token_verifier: Callable[[str], dict] = _verify_with_firebase


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(status_code=401, detail=detail, headers={'WWW-Authenticate': 'Bearer'})


async def get_current_user(
    creds: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
) -> dict:
    if creds is None or creds.scheme.lower() != 'bearer' or not creds.credentials.strip():
        raise _unauthorized('Missing or malformed Authorization header')
    try:
        # verify_id_token does blocking work (key fetch, crypto); keep it off the event loop.
        decoded = await run_in_threadpool(token_verifier, creds.credentials.strip())
    except Exception as exc:
        logger.info('Rejected token: %s', type(exc).__name__)
        raise _unauthorized('Invalid or expired token')

    uid = decoded.get('uid') if isinstance(decoded, dict) else None
    if not uid:
        raise _unauthorized('Invalid or expired token')

    retry_after = rate_limiter.hit(uid, settings.rate_limit_per_minute)
    if retry_after is not None:
        raise HTTPException(
            status_code=429,
            detail='Too many requests',
            headers={'Retry-After': str(retry_after)},
        )
    return decoded
