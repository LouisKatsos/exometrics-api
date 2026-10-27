from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pymongo.errors import DuplicateKeyError

from app.database import get_db
from app.dependencies import get_current_user
from app.models.user import UserCreate, UserUpdate
from app.records import new_user_doc, serialize

router = APIRouter(prefix='/auth', tags=['auth'])


@router.post('/register')
async def register(body: UserCreate, user=Depends(get_current_user)):
    db = get_db()
    existing = await db.users.find_one({'firebase_uid': user['uid']})
    if existing:
        return {'message': 'User already exists', 'id': str(existing['_id'])}
    doc = new_user_doc(user['uid'], user.get('email', ''), body.display_name)
    try:
        result = await db.users.insert_one(doc)
    except DuplicateKeyError:
        # A parallel request registered the same user first.
        existing = await db.users.find_one({'firebase_uid': user['uid']})
        return {'message': 'User already exists', 'id': str(existing['_id'])}
    return {'message': 'User created', 'id': str(result.inserted_id)}


@router.get('/me')
async def get_me(user=Depends(get_current_user)):
    db = get_db()
    doc = await db.users.find_one({'firebase_uid': user['uid']})
    if not doc:
        raise HTTPException(status_code=404, detail='Profile not found')
    return serialize(doc)


@router.patch('/me')
async def update_me(body: UserUpdate, user=Depends(get_current_user)):
    db = get_db()
    update_data = {k: v for k, v in body.model_dump().items() if v is not None}
    update_data['updated_at'] = datetime.now(timezone.utc)
    await db.users.update_one(
        {'firebase_uid': user['uid']},
        {'$set': update_data}
    )
    return {'message': 'Profile updated'}
