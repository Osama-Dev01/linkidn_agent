# Author Studio frontend

React + Vite profile editor connected to the FastAPI backend.

## Run locally

From the project root:

```powershell
.venv\Scripts\python.exe -m uvicorn app.server:app --host 127.0.0.1 --port 8000
```

In a second terminal:

```powershell
cd frontend
npm install
npm run dev
```

Open http://127.0.0.1:5173. Vite proxies `/api` to port 8000. MongoDB must be reachable; the backend uses `MONGODB_URI` and `MONGODB_DB` from the existing root `.env`.

## Data flow

- Register or log in with email and password. Each account gets a stable UUID.
- Passwords are scrypt-hashed; opaque sessions use HttpOnly cookies and expire after seven days. Mutations require an allowed Origin and session CSRF token.
- `Save & continue` validates a section and saves it to MongoDB for the authenticated user.
- Incomplete edits live in user-scoped `sessionStorage` only, surviving refresh in the same tab. They are cleared for a section after a successful save and cleared on logout. This is temporary browser storage, not a file export or database replacement.
- Review fetches the saved profile and renders readable cards. Returning users start in review when saved sections exist. Unsaved edits remain separate.
- Required fields are marked *. Exclusions, extra notes, and personal record collections can be empty. Once a record is added, its core fields and sharing choice are required.
- No file import/export, profile versions, or browser-stored authentication tokens.

## Code

- `src/schema.js`: page and field definitions.
- `src/profile.js`: validation and clean API payloads.
- `src/Field.jsx`: reusable active input types.
- `src/Auth.jsx`: registration/login.
- `src/Review.jsx`: saved-profile cards.
- `src/App.jsx`: session, drafts, navigation, and section saves.
- `app/db/schemas.py`: backend validation and storage schemas.
- `app/api/profile.py`: auth and profile endpoints.

## Checks

```powershell
npm test
npm run build
```

Backend integration tests create and delete a uniquely named test database using the configured MongoDB connection (the account needs permission to create it). From the project root:

```powershell
$env:RUN_DB_TESTS = '1'
.venv\Scripts\python.exe -m tests.test_profile_api
```

## Deployment

Serve frontend and `/api` under the same HTTPS origin. Set `COOKIE_SECURE=true` and `APP_ORIGINS=https://your-app.example` on the backend. `APP_ORIGINS` accepts a comma-separated exact-origin allowlist; local defaults are `http://127.0.0.1:5173` and `http://localhost:5173`. Index creation happens at backend startup.

Collections: `users`, `author_profiles`, `auth_sessions`, and `auth_attempts`. Existing graph/checkpoint collections remain unchanged. Email verification and password reset are not implemented.
