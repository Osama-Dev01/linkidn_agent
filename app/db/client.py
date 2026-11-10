from langgraph.checkpoint.mongodb import MongoDBSaver
from pymongo import MongoClient
from pymongo.database import Database

from app.core.config import settings


_client: MongoClient | None = None


def get_client() -> MongoClient:
    global _client

    if _client is None:
        _client = MongoClient(settings.mongodb_uri, serverSelectionTimeoutMS=5000, tz_aware=True)

    return _client


def get_database() -> Database:
    return get_client()[settings.mongodb_db]


def initialize_database() -> Database:
    client = get_client()
    client.admin.command("ping")
    database = client[settings.mongodb_db]
    initialize_profile_indexes(database)
    return database


def initialize_profile_indexes(database: Database) -> None:
    database.users.create_index("user_id", unique=True)
    database.users.create_index("email", unique=True)
    database.profiles.create_index("user_id", unique=True)
    database.preferences.create_index("user_id", unique=True)
    database.auth_sessions.create_index("token_hash", unique=True)
    database.auth_sessions.create_index("expires_at", expireAfterSeconds=0)


def get_checkpointer() -> MongoDBSaver:
    return MongoDBSaver(get_client(), db_name=settings.mongodb_db)


def close_database() -> None:
    global _client

    if _client is not None:
        _client.close()
        _client = None


client = get_client()
