from fastapi import APIRouter, Depends, HTTPException
from app.dependencies import get_current_user
from app.database import get_db
from app.models.user import UserCreate, UserUpdate, UserResponse
from datetime import datetime, timezone

router = APIRouter(prefix='/auth', tags=['auth'])


@router.post('/register')
async def register(body: UserCreate, user=Depends(get_current_user)):
    db = get_db()
    existing = await db.users.find_one({'firebase_uid': user['uid']})
    if existing:
        return {'message': 'User already exists', 'id': str(existing['_id'])}
    doc = {
        'firebase_uid': user['uid'],
        'email': user.get('email', ''),
        'display_name': body.display_name,
        'preferences': {},
        'created_at': datetime.now(timezone.utc),
        'updated_at': datetime.now(timezone.utc),
    }
    result = await db.users.insert_one(doc)
    return {'message': 'User created', 'id': str(result.inserted_id)}


@router.get('/me')
async def get_me(user=Depends(get_current_user)):
    db = get_db()
    doc = await db.users.find_one({'firebase_uid': user['uid']})
    if not doc:
        raise HTTPException(status_code=404, detail='Profile not found')
    doc['id'] = str(doc.pop('_id'))
    return doc


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
