from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from pymongo import ReturnDocument
from pymongo.database import Database
from pymongo.errors import DuplicateKeyError

from app.db.client import get_database
from app.middleware.auth import create_auth_router, get_session, now, verify_csrf
from app.api.validation import REPEAT_SECTIONS, SECTION_FIELDS, validate_section
from app.services.engine import run_engine_task

router = APIRouter(prefix="/api")
db: Database = get_database()
router.include_router(create_auth_router(lambda: db))


@router.post("/engine/run", status_code=202)
def start_engine(request: Request, background_tasks: BackgroundTasks):
    session = get_session(db, request)
    verify_csrf(request, session)
    running_message = "Engine currently running. Your current run will continue; no new engine was started."
    if db.engine_runs.find_one({"_id": session["user_id"]}):
        raise HTTPException(status_code=409, detail=running_message)
    profile = db.profiles.find_one({"user_id": session["user_id"]}, {"_id": 0})
    sections = (*SECTION_FIELDS, *REPEAT_SECTIONS)
    if not profile or any(
        section not in profile or validate_section(section, profile[section])
        for section in sections
    ):
        raise HTTPException(status_code=422, detail="Complete your profile first. Save all eight sections before running the engine.")

    try:
        db.engine_runs.insert_one({"_id": session["user_id"]})
    except DuplicateKeyError:
        raise HTTPException(status_code=409, detail=running_message)
    background_tasks.add_task(run_engine_task, profile)
    return {"message": "Engine started. Check your email for review requests."}


@router.get("/published-posts")
def get_published_posts(request: Request):
    session = get_session(db, request)
    posts = db.published_posts.find(
        {"user_id": session["user_id"]},
        {"_id": 0, "post_id": 1, "title": 1, "final_text": 1, "published_at": 1},
    ).sort("published_at", -1)
    return {"posts": list(posts)}


@router.get("/profile")
def get_profile(request: Request):
    session = get_session(db, request)
    profile = db.profiles.find_one(
        {"user_id": session["user_id"]},
        {"_id": 0, "user_id": 1, "identity": 1, "expertise": 1, "audience": 1,
         "interests": 1, "preferences": 1, "writing_samples": 1, "stances": 1, "experiences": 1},
    )
    sections = {key: value for key, value in (profile or {}).items() if key != "user_id"}
    return {"user_id": session["user_id"], "sections": sections}


@router.put("/profile/{section}")
def save_profile_section(section: str, payload: dict[str, Any], request: Request):
    session = get_session(db, request)
    verify_csrf(request, session)
    errors = validate_section(section, payload)
    if errors:
        raise HTTPException(status_code=422, detail=errors)

    timestamp = now()
    profile = db.profiles.find_one_and_update(
        {"user_id": session["user_id"]},
        {
            "$set": {section: payload, "updated_at": timestamp},
            "$setOnInsert": {"user_id": session["user_id"], "created_at": timestamp},
        },
        upsert=True,
        return_document=ReturnDocument.AFTER,
        projection={
            "_id": 0, "user_id": 1, "identity": 1, "expertise": 1, "audience": 1,
            "interests": 1, "preferences": 1, "writing_samples": 1, "stances": 1, "experiences": 1,
        },
    )
    sections = {key: value for key, value in profile.items() if key not in {"user_id", "created_at", "updated_at"}}
    return {"user_id": session["user_id"], "sections": sections}
