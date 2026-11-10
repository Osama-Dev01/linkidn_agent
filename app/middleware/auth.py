import hashlib
import hmac
import re
import secrets
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from typing import Any, Callable
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request, Response
from pymongo.database import Database

SESSION_COOKIE = "author_session"
SESSION_DAYS = 7
ALLOWED_ORIGINS = {"http://127.0.0.1:5173", "http://localhost:5173"}
LOGIN_ATTEMPTS: dict[str, deque[float]] = defaultdict(deque)


def now() -> datetime:
    return datetime.now(timezone.utc)


def _error(field: str, message: str) -> dict[str, str]:
    return {"field": field, "message": message}


def _allowed_origin(request: Request) -> None:
    origin = request.headers.get("origin")
    request_origin = f"{request.url.scheme}://{request.url.netloc}"
    if origin and origin not in ALLOWED_ORIGINS and origin != request_origin:
        raise HTTPException(status_code=403, detail="Request origin is not allowed.")


def get_session(database: Database, request: Request) -> dict[str, Any]:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        raise HTTPException(status_code=401, detail="Authentication required.")
    record = database.auth_sessions.find_one({"token_hash": hashlib.sha256(token.encode()).hexdigest()})
    if not record or record["expires_at"] <= now():
        raise HTTPException(status_code=401, detail="Session expired. Please log in again.")
    return record


def verify_csrf(request: Request, session: dict[str, Any]) -> None:
    _allowed_origin(request)
    supplied = request.headers.get("x-csrf-token", "")
    if not hmac.compare_digest(supplied, session["csrf_token"]):
        raise HTTPException(status_code=403, detail="CSRF token is missing or invalid.")


def _password_hash(password: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1)
    return f"{salt.hex()}:{digest.hex()}"


def _password_matches(password: str, encoded: str) -> bool:
    try:
        salt_hex, digest_hex = encoded.split(":", 1)
        candidate = _password_hash(password, bytes.fromhex(salt_hex)).split(":", 1)[1]
        return hmac.compare_digest(candidate, digest_hex)
    except (ValueError, TypeError):
        return False


def _login_limited(key: str) -> None:
    attempts = LOGIN_ATTEMPTS[key]
    cutoff = time.time() - 900
    while attempts and attempts[0] < cutoff:
        attempts.popleft()
    if len(attempts) >= 14:
        raise HTTPException(status_code=429, detail="Too many login attempts. Try again later.")
    attempts.append(time.time())


def _new_session(database: Database, user: dict[str, Any], request: Request, response: Response) -> dict[str, Any]:
    token = secrets.token_urlsafe(32)
    csrf_token = secrets.token_urlsafe(32)
    database.auth_sessions.insert_one({
        "user_id": user["user_id"],
        "token_hash": hashlib.sha256(token.encode()).hexdigest(),
        "csrf_token": csrf_token,
        "expires_at": now() + timedelta(days=SESSION_DAYS),
        "created_at": now(),
    })
    response.set_cookie(
        SESSION_COOKIE,
        token,
        httponly=True,
        secure=request.url.scheme == "https",
        samesite="lax",
        max_age=SESSION_DAYS * 24 * 60 * 60,
        path="/",
    )
    return {"user": {"user_id": user["user_id"], "name": user["name"], "email": user["email"]}, "csrf": csrf_token}


def create_auth_router(database_for_request: Callable[[], Database]) -> APIRouter:
    router = APIRouter()

    @router.post("/auth/register", status_code=201)
    def register(payload: dict[str, Any], request: Request, response: Response):
        _allowed_origin(request)
        name = payload.get("name")
        email = payload.get("email")
        password = payload.get("password")
        errors = []
        if not isinstance(name, str) or not name.strip() or len(name) > 300:
            errors.append(_error("name", "Enter a name of up to 300 characters."))
        if not isinstance(email, str) or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email) or len(email) > 254:
            errors.append(_error("email", "Enter a valid email address."))
        if not isinstance(password, str) or not 10 <= len(password) <= 128:
            errors.append(_error("password", "Password must contain 10–128 characters."))
        if errors:
            raise HTTPException(status_code=422, detail=errors)

        database = database_for_request()
        email = email.strip().lower()
        if database.users.find_one({"email": email}):
            raise HTTPException(status_code=409, detail="An account with this email already exists.")
        user = {
            "user_id": str(uuid4()),
            "name": name.strip(),
            "email": email,
            "password_hash": _password_hash(password),
            "created_at": now(),
            "updated_at": now(),
        }
        database.users.insert_one(user)
        return _new_session(database, user, request, response)

    @router.post("/auth/login")
    def login(payload: dict[str, Any], request: Request, response: Response):
        _allowed_origin(request)
        email = payload.get("email")
        password = payload.get("password")
        if not isinstance(email, str) or not isinstance(password, str):
            raise HTTPException(status_code=422, detail="Email and password are required.")
        email = email.strip().lower()
        _login_limited(f"{request.client.host if request.client else ''}:{email}")
        database = database_for_request()
        user = database.users.find_one({"email": email})
        if not user or not _password_matches(password, user.get("password_hash", "")):
            raise HTTPException(status_code=401, detail="Email or password is incorrect.")
        return _new_session(database, user, request, response)

    @router.get("/auth/me")
    def current_user(request: Request):
        database = database_for_request()
        session = get_session(database, request)
        user = database.users.find_one({"user_id": session["user_id"]}, {"_id": 0, "user_id": 1, "name": 1, "email": 1})
        if not user:
            raise HTTPException(status_code=401, detail="Account not found.")
        return {"user": user, "csrf": session["csrf_token"]}

    @router.post("/auth/logout")
    def logout(request: Request, response: Response):
        database = database_for_request()
        session = get_session(database, request)
        verify_csrf(request, session)
        database.auth_sessions.delete_one({"_id": session["_id"]})
        response.delete_cookie(SESSION_COOKIE, path="/", httponly=True, samesite="lax")
        return {"ok": True}

    return router
