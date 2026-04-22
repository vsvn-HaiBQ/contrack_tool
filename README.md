# Contrack

Operational web app for JP/VN ticket flow, logtime, and pull request management.

## Stack

- Backend: FastAPI
- Frontend: Vue 3 + TypeScript
- DB: PostgreSQL
- Session/cache: Redis
- Deploy: Docker Compose

## Included flows

- First-run admin setup flow
- User settings and system settings
- JP to VN sync workflow
- Managed ticket detail and ticket links
- Logtime grid
- Pull request creation flow

## Module architecture

Backend:

- `app/modules/auth`
- `app/modules/users`
- `app/modules/settings`
- `app/modules/tickets`
- `app/modules/logtime`
- `app/modules/pull_requests`
- `app/modules/redmine`
- `app/modules/github`

Frontend:

- `src/modules/auth`
- `src/modules/layout`
- `src/modules/settings`
- `src/modules/tickets`
- `src/modules/logtime`
- `src/modules/pull_requests`
- `src/shared`

## Run with Docker

```bash
docker compose up --build
```

Services:

- Frontend: `http://localhost:8888`
- Backend API: `http://localhost:8009/api`

## Run locally

Backend:

```bash
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8009
```

Frontend:

```bash
cd frontend
npm install
npm run dev
```

Default local ports:

- PostgreSQL: `5439`
- Frontend: `8888`
- Backend API: `8009`

## Notes

- Redmine and GitHub integrations now run only through the real HTTP clients in `app/modules/redmine` and `app/modules/github`.
- There is no fallback mock path. Missing host, project, token, or API key now returns explicit errors from the API.
- Local backend config now reads PostgreSQL, Redis, and `MASTER_KEY` from `backend/.env`.
- When the database is empty, the login screen switches to initial admin setup instead of relying on a hard-coded seeded account.
- The settings screen includes integration status and per-service test connection actions so environment issues can be checked before using sync, logtime, or PR flows.
- The schema and docs remain in `docs/` and `sql/`.
- The app is organized by feature module so integration code, routers, and UI flows stay isolated by domain.
