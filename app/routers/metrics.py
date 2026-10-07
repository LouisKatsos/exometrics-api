from fastapi import APIRouter, Depends, HTTPException, Query
from typing import Optional
from app.dependencies import get_current_user
from app.database import get_db
from app.models.metrics import (
    MetricsEntryCreate,
    PowerChangeEventCreate,
    ModeChangeEventCreate,
    FeedbackCreate,
)
from datetime import datetime, timezone

router = APIRouter(prefix='/metrics', tags=['metrics'])


async def _get_user_doc(db, uid: str):
    user_doc = await db.users.find_one({'firebase_uid': uid})
    if not user_doc:
        raise HTTPException(status_code=404, detail='User not found')
    return user_doc


# ---------------------------------------------------------------------------
# Exercise metrics entries — one per MetricsLogger.log() call
# ---------------------------------------------------------------------------

@router.post('/', status_code=201)
async def create_metrics_entry(
    body: MetricsEntryCreate, user=Depends(get_current_user)
):
    db = get_db()
    user_doc = await _get_user_doc(db, user['uid'])

    doc = {
        'user_id':     str(user_doc['_id']),
        'username':    body.username,
        'session_id':  body.session_id,
        'received_at': datetime.now(timezone.utc),
        'timestamp':   body.timestamp,
        'hr':          body.hr,
        'hrv':         body.hrv,
        'hrv_slope':   body.hrv_slope,
        'distance_m':  body.distance_m,
        'duration_ms': body.duration_ms,
        'calories':    body.calories,
        'steps':       body.steps,
    }
    result = await db.metrics_entries.insert_one(doc)
    return {'id': str(result.inserted_id)}


@router.get('/')
async def list_metrics_entries(
    skip: int = 0,
    limit: int = 50,
    session_id: Optional[int] = None,
    user=Depends(get_current_user),
):
    db = get_db()
    user_doc = await _get_user_doc(db, user['uid'])
    query = {'user_id': str(user_doc['_id'])}
    if session_id is not None:
        query['session_id'] = session_id
    cursor = db.metrics_entries.find(query).sort('timestamp', -1).skip(skip).limit(limit)
    results = []
    async for doc in cursor:
        doc['id'] = str(doc.pop('_id'))
        results.append(doc)
    return results


@router.get('/latest')
async def get_latest_metrics_entry(user=Depends(get_current_user)):
    db = get_db()
    user_doc = await _get_user_doc(db, user['uid'])
    doc = await db.metrics_entries.find_one(
        {'user_id': str(user_doc['_id'])},
        sort=[('timestamp', -1)],
    )
    if not doc:
        return None
    doc['id'] = str(doc.pop('_id'))
    return doc


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
    user_doc = await _get_user_doc(db, user['uid'])

    doc = {
        'user_id':           str(user_doc['_id']),
        'username':          body.username,
        'session_id':        body.session_id,
        'received_at':       datetime.now(timezone.utc),
        'timestamp':         body.timestamp,
        'type':              'power_change',
        'old_power_percent': body.old_power_percent,
        'new_power_percent': body.new_power_percent,
        'reason':            body.reason,
        'hr':                body.hr,
        'hrv':               body.hrv,
        'hrv_slope':         body.hrv_slope,
    }
    result = await db.events.insert_one(doc)
    return {'id': str(result.inserted_id)}


@router.post('/events/mode', status_code=201)
async def create_mode_change_event(
    body: ModeChangeEventCreate, user=Depends(get_current_user)
):
    db = get_db()
    user_doc = await _get_user_doc(db, user['uid'])

    doc = {
        'user_id':     str(user_doc['_id']),
        'username':    body.username,
        'session_id':  body.session_id,
        'received_at': datetime.now(timezone.utc),
        'timestamp':   body.timestamp,
        'type':        'mode_change',
        'old_mode':    body.old_mode,
        'new_mode':    body.new_mode,
        'hr':          body.hr,
    }
    result = await db.events.insert_one(doc)
    return {'id': str(result.inserted_id)}


@router.get('/events')
async def list_events(
    skip: int = 0,
    limit: int = 50,
    type: Optional[str] = Query(default=None, description="'power_change' or 'mode_change'"),
    session_id: Optional[int] = None,
    user=Depends(get_current_user),
):
    db = get_db()
    user_doc = await _get_user_doc(db, user['uid'])
    query = {'user_id': str(user_doc['_id'])}
    if type:
        query['type'] = type
    if session_id is not None:
        query['session_id'] = session_id
    cursor = db.events.find(query).sort('timestamp', -1).skip(skip).limit(limit)
    results = []
    async for doc in cursor:
        doc['id'] = str(doc.pop('_id'))
        results.append(doc)
    return results


# ---------------------------------------------------------------------------
# User feedback — one document per press of "Save Feedback" in the app
# ---------------------------------------------------------------------------

@router.post('/feedback', status_code=201)
async def create_feedback(
    body: FeedbackCreate, user=Depends(get_current_user)
):
    db = get_db()
    user_doc = await _get_user_doc(db, user['uid'])

    doc = {
        'user_id':     str(user_doc['_id']),
        'username':    body.username,
        'session_id':  body.session_id,
        'received_at': datetime.now(timezone.utc),
        'timestamp':   body.timestamp,
        'text':        body.text,
    }
    result = await db.feedback.insert_one(doc)
    return {'id': str(result.inserted_id)}


@router.get('/feedback')
async def list_feedback(
    skip: int = 0,
    limit: int = 50,
    session_id: Optional[int] = None,
    user=Depends(get_current_user),
):
    db = get_db()
    user_doc = await _get_user_doc(db, user['uid'])
    query = {'user_id': str(user_doc['_id'])}
    if session_id is not None:
        query['session_id'] = session_id
    cursor = db.feedback.find(query).sort('timestamp', -1).skip(skip).limit(limit)
    results = []
    async for doc in cursor:
        doc['id'] = str(doc.pop('_id'))
        results.append(doc)
    return results