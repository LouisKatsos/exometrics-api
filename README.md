# ExoMetrics API

The backend the Smart Exoskeleton phone app uploads to. It stores exercise
metrics, exoskeleton power/mode events and participant feedback in MongoDB.
Each request is authenticated with a Firebase ID token (the app signs in
anonymously).

Render deploys this repository's `main` branch to
`https://exometrics-api.onrender.com`; the data is in MongoDB Atlas (free M0
cluster, Sydney region). The phone and watch apps are in
SmartExoskeleton/SmartExoskeletonv2.0.

Version 0.2.0 keeps everything 0.1.0 did (identity fields, the feedback
endpoint, the `session_id` filters) and adds the hardening described below.

## Endpoints

All endpoints except `/health*` need `Authorization: Bearer <Firebase ID token>`.

| Method | Path | What it does |
| --- | --- | --- |
| GET | `/health` | Liveness check. Always `{"status": "ok"}` while the process runs. |
| GET | `/health/ready` | Readiness: 200 when MongoDB answers, 503 when it doesn't. |
| POST | `/auth/register` | Creates the caller's user record (safe to call repeatedly). |
| GET / PATCH | `/auth/me` | Read / update the caller's profile. |
| POST | `/metrics/` | Store one metrics entry. |
| POST | `/metrics/batch` | Store up to 500 metrics entries in one request. |
| GET | `/metrics/`, `/metrics/latest` | List (newest first) / latest metrics entry. |
| POST | `/metrics/events/power`, `/metrics/events/mode` | Store a power or mode change. |
| GET | `/metrics/events?type=power_change` | List events, optionally by type. |
| POST / GET | `/metrics/feedback` | Store / list feedback text. |

List endpoints take `skip` and `limit` (default 50, capped at 500), and can be
narrowed with `session_id` and `participant_code`.

### Records and duplicates

The JSON fields match what the app's `MetricsLogger` writes (camelCase, for
example `distanceM`, `sessionId`). Unknown fields are ignored, so older and
newer app builds both work. Every record carries the participant's `username`,
the app's pseudonymous `participantCode` (for example `EXO-4K7Q-9ZMD`, from app
1.1) and the `sessionId` of the app launch.

Uploads are idempotent. App 1.1 and later send an `entryId` with every record;
older builds don't, so their records are identified by a hash of their
content. Sending a record the server already has returns `200
{"id": "...", "duplicate": true}` instead of storing it twice. A new record
returns `201 {"id": "..."}` as before.

`POST /metrics/batch` takes `{"entries": [...]}` and validates each entry on its
own. The response lists one result per entry, in order:

```
{"results": [{"index": 0, "status": "created", "id": "..."},
             {"index": 1, "status": "duplicate", "id": "..."},
             {"index": 2, "status": "invalid", "errors": [...]}],
 "created": 1, "duplicates": 1, "invalid": 1}
```

Validation errors (422) list the field and the problem but never echo the
submitted values, because they are health data.

A data upload from a user who never called `/auth/register` creates the user
record automatically. Read endpoints still answer 404 for an unknown user.

## Configuration

Settings come from environment variables (or a `.env` file locally). See
`.env.example`.

| Variable | Default | Notes |
| --- | --- | --- |
| `MONGO_URI` | `mongodb://localhost:27017` | `mongodb+srv://` or `tls=true` enables TLS with the certifi CA bundle. |
| `DB_NAME` | `exometrics` | |
| `FIREBASE_CREDENTIALS_PATH` | `firebase-service-account.json` | Service account key file. |
| `FIREBASE_CREDENTIALS_JSON` | unset | The key file's JSON content; used instead of the path when set. |
| `CHECK_REVOKED_TOKENS` | `false` | `true` adds a Firebase lookup per request. |
| `ENVIRONMENT` | `production` on Render, else `development` | Render sets `RENDER=true`, so deploys there are production automatically. Production turns `/docs` off and HSTS on. |
| `ENABLE_DOCS` | unset | Forces `/docs` on or off regardless of environment. |
| `LOG_LEVEL` | `INFO` | |
| `CORS_ORIGINS` | empty | Exact browser origins allowed, comma-separated. Empty: none (the app doesn't need CORS). Credentials are never allowed. |
| `MAX_BODY_BYTES` | `1048576` | Larger requests get 413. |
| `RATE_LIMIT_PER_MINUTE` | `1200` | Per Firebase user, per server process; above what an old app build uses to empty its backlog. `0` turns it off. |
| `IP_RATE_LIMIT_PER_MINUTE` | `6000` | Per client IP, all requests: a flood guard set high because study phones may share an address. `0` turns it off. |
| `MAX_BATCH_SIZE` | `500` | Entries per `/metrics/batch` request. |

## Running locally

```
python -m venv .venv
.venv\Scripts\activate        (Windows)   or   source .venv/bin/activate
pip install -r requirements-dev.txt
copy .env.example .env        (then fill in MONGO_URI and the Firebase key)
uvicorn app.main:app --reload
```

## Tests

```
pip install -r requirements-dev.txt
python -m pytest
```

The tests use an in-memory MongoDB (mongomock-motor) and a stub in place of
Firebase, so they need no network or credentials.

## Deploying on Render

Render deploys the backend repository's `main` branch. If the service builds from
the `Dockerfile`, nothing else is needed: the image runs as an unprivileged user
on port 8080 with proxy headers on. If the Firebase key is a Render Secret File,
make sure it is readable by that user, or use `FIREBASE_CREDENTIALS_JSON`.

For a native Python service instead:

- Build command: `pip install -r requirements.txt`
- Start command: `uvicorn app.main:app --host 0.0.0.0 --port $PORT --proxy-headers --forwarded-allow-ips="*" --no-server-header`

Either way:

- Health check path: `/health`
- Environment: `MONGO_URI`, `DB_NAME`, and the Firebase key either as a
  Secret File (point `FIREBASE_CREDENTIALS_PATH` at it, for example
  `/etc/secrets/firebase-service-account.json`) or as `FIREBASE_CREDENTIALS_JSON`.
  `ENVIRONMENT` needs no setting on Render (see above).

On startup the API creates the MongoDB indexes it needs (including the unique
indexes that back duplicate detection). If one can't be created, for example
because the `users` collection already holds duplicate users, it logs a warning
and keeps running; duplicate detection then still works through a lookup
before each insert.

The rate limiter keeps its counts in memory, so with several instances each
one limits on its own.

## Compatibility with older app builds

Valid records from existing app builds are stored and answered as before.
The new range checks only reject values no real device produces (for example
a heart rate above 300). Compared with the live 0.1.0:

- A request without an `Authorization` header gets 401 (it used to get 422).
- A 422 response no longer includes `body_received` or `content_type`.
- Browsers from other origins are no longer allowed by default (`CORS_ORIGINS`).
- `/docs` is off when `ENVIRONMENT=production`.

`/metrics/batch` and the `participant_code` field and filter are new. The app
falls back to per-line uploads when `/metrics/batch` is missing, so the server
and the app can be updated in either order.
