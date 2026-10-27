import logging
from typing import Optional
from urllib.parse import parse_qs, urlsplit

import certifi
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from pymongo import ASCENDING, DESCENDING
from pymongo.errors import ConnectionFailure

from app.config import settings

logger = logging.getLogger(__name__)

client: Optional[AsyncIOMotorClient] = None

# Only documents written by this version carry idem_key, so the unique index
# must ignore the older ones.
_HAS_IDEM_KEY = {'idem_key': {'$exists': True}}

INDEXES = {
    'users': [
        ([('firebase_uid', ASCENDING)], {'name': 'firebase_uid_unique', 'unique': True}),
    ],
    'metrics_entries': [
        ([('user_id', ASCENDING), ('timestamp', DESCENDING)], {'name': 'user_timestamp'}),
        ([('user_id', ASCENDING), ('idem_key', ASCENDING)],
         {'name': 'user_idem_key_unique', 'unique': True, 'partialFilterExpression': _HAS_IDEM_KEY}),
    ],
    'events': [
        ([('user_id', ASCENDING), ('timestamp', DESCENDING)], {'name': 'user_timestamp'}),
        ([('user_id', ASCENDING), ('type', ASCENDING), ('timestamp', DESCENDING)], {'name': 'user_type_timestamp'}),
        ([('user_id', ASCENDING), ('idem_key', ASCENDING)],
         {'name': 'user_idem_key_unique', 'unique': True, 'partialFilterExpression': _HAS_IDEM_KEY}),
    ],
    'feedback': [
        ([('user_id', ASCENDING), ('timestamp', DESCENDING)], {'name': 'user_timestamp'}),
        ([('user_id', ASCENDING), ('idem_key', ASCENDING)],
         {'name': 'user_idem_key_unique', 'unique': True, 'partialFilterExpression': _HAS_IDEM_KEY}),
    ],
}


def _use_tls(uri: str) -> bool:
    if settings.mongo_tls is not None:
        return settings.mongo_tls
    if uri.lower().startswith('mongodb+srv://'):
        return True
    params = {key.lower(): values for key, values in parse_qs(urlsplit(uri).query).items()}
    return any(value.lower() == 'true' for key in ('tls', 'ssl') for value in params.get(key, []))


def get_db() -> AsyncIOMotorDatabase:
    if client is None:
        raise RuntimeError('Database is not connected; connect_db() runs at startup.')
    return client[settings.db_name]


async def connect_db():
    global client
    if client is not None:
        return
    options = {
        'serverSelectionTimeoutMS': settings.mongo_server_selection_timeout_ms,
        'appname': 'exometrics-api',
    }
    if _use_tls(settings.mongo_uri):
        options['tlsCAFile'] = certifi.where()
    client = AsyncIOMotorClient(settings.mongo_uri, **options)


async def close_db():
    global client
    if client is not None:
        client.close()
        client = None


async def ping() -> bool:
    try:
        await get_db().command('ping')
        return True
    except Exception as exc:
        logger.warning('Database ping failed: %s', type(exc).__name__)
        return False


# Roles that reach beyond this one database. The API's database user only
# needs readWrite on settings.db_name (least privilege).
_BROAD_ROLES = {
    'atlasAdmin', 'root', 'readWriteAnyDatabase', 'dbAdminAnyDatabase',
    'userAdminAnyDatabase', 'clusterAdmin', 'clusterManager', 'dbOwner',
}


async def warn_if_over_privileged():
    """Logs a warning when the connected database user has more rights than
    the API needs. Never blocks startup."""
    try:
        status = await get_db().command({'connectionStatus': 1})
        roles = status.get('authInfo', {}).get('authenticatedUserRoles', [])
        broad = sorted({r.get('role') for r in roles if r.get('role') in _BROAD_ROLES})
        if broad:
            logger.warning(
                'Database user has broad roles %s; give the API a user with readWrite on %r only',
                broad, settings.db_name,
            )
    except Exception as exc:
        logger.info('Could not check database user roles (%s)', type(exc).__name__)


async def ensure_indexes():
    """Creates the indexes the API relies on. A failure is logged, never fatal."""
    db = get_db()
    for collection, specs in INDEXES.items():
        for keys, options in specs:
            try:
                await db[collection].create_index(keys, **options)
            except ConnectionFailure as exc:
                # Database unreachable: stop here instead of waiting out the
                # timeout once per index. They are created on the next start.
                logger.warning('Skipping index creation, database unreachable (%s)', type(exc).__name__)
                return
            except Exception as exc:
                logger.warning(
                    'Could not create index %s on %s (%s); the API keeps working without it',
                    options['name'], collection, type(exc).__name__,
                )
