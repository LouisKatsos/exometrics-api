from motor.motor_asyncio import AsyncIOMotorClient
from app.config import settings
import certifi

client: AsyncIOMotorClient = None


def get_db():
    return client[settings.db_name]


async def connect_db():
    global client
    client = AsyncIOMotorClient(settings.mongo_uri, tlsCAFile=certifi.where())


async def close_db():
    global client
    if client:
        client.close()
