"""Helpers shared by the routers: users, idempotent inserts, safe output."""
import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Tuple

from fastapi import HTTPException
from pydantic import BaseModel
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

DEFAULT_DISPLAY_NAME = 'Exoskeleton User'
MAX_PAGE_SIZE = 500


def new_user_doc(uid: str, email: str, display_name: str) -> dict:
    now = datetime.now(timezone.utc)
    return {
        'firebase_uid': uid,
        'email': email,
        'display_name': display_name,
        'preferences': {},
        'created_at': now,
        'updated_at': now,
    }


async def get_or_create_user(db, user: dict) -> dict:
    """The caller's user document, created on first use.

    Data endpoints used to answer 404 "User not found" when /auth/register had
    not succeeded first, which left uploads stuck; creating the same document
    register would have created fixes that.
    """
    uid = user['uid']
    doc = await db.users.find_one({'firebase_uid': uid})
    if doc:
        return doc
    try:
        doc = await db.users.find_one_and_update(
            {'firebase_uid': uid},
            {'$setOnInsert': new_user_doc(uid, user.get('email', ''), DEFAULT_DISPLAY_NAME)},
            upsert=True,
            return_document=ReturnDocument.AFTER,
        )
    except DuplicateKeyError:
        # Another request created it between our read and the upsert.
        doc = await db.users.find_one({'firebase_uid': uid})
    return doc


async def get_user_or_404(db, user: dict) -> dict:
    """For read endpoints: never creates a user, same 404 as before."""
    doc = await db.users.find_one({'firebase_uid': user['uid']})
    if not doc:
        raise HTTPException(status_code=404, detail='User not found')
    return doc


def idempotency_key(kind: str, record: BaseModel) -> str:
    """Identifies a record so a re-sent copy is recognised.

    Uses the app's entryId when present; older app builds don't send one, so
    their records are identified by a hash of their content instead.
    """
    entry_id = getattr(record, 'entry_id', None)
    if entry_id:
        return f'{kind}:{entry_id}'
    payload = record.model_dump(mode='json', exclude={'entry_id'})
    canonical = json.dumps(payload, sort_keys=True, separators=(',', ':'))
    return f'{kind}#' + hashlib.sha256(canonical.encode('utf-8')).hexdigest()


async def insert_once(collection, doc: dict) -> Tuple[str, bool]:
    """Inserts doc unless a record with the same (user_id, idem_key) exists.

    Returns (id, created). The read covers databases where the unique index is
    missing; the unique index covers two requests racing each other.
    """
    query = {'user_id': doc['user_id'], 'idem_key': doc['idem_key']}
    existing = await collection.find_one(query, {'_id': 1})
    if existing:
        return str(existing['_id']), False
    try:
        result = await collection.insert_one(doc)
        return str(result.inserted_id), True
    except DuplicateKeyError:
        existing = await collection.find_one(query, {'_id': 1})
        if existing:
            return str(existing['_id']), False
        raise


def sanitize_errors(errors: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Validation errors without the submitted values (they are health data)."""
    return [
        {'loc': list(err.get('loc', ())), 'msg': err.get('msg', ''), 'type': err.get('type', '')}
        for err in errors
    ]


def clamp_page(skip: int, limit: int) -> Tuple[int, int]:
    """Old clients may send any skip/limit; clamp instead of rejecting."""
    return max(skip, 0), min(max(limit, 1), MAX_PAGE_SIZE)


def serialize(doc: dict) -> dict:
    doc['id'] = str(doc.pop('_id'))
    doc.pop('idem_key', None)
    return doc
