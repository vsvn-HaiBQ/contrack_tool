# ConTrack environment management — analysis before implementation

## Current architecture

- Vue 3 / TypeScript / Vite frontend, entry `frontend/src/main.ts`, routes in `frontend/src/router.ts`, navigation in `modules/layout/AppShell.vue`.
- FastAPI / SQLAlchemy backend, entry `backend/app/main.py`. Feature modules expose routers. PostgreSQL stores tool metadata; Redis stores login sessions and Celery jobs. SQL migrations run at startup.
- Cookie authentication and configurable menu permissions are already shared infrastructure. The existing `versions` module manages build branch / Box folder metadata, not deployed Linux environments; it must remain separate.
- Node `local-server/server.cjs` runs on the user's Windows machine. `lib/build-source.cjs` builds and packages WAR files. It does not deploy WARs, control Tomcat, or restore PostgreSQL baselines.
- No existing Tomcat start/stop/deploy implementation, application database schema-version query, or managed Git/SVN Docker service was found. GitHub integration and local Git operations are not Git/SVN server administration.
- Compose currently starts frontend/Nginx, API, Celery, PostgreSQL 16, Redis, OpenXML and FileHandler. It does not start the target ConTrack Java application, Git server or SVN server. External repository servers described in the request are treated as pre-existing services.
- Configuration: backend Pydantic environment settings, user/system DB settings, browser runtime `config.js`, Node environment settings. Logging includes request IDs, audit DB records and Node job logs. There is no environment run history.

## Reusable components

- FastAPI router registration, cookie authentication, menu permission dependency.
- Frontend `shared/http.ts`, session permissions, application shell and existing Tailwind visual conventions.
- PostgreSQL tooling conventions, but **not the tool's metadata database** as the target ConTrack working database.
- Existing Git/SVN services through trusted repository profile URL mapping; MVP does not restart, replace or mutate these services.

## Minimal edits to existing files

1. `backend/app/main.py`: import/register the new router only.
2. `backend/app/modules/users/service.py`: declare one new configurable permission only.
3. `backend/requirements.txt`: explicitly declare YAML parsing dependency.
4. `frontend/src/router.ts`: register a new lazy-loaded page; permit it without Redmine settings.
5. `frontend/src/modules/layout/AppShell.vue`: append one navigation tab.

Do not change existing feature services, models, SQL migrations, local Node behavior or existing Dockerfiles. In particular preserve the user's pre-existing edit to `frontend/Dockerfile` and untracked `nano.4151428.save`.

## New components

- `backend/app/modules/contrack_environments/`: strict catalog models/readers, isolated administrator configuration, immutable recipe resolution, OS file lock, persistent run/state store, PostgreSQL restore adapter, Tomcat adapter, health checks, preparation orchestration and API.
- `frontend/src/modules/contrack_environments/`: version/profile selection, current environment, preparation progress, logs and run history.
- `backend/tests/`: catalog/security, state/lock, adapters and orchestration regression tests, including upgrade/hotfix/older-version sequences with fake external services.
- `deploy/contrack-environments/`: example configuration, catalogs and optional isolated container setup.
- `docs/contrack-version-management.md`: operator setup and usage.

## Implementation plan

1. Add catalog models/readers; validate unique IDs, available artifacts, contained paths, explicit schema compatibility and declared bundle mappings.
2. Resolve each selection into a fixed recipe. Always create a uniquely named working DB, including same-schema hotfixes and switches to older versions. Never modify or downgrade a baseline/current DB.
3. Add persistent run files and one cross-process OS lock, acquired before queueing. Keep failure logs; only report RUNNING after all health checks pass.
4. Add trusted adapters for standard PostgreSQL utilities and a dedicated Tomcat `CATALINA_BASE`. Config templates and schema query are administrator inputs, never browser/manifest commands. Require configuration before making changes.
5. Prepare DB/repository/config before stopping the current managed Tomcat, then deploy/start/health-check. Reject unmanaged processes on the configured port. Do not automatically roll back or delete failed working DBs.
6. Register API and the independent UI/menu. Existing accounts gain access only when an administrator grants the new permission (admin already has all permissions).
7. Run staged compile/tests and frontend build where the local toolchain permits. Real Linux/Tomcat/PostgreSQL integration requires operator-provided assets and infrastructure and must be reported separately from adapter-based tests.

## Deployment decisions and unknowns

- Root defaults to `/srv/contrack-env` and all subpaths/configuration are configurable. New feature is disabled until an administrator explicitly enables it.
- Use dedicated target PostgreSQL credentials, never infer them from the tool metadata DB. Administrator must provide the actual read-only schema-version query and real Tomcat configuration templates; neither can be inferred from this repository.
- Run target Tomcat beside the API in an opt-in Linux runtime, or run the API on the Linux host with required tools installed. Existing Compose services remain unchanged. No Docker socket mount is needed.
- Repository MVP is mapping plus endpoint reachability checks for existing Git/SVN servers. No catalog copies or physical PostgreSQL data directory copies.
- API crashes release the OS lock; unfinished persisted runs must be shown as interrupted and require a fresh preparation. Environment switching is serialized across API processes sharing the same root.

## Implementation and verification record

- Catalog/bundle models, compatibility checks, unique working DB provisioning, Tomcat deployment adapter, repository mapping, persistent runtime/run state, six health checks and failure handling are implemented in the new module.
- UI, authenticated API, permission registration, example catalogs/configuration and opt-in Docker extension are implemented. Existing business services and database schema are unchanged; the only shared-file edits are the registration/dependency lines listed above.
- Python compile/import checks, full web + local-server build and TypeScript `tsc --noEmit` passed.
- Backend suite: 38 passed, 1 opt-in Linux integration test skipped. Node/frontend suite: 28 passed, 3 existing live FileHandler tests skipped. Frontend tests exercise selection defaults, schema filtering, duplicate-submit prevention, validation and failure states.
- A Windows-specific transient `os.replace` access denial was reproduced during sequential state updates. Atomic writes now retry only Windows sharing/access-denial errors for at most 310 ms; deterministic tests verify both transient recovery and preservation of the old file on permanent failure.
- Live Linux/Tomcat/PostgreSQL/repository execution and Docker builds were not run: no real target WAR/baseline/configuration or Docker CLI is provided in this workspace. The real integration test is explicitly opt-in and documented.
- Browser visual inspection could not run because the browser automation host is unavailable; UI logic, Vue compilation and TypeScript checks passed. The temporary preview server was stopped.
