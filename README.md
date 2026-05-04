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
corepack pnpm install
corepack pnpm dev
```

Node processing server for Build Source and Fix EOL:

```bash
corepack pnpm local-server
```

Default local ports:

- PostgreSQL: `5439`
- Frontend: `8888`
- Backend API: `8009`
- Node processing server: `3219`

## Build web + local server

```bash
corepack pnpm build
```

This builds the Vite web app to `build_output/web` for the shared web server and writes the Node processing package to `build_output/local-server`.
Deploy `build_output/web` on the shared server, then edit `build_output/web/config.js` only if the Node processing server is not running on the user's local machine at port `3219`.
Run `build_output/local-server/start-local-server.bat` on the Windows machine that performs source builds and Working Tree EOL fixes.
The launcher binds to `127.0.0.1:3219` by default and keeps a visible console open while the Node server is running. Use `Ctrl+C` in that console to stop it.

`config.js` is loaded at runtime, so the shared web build does not need to be rebuilt when the Node processing URL changes:

```js
window.CONTRACK_CONFIG = {
  apiBase: "/api",
  nodeServerBase: "http://127.0.0.1:3219",
};
```

If the Node processing server is centralized on another Windows build machine, set `CONTRACK_LOCAL_SERVER_HOST=0.0.0.0`, change `nodeServerBase` to that host, and set `CONTRACK_ALLOWED_ORIGINS` on the Node server, for example `http://contrack-server:8888`.

## Notes

- Redmine and GitHub integrations now run only through the real HTTP clients in `app/modules/redmine` and `app/modules/github`.
- There is no fallback mock path. Missing host, project, token, or API key now returns explicit errors from the API.
- Local backend config now reads PostgreSQL, Redis, and `MASTER_KEY` from `backend/.env`.
- When the database is empty, the login screen switches to initial admin setup instead of relying on a hard-coded seeded account.
- The settings screen includes integration status and per-service test connection actions so environment issues can be checked before using sync, logtime, or PR flows.
- The schema and docs remain in `docs/` and `sql/`.
- The app is organized by feature module so integration code, routers, and UI flows stay isolated by domain.
