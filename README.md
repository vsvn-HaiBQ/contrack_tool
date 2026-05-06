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

The backend image builds the frontend and local-server release artifacts inside Docker, then copies them into the Python runtime image. A clean Linux server does not need a pre-existing `build_output` directory before running Docker Compose.

Services:

- Frontend: `http://localhost:8888`
- Backend API: `http://localhost:8009/api`
- OpenXML API: `http://localhost:5000`

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

Node processing server for Build Source, Fix EOL, and document translation orchestration:

```bash
corepack pnpm local-server
```

Default local ports:

- PostgreSQL: `5439`
- Frontend: `8888`
- Backend API: `8009`
- OpenXML API: `5000`
- Node processing server: `3219`

## Document Translation Server Plan

Office document translation is split into two server responsibilities:

- `openxml/`: ASP.NET Core API that extracts and rewrites `.docx`, `.xlsx`, and `.pptx` text segments.
- `local-server/`: Node.js processing server that calls OpenXML, prompts Codex CLI, and writes the translated file on the user's machine.

Node endpoints:

- `GET /document-translation/health`
- `POST /document-translation/sheets`
- `POST /document-translation/extract`
- `POST /document-translation/translate`
- `GET /document-translation/jobs/{job_id}`

Frontend route: `/document-translation` (`Translate Docs` tab). The UI translates all visible sheets in `.xlsx` files; there is no sheet selection flow.

Codex CLI must be installed and logged in on the machine running the Node processing server. In the web UI, OpenXML defaults to `http://<current-web-host>:5000`, so a production page opened by IP will call OpenXML on that same IP. Override it with `window.CONTRACK_CONFIG.openXmlBase`, `VITE_OPENXML_BASE`, or `CONTRACK_OPENXML_BASE_URL` when needed. See `docs/document-translation-codex-plan.md` for the full flow and environment options.

## Build web + local server

```bash
corepack pnpm build
```

This builds the Vite web app to `build_output/web` for the shared web server and writes the Node processing package to `build_output/local-server`.
It also writes an update bundle and manifest to `build_output/releases/local-server`:

- `latest.json`
- `contrack-local-server-{version}.bundle.json.gz`
- `contrack-local-server-{version}.zip`

Deploy `build_output/web` on the shared server, then edit `build_output/web/config.js` only if the Node processing server is not running on the user's local machine at port `3219`.
Run `build_output/local-server/start-local-server.bat` on the Windows machine that performs source builds and Working Tree EOL fixes.
The launcher binds to `127.0.0.1:3219` by default and keeps a visible console open while the Node server is running. Use `Ctrl+C` in that console to stop it.

`config.js` is loaded at runtime, so the shared web build does not need to be rebuilt when the Node processing URL changes:

```js
window.CONTRACK_CONFIG = {
  apiBase: "/api",
  nodeServerBase: "http://127.0.0.1:3219",
  openXmlBase: `http://${window.location.hostname || "127.0.0.1"}:5000`,
};
```

If the Node processing server is centralized on another Windows build machine, set `CONTRACK_LOCAL_SERVER_HOST=0.0.0.0`, change `nodeServerBase` to that host, and set `CONTRACK_ALLOWED_ORIGINS` on the Node server, for example `http://contrack-server:8888`.

## Local Node server update flow

The backend acts as the release server for the local Node processing server:

- `GET /api/local-server/releases/latest` returns the latest release manifest for authenticated users.
- `POST /api/local-server/releases/{version}/download-ticket` returns a short-lived signed download URL.
- `GET /api/local-server/releases/{version}/download?token=...` serves the update bundle after token validation.

The frontend compares the backend release with the local Node `/health` version and shows an update action when a newer bundle exists. When clicked, the local Node server downloads the signed bundle from the backend, verifies `sha256`, stages the files under `.updates`, then restarts through an updater script. Bump the root `package.json` `version` before building a new local Node release.
If the local Node server is offline, the header shows a Download action that fetches the latest `contrack-local-server-{version}.zip` package from the backend so the user can install or restart it manually.

Admin shortcut:

```bat
create-version.bat patch
create-version.bat 0.2.0 --deploy
```

Linux/SSH shortcut:

```bash
chmod +x create-version.sh
./create-version.sh patch
./create-version.sh 0.2.0 --deploy
```

## Notes

- Redmine and GitHub integrations now run only through the real HTTP clients in `app/modules/redmine` and `app/modules/github`.
- There is no fallback mock path. Missing host, project, token, or API key now returns explicit errors from the API.
- Local backend config now reads PostgreSQL, Redis, and `MASTER_KEY` from `backend/.env`.
- When the database is empty, the login screen switches to initial admin setup instead of relying on a hard-coded seeded account.
- The settings screen includes integration status and per-service test connection actions so environment issues can be checked before using sync, logtime, or PR flows.
- The schema and docs remain in `docs/` and `sql/`.
- The app is organized by feature module so integration code, routers, and UI flows stay isolated by domain.
