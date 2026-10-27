from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from pymongo.errors import BulkWriteError

from app.config import settings
from app.database import get_db
from app.dependencies import get_current_user
from app.models.metrics import (
    FeedbackCreate,
    MetricsBatchCreate,
    MetricsEntryCreate,
    ModeChangeEventCreate,
    PowerChangeEventCreate,
)
from app.records import (
    clamp_page,
    get_or_create_user,
    get_user_or_404,
    idempotency_key,
    insert_once,
    sanitize_errors,
    serialize,
)

router = APIRouter(prefix='/metrics', tags=['metrics'])


def _identity(user_id: str, body, kind: str) -> dict:
    """Fields every stored record gets."""
    return {
        'user_id':     user_id,
        'received_at': datetime.now(timezone.utc),
        'timestamp':   body.timestamp,
        'username':    body.username,
        'participant_code': body.participant_code,
        'session_id':  body.session_id,
        'entry_id':    body.entry_id,
        'test':        body.test,
        'idem_key':    idempotency_key(kind, body),
    }


def _stored(record_id: str, created: bool):
    # New record: 201 {"id"} exactly as before. A repeat of a record we
    # already have: 200 with the original id, so the client can drop it.
    if created:
        return {'id': record_id}
    return JSONResponse(status_code=200, content={'id': record_id, 'duplicate': True})


def _owner_query(user_doc: dict, session_id: Optional[int], participant_code: Optional[str]) -> dict:
    """Records of the calling user only, optionally narrowed to one app
    session or participant code (the session_id filter is what the live API
    already offered)."""
    query = {'user_id': str(user_doc['_id'])}
    if session_id is not None:
        query['session_id'] = session_id
    if participant_code is not None:
        query['participant_code'] = participant_code
    return query


async def _list(collection, query: dict, skip: int, limit: int):
    skip, limit = clamp_page(skip, limit)
    cursor = collection.find(query).sort('timestamp', -1).skip(skip).limit(limit)
    return [serialize(doc) async for doc in cursor]


# ---------------------------------------------------------------------------
# Exercise metrics entries — one per MetricsLogger.log() call
# ---------------------------------------------------------------------------

def _metrics_doc(user_id: str, body: MetricsEntryCreate) -> dict:
    return {
        **_identity(user_id, body, 'metrics'),
        'hr':          body.hr,
        'hrv':         body.hrv,
        'hrv_slope':   body.hrv_slope,
        'hrv_source':  body.hrv_source,
        'distance_m':  body.distance_m,
        'duration_ms': body.duration_ms,
        'calories':    body.calories,
        'steps':       body.steps,
    }


@router.post('/', status_code=201)
async def create_metrics_entry(
    body: MetricsEntryCreate, user=Depends(get_current_user)
):
    db = get_db()
    user_doc = await get_or_create_user(db, user)
    record_id, created = await insert_once(db.metrics_entries, _metrics_doc(str(user_doc['_id']), body))
    return _stored(record_id, created)


@router.post('/batch')
async def create_metrics_batch(
    body: MetricsBatchCreate, user=Depends(get_current_user)
):
    """Stores many metrics entries in one request.

    Each entry gets its own result: "created", "duplicate" (already stored,
    safe to drop) or "invalid" (with the validation errors, without values).
    """
    if len(body.entries) > settings.max_batch_size:
        raise HTTPException(
            status_code=413,
            detail=f'Too many entries; the limit is {settings.max_batch_size} per request',
        )
    db = get_db()
    user_doc = await get_or_create_user(db, user)
    user_id = str(user_doc['_id'])

    results: list = [None] * len(body.entries)
    first_index_for_key: dict = {}
    repeats: dict = {}       # index -> index of the first entry with the same key
    candidates: list = []    # (index, doc) of entries that may be new

    for index, raw in enumerate(body.entries):
        try:
            entry = MetricsEntryCreate.model_validate(raw)
        except ValidationError as exc:
            results[index] = {'index': index, 'status': 'invalid', 'errors': sanitize_errors(exc.errors())}
            continue
        doc = _metrics_doc(user_id, entry)
        key = doc['idem_key']
        if key in first_index_for_key:
            repeats[index] = first_index_for_key[key]
            continue
        first_index_for_key[key] = index
        candidates.append((index, doc))

    existing = {}
    if candidates:
        keys = [doc['idem_key'] for _, doc in candidates]
        cursor = db.metrics_entries.find({'user_id': user_id, 'idem_key': {'$in': keys}}, {'idem_key': 1})
        existing = {doc['idem_key']: str(doc['_id']) async for doc in cursor}

    new_docs = []
    for index, doc in candidates:
        if doc['idem_key'] in existing:
            results[index] = {'index': index, 'status': 'duplicate', 'id': existing[doc['idem_key']]}
        else:
            new_docs.append((index, doc))

    if new_docs:
        failed = {}
        try:
            await db.metrics_entries.insert_many([doc for _, doc in new_docs], ordered=False)
        except BulkWriteError as exc:
            failed = {err['index']: err for err in exc.details.get('writeErrors', [])}
            if any(err.get('code') != 11000 for err in failed.values()):
                raise
        for position, (index, doc) in enumerate(new_docs):
            if position in failed:
                # Raced with another request storing the same record.
                stored = await db.metrics_entries.find_one(
                    {'user_id': user_id, 'idem_key': doc['idem_key']}, {'_id': 1}
                )
                results[index] = {'index': index, 'status': 'duplicate',
                                  'id': str(stored['_id']) if stored else None}
            else:
                results[index] = {'index': index, 'status': 'created', 'id': str(doc['_id'])}

    for index, first in repeats.items():
        results[index] = {'index': index, 'status': 'duplicate', 'id': (results[first] or {}).get('id')}

    counts = {'created': 0, 'duplicate': 0, 'invalid': 0}
    for result in results:
        counts[result['status']] += 1
    return {
        'results': results,
        'created': counts['created'],
        'duplicates': counts['duplicate'],
        'invalid': counts['invalid'],
    }


@router.get('/')
async def list_metrics_entries(
    skip: int = 0,
    limit: int = 50,
    session_id: Optional[int] = None,
    participant_code: Optional[str] = Query(default=None, max_length=32),
    user=Depends(get_current_user),
):
    db = get_db()
    user_doc = await get_user_or_404(db, user)
    return await _list(db.metrics_entries, _owner_query(user_doc, session_id, participant_code), skip, limit)


@router.get('/latest')
async def get_latest_metrics_entry(user=Depends(get_current_user)):
    db = get_db()
    user_doc = await get_user_or_404(db, user)
    doc = await db.metrics_entries.find_one(
        {'user_id': str(user_doc['_id'])},
        sort=[('timestamp', -1)],
    )
    if not doc:
        return None
    return serialize(doc)


# ---------------------------------------------------------------------------
# Exoskeleton events — power changes and mode changes, kept in one
# collection with a `type` discriminator so a session's timeline can be
# reconstructed by sorting on `timestamp` alone.
# ---------------------------------------------------------------------------

@router.post('/events/power', status_code=201)
async def create_power_change_event(
    body: PowerChangeEventCreate, user=Depends(get_current_user)
):
    db = get_db()
    user_doc = await get_or_create_user(db, user)

    doc = {
        **_identity(str(user_doc['_id']), body, 'power_change'),
        'type':              'power_change',
        'old_power_percent': body.old_power_percent,
        'new_power_percent': body.new_power_percent,
        'reason':            body.reason,
        'hr':                body.hr,
        'hrv':               body.hrv,
        'hrv_slope':         body.hrv_slope,
    }
    record_id, created = await insert_once(db.events, doc)
    return _stored(record_id, created)


@router.post('/events/mode', status_code=201)
async def create_mode_change_event(
    body: ModeChangeEventCreate, user=Depends(get_current_user)
):
    db = get_db()
    user_doc = await get_or_create_user(db, user)

    doc = {
        **_identity(str(user_doc['_id']), body, 'mode_change'),
        'type':     'mode_change',
        'old_mode': body.old_mode,
        'new_mode': body.new_mode,
        'hr':       body.hr,
    }
    record_id, created = await insert_once(db.events, doc)
    return _stored(record_id, created)


@router.get('/events')
async def list_events(
    skip: int = 0,
    limit: int = 50,
    type: Optional[str] = Query(default=None, max_length=32, description="'power_change' or 'mode_change'"),
    session_id: Optional[int] = None,
    participant_code: Optional[str] = Query(default=None, max_length=32),
    user=Depends(get_current_user),
):
    db = get_db()
    user_doc = await get_user_or_404(db, user)
    query = _owner_query(user_doc, session_id, participant_code)
    if type:
        query['type'] = type
    return await _list(db.events, query, skip, limit)


# ---------------------------------------------------------------------------
# Free-text feedback from the app's Feedback box
# ---------------------------------------------------------------------------

@router.post('/feedback', status_code=201)
async def create_feedback(
    body: FeedbackCreate, user=Depends(get_current_user)
):
    db = get_db()
    user_doc = await get_or_create_user(db, user)
    doc = {
        **_identity(str(user_doc['_id']), body, 'feedback'),
        'text': body.text,
    }
    record_id, created = await insert_once(db.feedback, doc)
    return _stored(record_id, created)


@router.get('/feedback')
async def list_feedback(
    skip: int = 0,
    limit: int = 50,
    session_id: Optional[int] = None,
    participant_code: Optional[str] = Query(default=None, max_length=32),
    user=Depends(get_current_user),
):
    db = get_db()
    user_doc = await get_user_or_404(db, user)
    return await _list(db.feedback, _owner_query(user_doc, session_id, participant_code), skip, limit)
