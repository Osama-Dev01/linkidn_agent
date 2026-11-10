from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pymongo.errors import PyMongoError

from app.api.profile import router
from app.db.client import initialize_database


@asynccontextmanager
async def lifespan(app: FastAPI):
    initialize_database()
    yield


def print_preferences(user_id, preferences):
    print(f"\nUser ID: {user_id}")
    print("=" * 60)

    for category, values in preferences.items():
        if category == "field_metadata":
            continue

        print(f"\n{category.replace('_', ' ').upper()}")
        print("-" * 40)

        if isinstance(values, dict):
            for key, value in values.items():
                label = key.replace("_", " ").title()
                print(f"\n  {label}:")

                if isinstance(value, list):
                    for item in value:
                        print(f"    - {item}")
                else:
                    print(f"    {value}")
        else:
            print(f"  {values}")

    print("\n" + "=" * 60)








app = FastAPI(title="Author Studio", lifespan=lifespan)
app.include_router(router)


@app.exception_handler(PyMongoError)
async def database_error(request: Request, error: PyMongoError):
    return JSONResponse({"detail": "Database unavailable. Please try again."}, status_code=503)


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, error: RequestValidationError):
    details = [
        {
            "field": ".".join(map(str, item["loc"][1:])),
            "message": item["msg"],
        }
        for item in error.errors()
    ]
    return JSONResponse({"detail": details}, status_code=422)


@app.get("/health")
def health():
    return {"status": "ok"}
